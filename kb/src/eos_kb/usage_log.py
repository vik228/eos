"""Local, append-only log of retrieval calls.

Each kb search/context call appends one JSON line to usage.jsonl in the KB's
state directory, so agent retrieval behavior (including escalation from plain
BM25 to --jev) can be observed. The log stays on this machine, outside the KB
and the repository. Logging never fails a retrieval command.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .storage import state_directory

USAGE_FILE = "usage.jsonl"
DISABLE_ENV = "EOS_KB_USAGE_LOG"
ESCALATION_WINDOW = timedelta(minutes=10)
_RECENT_ESCALATIONS = 10


def usage_path(kb: Path, *, environ: Mapping[str, str] | None = None) -> Path:
    return state_directory(kb, environ=environ) / USAGE_FILE


def record_usage(
    kb: Path,
    *,
    command: str,
    query: str,
    project: str | None,
    jev_requested: bool,
    jev_used: bool,
    jev_tokens: int,
    cards: Iterable[str],
    budget: int | None = None,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> None:
    env = os.environ if environ is None else environ
    if env.get(DISABLE_ENV, "1") == "0":
        return
    entry: dict[str, Any] = {
        "ts": (now or datetime.now(timezone.utc)).isoformat(),
        "command": command,
        "session_id": env.get("EOS_AGENT_SESSION_ID") or None,
        "profile": env.get("EOS_AGENT_PROFILE") or None,
        "cwd": str(Path.cwd()),
        "project": project,
        "query": query,
        "budget": budget,
        "jev_requested": jev_requested,
        "jev_used": jev_used,
        "jev_tokens": jev_tokens,
        "cards": list(cards),
    }
    line = (json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    try:
        path = usage_path(kb, environ=env)
        path.parent.mkdir(parents=True, exist_ok=True)
        # One O_APPEND write per entry keeps concurrent agent writes line-atomic.
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except OSError:
        pass


def read_usage(kb: Path, *, environ: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    try:
        text = usage_path(kb, environ=environ).read_text(encoding="utf-8")
    except OSError:
        return []
    entries: list[dict[str, Any]] = []
    for raw in text.splitlines():
        try:
            entry = json.loads(raw)
            datetime.fromisoformat(entry["ts"])
        except (ValueError, TypeError, KeyError):
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def summarize_usage(
    entries: Iterable[dict[str, Any]],
    *,
    since: datetime | None = None,
) -> dict[str, Any]:
    """Count calls and escalations.

    An escalation is a --jev call that follows a plain call of the same command
    in the same agent session within ESCALATION_WINDOW.
    """
    selected = sorted(
        (e for e in entries if since is None or datetime.fromisoformat(e["ts"]) >= since),
        key=lambda e: e["ts"],
    )
    last_plain: dict[tuple[str, str], dict[str, Any]] = {}
    escalations: list[dict[str, Any]] = []
    for entry in selected:
        session = entry.get("session_id")
        if not session:
            continue
        key = (session, entry.get("command", ""))
        if not entry.get("jev_requested"):
            last_plain[key] = entry
            continue
        plain = last_plain.pop(key, None)
        if plain is None:
            continue
        gap = datetime.fromisoformat(entry["ts"]) - datetime.fromisoformat(plain["ts"])
        if timedelta(0) <= gap <= ESCALATION_WINDOW:
            escalations.append({
                "ts": entry["ts"],
                "session_id": session,
                "command": entry.get("command"),
                "plain_query": plain.get("query"),
                "plain_cards": plain.get("cards", []),
                "jev_query": entry.get("query"),
                "jev_cards": entry.get("cards", []),
                "jev_tokens": entry.get("jev_tokens", 0),
            })
    jev_calls = [e for e in selected if e.get("jev_requested")]
    return {
        "calls": len(selected),
        "plain_calls": len(selected) - len(jev_calls),
        "jev_calls": len(jev_calls),
        "jev_fallbacks": sum(1 for e in jev_calls if not e.get("jev_used")),
        "jev_tokens": sum(int(e.get("jev_tokens") or 0) for e in jev_calls),
        "sessions": len({e["session_id"] for e in selected if e.get("session_id")}),
        "escalations": len(escalations),
        "recent_escalations": escalations[-_RECENT_ESCALATIONS:],
    }
