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
