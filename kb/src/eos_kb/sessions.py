from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import atomic_write, state_directory, writer_lock


class SessionError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state(root: Path) -> Path:
    path = state_directory(root) / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(root: Path, session_id: str) -> Path:
    return _state(root) / f"{session_id}.json"


def _read(root: Path, session_id: str) -> dict[str, Any]:
    path = _path(root, session_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SessionError(f"session {session_id!r} not found") from exc


def _write(path: Path, value: dict[str, Any]) -> None:
    atomic_write(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def _event(root: Path, session_id: str, event_type: str, **data: Any) -> None:
    directory = state_directory(root) / "events"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session_id}.jsonl"
    event = {"at": _now(), "type": event_type, **data}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_start_token(pid: int | None) -> str | None:
    """Return a kernel process identity where the platform exposes one."""
    if not pid:
        return None
    stat = Path(f"/proc/{pid}/stat")
    try:
        fields = stat.read_text(encoding="ascii").split()
    except (FileNotFoundError, OSError, UnicodeError):
        return None
    return fields[21] if len(fields) > 21 else None


def start_session(
    root: Path,
    *,
    cwd: Path,
    agent: str,
    profile: str,
    native_id: str | None = None,
    parent_session_id: str | None = None,
    pid: int | None = None,
    lease_seconds: int = 300,
    session_id: str | None = None,
) -> dict[str, Any]:
    session_id = session_id or str(uuid.uuid4())
    path = _path(root, session_id)
    now = _now()
    record = {
        "schema_version": 1,
        "session_id": session_id,
        "native_id": native_id,
        "parent_session_id": parent_session_id,
        "agent": agent,
        "profile": profile,
        "cwd": str(cwd.resolve()),
        "pid": pid if pid is not None else os.getpid(),
        "process_start_token": _process_start_token(pid if pid is not None else os.getpid()),
        "lease_expires_at": datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + lease_seconds, timezone.utc
        ).isoformat(),
        "started_at": now,
        "updated_at": now,
        "state": "active",
        "changed_paths": [],
        "active_investigation_ids": [],
    }
    with writer_lock(_state(root)):
        if path.exists():
            existing = _read(root, session_id)
            if existing.get("state") == "active":
                raise SessionError("session is already active")
            raise SessionError("session ID already exists")
        _write(path, record)
    return record


def resume_session(
    root: Path,
    session_id: str | None = None,
    *,
    native_id: str | None = None,
    lease_seconds: int = 300,
) -> dict[str, Any]:
    if not session_id:
        raise SessionError("session_id is required for resume")
    path = _path(root, session_id)
    with writer_lock(_state(root)):
        record = _read(root, session_id)
        if record["state"] == "active":
            raise SessionError("session is already active")
        if record["state"] == "abandoned" and native_id != record.get("native_id"):
            raise SessionError("abandoned session requires matching native_id")
        if record.get("native_id") and native_id != record["native_id"]:
            raise SessionError("native_id does not match session")
        record["state"] = "active"
        record["updated_at"] = _now()
        record["pid"] = os.getpid()
        record["lease_expires_at"] = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + lease_seconds, timezone.utc
        ).isoformat()
        _write(path, record)
        _event(root, session_id, "resume")
    return record


def checkpoint_session(root: Path, session_id: str, *, changed_paths: list[str] | None = None) -> dict[str, Any]:
    path = _path(root, session_id)
    with writer_lock(_state(root)):
        record = _read(root, session_id)
        if record["state"] != "active":
            raise SessionError("only active sessions can be checkpointed")
        merged = sorted(set(record.get("changed_paths", [])) | set(changed_paths or []))
        record["changed_paths"] = merged
        record["updated_at"] = _now()
        _write(path, record)
        _event(root, session_id, "checkpoint", changed_paths=merged)
    return record


def end_session(root: Path, session_id: str, *, exit_code: int) -> dict[str, Any]:
    record = checkpoint_session(root, session_id)
    path = _path(root, session_id)
    with writer_lock(_state(root)):
        record = _read(root, session_id)
        record["state"] = "ended"
        record["exit_code"] = exit_code
        record["updated_at"] = _now()
        _write(path, record)
        _event(root, session_id, "end", exit_code=exit_code)
    return record


def recover_sessions(root: Path, *, lease_seconds: int = 300, now: datetime | None = None) -> list[dict[str, Any]]:
    current = now or datetime.now(timezone.utc)
    recovered: list[dict[str, Any]] = []
    with writer_lock(_state(root)):
        for path in sorted(_state(root).glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("state") != "active":
                continue
            expires = datetime.fromisoformat(record["lease_expires_at"])
            alive = _pid_alive(record.get("pid"))
            observed_token = _process_start_token(record.get("pid"))
            recorded_token = record.get("process_start_token")
            identity_is_known = observed_token is not None and recorded_token is not None
            if alive and identity_is_known and observed_token == recorded_token:
                continue
            if alive and not identity_is_known and expires > current:
                continue
            if alive and not identity_is_known and expires <= current:
                reason = "lease_expired"
            elif not alive or (identity_is_known and observed_token != recorded_token):
                reason = "owner_not_live"
            else:
                continue
            record["state"] = "abandoned"
            record["abandoned_at"] = current.isoformat()
            record["updated_at"] = current.isoformat()
            _write(path, record)
            _event(root, record["session_id"], "recover", reason=reason)
            recovered.append(record)
    return recovered


def load_session(root: Path, session_id: str) -> dict[str, Any]:
    return _read(root, session_id)
