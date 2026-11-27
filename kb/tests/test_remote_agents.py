"""Tests for remote coding-agent launcher and monitor (eos_kb.remote_agents + MCP tools)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from eos_kb.mcp_tools import McpToolError, dispatch_tool
from eos_kb.remote_agents import (
    RemoteAgentError,
    followup_remote_agent,
    list_remote_agents,
    logs_remote_agent,
    start_remote_agent,
    status_remote_agent,
    stop_remote_agent,
)


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work_root = tmp_path / "work"
    personal_root = tmp_path / "personal"
    (work_root / "backend").mkdir(parents=True)
    (personal_root / "eos").mkdir(parents=True)
    monkeypatch.setenv("EOS_WORK_ROOT", str(work_root))
    monkeypatch.setenv("EOS_PERSONAL_ROOT", str(personal_root))
    monkeypatch.setenv("EOS_REMOTE_AGENTS_DIR", str(tmp_path / "remote-agents"))


def test_work_profile_allows_only_claude_and_blocks_escape(tmp_path: Path) -> None:
    with pytest.raises(RemoteAgentError, match="not permitted"):
        start_remote_agent("work", name="debug-codex", prompt="check logs", cwd="backend", agent="codex")

    with pytest.raises(RemoteAgentError, match="outside"):
        start_remote_agent("work", name="escape", prompt="read", cwd="../personal/eos", agent="claude")


def test_start_monitor_followup_and_stop_lifecycle(tmp_path: Path) -> None:
    fake_stream = json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Root cause found in worker.py"}]},
        }
    )
    fake_result = json.dumps({"type": "result", "result": "Fixed root cause summary."})
    cmd = [sys.executable, "-c", f"print({fake_stream!r}); print({fake_result!r})"]

    meta = start_remote_agent(
        "work",
        name="Order Sync Debug",
        prompt="Investigate order sync lag",
        cwd="backend",
        agent="claude",
        command_override=cmd,
    )
    run_id = meta["run_id"]
    assert meta["name"] == "Order Sync Debug"
    assert meta["profile"] == "work"

    for _ in range(30):
        st = status_remote_agent("work", run_id=run_id)
        if st["status"] != "running":
            break
        time.sleep(0.1)

    assert st["status"] == "completed"
    assert st["final_result"] == "Fixed root cause summary."
    assert any("Root cause found" in e for e in st["recent_events"])

    # Profile isolation: personal cannot see work runs
    assert list_remote_agents("personal") == []
    assert len(list_remote_agents("work")) == 1

    # Logs formatted cleanly
    log_res = logs_remote_agent("work", run_id=run_id)
    assert "Root cause found" in log_res["text"]

    # Follow-up increments turn and appends output
    followup_cmd = [
        sys.executable,
        "-c",
        f"print({json.dumps({'type': 'result', 'result': 'Follow-up complete.'})!r})",
    ]
    meta2 = followup_remote_agent("work", run_id=run_id, prompt="Check tests too", command_override=followup_cmd)
    assert meta2["turns"] == 2
    for _ in range(30):
        st2 = status_remote_agent("work", run_id=run_id)
        if st2["status"] != "running":
            break
        time.sleep(0.1)
    assert st2["status"] == "completed"
    assert st2["final_result"] == "Follow-up complete."


def test_stop_running_agent(tmp_path: Path) -> None:
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    meta = start_remote_agent(
        "personal",
        name="Long Job",
        prompt="sleep",
        cwd="eos",
        agent="codex",
        command_override=cmd,
    )
    stopped = stop_remote_agent("personal", run_id=meta["run_id"])
    assert stopped["status"] == "stopped"


def test_mcp_dispatch_enforces_work_claude_only(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    with pytest.raises(McpToolError, match="not permitted"):
        dispatch_tool(
            kb,
            "work",
            "agent_start",
            {"name": "bad", "prompt": "hi", "cwd": "backend", "agent": "gemini"},
        )
    res = dispatch_tool(kb, "work", "agent_list", {})
    assert "No remote agent sessions" in res["text"]
