from __future__ import annotations

import json
import os
import posixpath
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .storage import atomic_write, state_directory, writer_lock
from .usage_log import read_usage


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
        "used_resources": [],
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


def normalize_used_resource(value: object) -> str:
    """Normalize a used-resource entry the same way as target paths.

    Leading ./ segments and redundant separators are stripped so "./old.md"
    matches the "old.md" card; absolute paths and parent-directory escapes
    are rejected instead of stored.
    """
    text = str(value) if value is not None else ""
    if not text:
        raise SessionError(f"used resource is empty: {value!r}")
    normalized = posixpath.normpath(text)
    candidate = PurePosixPath(normalized)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise SessionError(f"used resource escapes the knowledge bundle: {value!r}")
    return normalized


def _sanitized_reads(resources: Iterable[object]) -> list[str]:
    """Keep card resources and repo-relative paths; reject escapes.

    Absolute paths and parent-directory escapes must never reach the session
    record: a --used-resource value is matched against KB-relative paths and
    card resources only.
    """
    return sorted({normalize_used_resource(item) for item in resources})


def record_session_reads(root: Path, session_id: str, resources: list[str]) -> dict[str, Any]:
    """Record docs this session read directly (agent Read/cat, outside kb search).

    Retrieval via kb search/context/show also lands here (see cli), so the
    gate works with the usage log disabled; this covers direct reads too.
    Only active sessions can record reads.
    """
    cleaned = _sanitized_reads(resources)
    path = _path(root, session_id)
    with writer_lock(_state(root)):
        record = _read(root, session_id)
        if record["state"] != "active":
            raise SessionError("only active sessions can record reads")
        merged = sorted(set(record.get("used_resources", [])) | set(cleaned))
        record["used_resources"] = merged
        record["updated_at"] = _now()
        _write(path, record)
        _event(root, session_id, "record-read", resources=merged)
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


def session_used_resources(root: Path, session_id: str | None) -> set[str]:
    """Docs the session used: kb retrieval cards plus recorded direct reads.

    Retrieval (search/context/show) lands in both the usage log and the
    session record, so the gate works with the usage log disabled. Related
    suggestions deliberately do not count as used, including entries kept
    from before that exclusion: only search, context, and show entries are
    read back. Direct file reads land in the session record via
    record_session_reads (repo-relative paths are resolved to the card
    resources the freshness report names).
    """
    if not session_id:
        return set()
    used: set[str] = set()
    try:
        entries = read_usage(root)
    except Exception:
        entries = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("session_id") != session_id:
            continue
        if entry.get("command") not in ("search", "context", "show"):
            continue
        cards = entry.get("cards")
        if isinstance(cards, list):
            used.update(str(card) for card in cards if card)
    try:
        record = _read(root, session_id)
    except (FileNotFoundError, SessionError):
        record = {}
    stored = record.get("used_resources", []) if isinstance(record, dict) else []
    if isinstance(stored, list):
        used.update(str(item) for item in stored if item)
    if not used:
        return used
    try:
        database = state_directory(root) / "index.sqlite3"
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
        try:
            rows = connection.execute("SELECT resource, relative_file FROM concepts").fetchall()
        finally:
            connection.close()
    except Exception:
        rows = []
    for resource, relative_file in rows:
        if relative_file in used:
            used.add(resource or relative_file)
    return used
