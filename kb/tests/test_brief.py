"""Tests for Layer 3 proactive pre-meeting/topic brief (eos_kb.brief + MCP kb_brief)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from eos_kb.brief import generate_brief, main as brief_main
from eos_kb.indexer import index_bundle
from eos_kb.mcp_tools import dispatch_tool


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "eos-state"))


def test_brief_combines_context_logs_decisions_and_proposals(tmp_path: Path, capsys) -> None:
    kb = tmp_path / "kb"
    _write(
        kb / "00-index.md",
        "---\ntitle: Index\ntype: Index\n---\n# Index\n",
    )
    _write(
        kb / "projects/eos/arch.md",
        "---\ntitle: EOS Tunnel Architecture\ntype: Note\nresource: kb:test/eos/arch.md\nstatus: stable\nfreshness: historical\n---\n\nCloudflare tunnel exposes /mcp/personal and /mcp/work.\n",
    )
    _write(
        kb / "projects/eos/_pending-kb-updates.md",
        "---\ntitle: EOS Pending\ntype: Knowledge Proposal\n---\n\n- [ ] **Add Layer 3 brief docs** (`projects/eos/arch.md`)\n",
    )
    _write(
        kb / "logs/2026/2026-11-26-meeting.md",
        "---\ntitle: EOS Sync Meeting\ntype: Log\ndate: 2026-11-26\nstatus: stable\nfreshness: historical\nkind: meeting\nproject: eos\n---\n\nAgreed to test Claude Voice with Cloudflare tunnel.\n",
    )
    _write(
        kb / "logs/2026/2026-11-20-decision.md",
        "---\ntitle: Evaluate Voice Latency\ntype: Log\ndate: 2026-11-20\nstatus: stable\nfreshness: historical\nkind: decision\nproject: eos\nrevisit_after: 2026-11-25\n---\n\nRevisit whether thin voice PWA is needed.\n",
    )
    res = index_bundle(kb)
    assert not res.errors

    brief = generate_brief(kb, topic="Cloudflare tunnel", project="eos", as_of=dt.date(2026, 11, 27))
    assert len(brief.context_cards) >= 1
    assert len(brief.due_decisions) == 1
    assert brief.due_decisions[0].title == "Evaluate Voice Latency"
    assert len(brief.recent_logs) == 2
    assert len(brief.pending_proposals) == 1

    md = brief.render_markdown()
    assert "Decisions Due for Revisit" in md
    assert "EOS Sync Meeting" in md
    assert "Add Layer 3 brief docs" in md
    assert "EOS Tunnel Architecture" in md

    assert brief_main(["Cloudflare tunnel", "--kb", str(kb), "--project", "eos", "--as-of", "2026-11-27", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["due_decisions"] == 1

    mcp_res = dispatch_tool(
        kb, "personal", "kb_brief", {"topic": "Cloudflare tunnel", "project": "eos", "as_of": "2026-11-27"}
    )
    assert "EOS Tunnel Architecture" in mcp_res["text"]
    assert "Evaluate Voice Latency" in mcp_res["text"]
