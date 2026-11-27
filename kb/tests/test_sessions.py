from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from eos_kb.sessions import (
    SessionError,
    checkpoint_session,
    end_session,
    load_session,
    recover_sessions,
    resume_session,
    start_session,
)
from eos_kb.storage import state_directory


@pytest.fixture
def state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))
    root = tmp_path / "knowledge"
    root.mkdir()
    return root


def test_session_lifecycle_writes_append_only_checkpoint_and_preserves_parent(
    state_root: Path,
) -> None:
    session = start_session(
        state_root,
        cwd=state_root,
        agent="codex",
        profile="personal",
        native_id="native-1",
        parent_session_id="parent-1",
        pid=os.getpid(),
    )

    checkpoint = checkpoint_session(state_root, session["session_id"], changed_paths=["a.py"])
    ended = end_session(state_root, session["session_id"], exit_code=0)

    assert checkpoint["state"] == "active"
    assert ended["state"] == "ended"
    assert ended["parent_session_id"] == "parent-1"
    events = state_directory(state_root).joinpath("events", f"{session['session_id']}.jsonl")
    assert [json.loads(line)["type"] for line in events.read_text().splitlines()] == [
        "checkpoint",
        "checkpoint",
        "end",
    ]


def test_resume_requires_native_id_for_abandoned_session_and_never_changes_parent(
    state_root: Path,
) -> None:
    session = start_session(
        state_root,
        cwd=state_root,
        agent="codex",
        profile="personal",
        native_id="native-2",
        parent_session_id="parent-2",
        pid=99999999,
        lease_seconds=1,
    )
    now = datetime.now(timezone.utc) + timedelta(seconds=10)
    assert recover_sessions(state_root, now=now, lease_seconds=1)[0]["state"] == "abandoned"

    with pytest.raises(SessionError, match="native_id"):
        resume_session(state_root, session["session_id"], native_id="wrong")
    resumed = resume_session(state_root, session["session_id"], native_id="native-2")
    assert resumed["state"] == "active"
    assert resumed["parent_session_id"] == "parent-2"


def test_start_does_not_replace_an_active_session(state_root: Path) -> None:
    first = start_session(state_root, cwd=state_root, agent="codex", profile="p", native_id="n")
    with pytest.raises(SessionError, match="active"):
        start_session(
            state_root,
            cwd=state_root,
            agent="codex",
            profile="p",
            native_id="n",
            session_id=first["session_id"],
        )


def test_record_session_reads_merges_resources_without_usage_log(
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eos_kb.sessions import record_session_reads, session_used_resources
    from eos_kb.usage_log import record_usage

    session = start_session(
        state_root, cwd=state_root, agent="codex", profile="personal", session_id="s1"
    )
    # With the usage log disabled, retrieval is never recorded: the session
    # record is the only fallback, and the gate must still see direct reads.
    monkeypatch.setenv("EOS_KB_USAGE_LOG", "0")
    monkeypatch.setenv("EOS_AGENT_SESSION_ID", "s1")
    record_usage(
        state_root, command="search", query="q", project=None,
        jev_requested=False, jev_used=False, jev_tokens=0, cards=["kb:demo/a"],
    )
    record_session_reads(state_root, session["session_id"], ["kb:demo/b", "notes/c.md"])
    record_session_reads(state_root, session["session_id"], ["kb:demo/b"])
    assert session_used_resources(state_root, "s1") == {"kb:demo/b", "notes/c.md"}


def test_session_used_resources_unions_usage_log_and_session_record(
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eos_kb.sessions import record_session_reads, session_used_resources
    from eos_kb.usage_log import record_usage

    session = start_session(
        state_root, cwd=state_root, agent="codex", profile="personal", session_id="s1"
    )
    monkeypatch.setenv("EOS_AGENT_SESSION_ID", "s1")
    record_usage(
        state_root, command="search", query="q", project=None,
        jev_requested=False, jev_used=False, jev_tokens=0, cards=["kb:demo/a"],
    )
    record_session_reads(state_root, session["session_id"], ["kb:demo/b"])
    assert session_used_resources(state_root, "s1") == {"kb:demo/a", "kb:demo/b"}
    assert session_used_resources(state_root, "s-other") == set()
    assert session_used_resources(state_root, None) == set()


def test_record_session_reads_rejects_path_escapes(state_root: Path) -> None:
    from eos_kb.sessions import record_session_reads

    session = start_session(
        state_root, cwd=state_root, agent="codex", profile="personal", session_id="s1"
    )
    for bad in ("../escape.md", "/etc/passwd", "a/../../b.md", ""):
        with pytest.raises(SessionError, match="escapes|used resource"):
            record_session_reads(state_root, session["session_id"], [bad])
    assert load_session(state_root, session["session_id"])["used_resources"] == []
    record = record_session_reads(state_root, session["session_id"], ["notes/ok.md", "kb:demo/a"])
    assert record["used_resources"] == ["kb:demo/a", "notes/ok.md"]


def test_record_session_reads_normalizes_repo_relative_paths(state_root: Path) -> None:
    from eos_kb.sessions import load_session, record_session_reads

    session = start_session(
        state_root, cwd=state_root, agent="codex", profile="personal", session_id="s1"
    )
    record = record_session_reads(state_root, session["session_id"], ["./notes/c.md", "a//b.md"])

    assert record["used_resources"] == ["a/b.md", "notes/c.md"]
    assert load_session(state_root, session["session_id"])["used_resources"] == ["a/b.md", "notes/c.md"]


def test_session_used_resources_ignores_non_read_commands(state_root: Path) -> None:
    import json

    from eos_kb.sessions import session_used_resources
    from eos_kb.usage_log import usage_path

    path = usage_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        # A retained old log entry from kb related: suggestions, never used.
        stream.write(json.dumps({"ts": "2026-01-01T00:00:00+00:00", "command": "related", "session_id": "s1", "cards": ["kb:demo/suggested"]}) + "\n")
        # An entry with no command at all: not a read either.
        stream.write(json.dumps({"ts": "2026-01-01T00:00:00+00:00", "session_id": "s1", "cards": ["kb:demo/mystery"]}) + "\n")
        stream.write(json.dumps({"ts": "2026-01-01T00:00:00+00:00", "command": "search", "session_id": "s1", "cards": ["kb:demo/read"]}) + "\n")

    assert session_used_resources(state_root, "s1") == {"kb:demo/read"}
