"""Durable freshness-gate boundary and review-event ledger.

Both live in the KB's own ``.eos/`` directory so they travel with the KB and
survive index rebuilds. The stored index is mutable and rebuilt on every
promote, so a path-vs-index comparison cannot tell new docs from existing
ones; the gate record (written once at activation, never updated) is the
single authoritative new/existing boundary, enforced in both ``kb validate``
and the promote path.

A gate file that is missing, unreadable, or the wrong version fails closed:
callers refuse and report instead of silently re-activating, because a fresh
snapshot would bless every new doc as existing and move the boundary.

Last review is a review *event* bound to the promoted content hash, never a
bare frontmatter edit:

- ``kb promote`` appends a review event carrying the exact promoted content
  hash and timestamp. Direct-change approvals deliberately do not: a
  self-supplied ``--actor`` must not reset expiry.
- An event counts only when it is well-formed, not future-dated, and linked
  to an accepted approval for the same proposal id and content hash, so a
  forged ``reviews.jsonl`` line cannot move expiry.
- Expiry is based on the latest event for the target. A content hash mismatch
  with the latest event means the doc was edited since review, which reports
  stale (re-review to clear), never unknown.
- Docs already tracked at activation get an initial review from the gate
  record itself: while their content still matches the activation snapshot,
  the activation timestamp counts as their first review.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .normalize import normalized_content_hash
from .storage import atomic_write, writer_lock


GATE_SCHEMA_VERSION = 1
GATE_FILENAME = "freshness-gate.json"
REVIEWS_FILENAME = "reviews.jsonl"
REVIEW_EVENT_VERSION = 1


class GateError(ValueError):
    """A missing, corrupt, or version-skewed gate boundary or review ledger."""

    def __init__(self, code: str, field_path: str, message: str) -> None:
        self.code = code
        self.field_path = field_path
        super().__init__(message)


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _eos(root: Path) -> Path:
    path = root / ".eos"
    path.mkdir(parents=True, exist_ok=True)
    return path


def gate_path(root: Path) -> Path:
    return root / ".eos" / GATE_FILENAME


def reviews_path(root: Path) -> Path:
    return root / ".eos" / REVIEWS_FILENAME


def _valid_gate(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("schema_version") == GATE_SCHEMA_VERSION
        and isinstance(value.get("activated_at"), str)
        and _parse_time(value["activated_at"]) is not None
        and isinstance(value.get("docs"), dict)
        and all(isinstance(path, str) and isinstance(item, str) for path, item in value["docs"].items())
    )


def _gate_failure(root: Path) -> GateError:
    """Fail closed: never silently re-activate a bad boundary.

    A corrupt or version-skewed record cannot be trusted to tell new docs
    from existing ones, and a fresh snapshot would bless everything on disk
    as existing. Refuse and report; the operator re-activates explicitly by
    removing the bad file and running kb index.
    """
    path = gate_path(root)
    if not path.is_file():
        return GateError(
            "gate.missing",
            "$.freshness-gate",
            "Freshness gate is not activated; run kb index to activate it.",
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = None
    if isinstance(value, dict) and value.get("schema_version") != GATE_SCHEMA_VERSION:
        return GateError(
            "gate.version_mismatch",
            "$.freshness-gate",
            "Freshness gate schema is not version 1; remove .eos/freshness-gate.json and run kb index to re-activate.",
        )
    return GateError(
        "gate.corrupt",
        "$.freshness-gate",
        "Freshness gate record is unreadable or malformed; remove .eos/freshness-gate.json and run kb index to re-activate.",
    )


def load_gate(root: Path) -> dict[str, Any] | None:
    """Return the activation record, or None when there is no usable boundary."""
    try:
        value = json.loads(gate_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if _valid_gate(value) else None


def require_gate(root: Path) -> dict[str, Any]:
    """Return the activation record, or fail closed when it is unusable."""
    gate = load_gate(root)
    if gate is not None:
        return gate
    raise _gate_failure(root)


def _snapshot_docs(root: Path) -> dict[str, str]:
    docs: dict[str, str] = {}
    for path in sorted(root.rglob("*.md")):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part in (".eos", ".git") for part in relative.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        docs[relative.as_posix()] = normalized_content_hash(text)
    return docs


def ensure_gate_activation(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Create the activation record on first use; never update it afterwards.

    Everything on disk at activation counts as existing, even if it is
    untagged. Anything appearing later is new. The record is written once so
    the boundary cannot drift when the index is rebuilt.
    """
    existing = load_gate(root)
    if existing is not None:
        return existing
    supplied = now or datetime.now(timezone.utc)
    if supplied.tzinfo is None:
        supplied = supplied.replace(tzinfo=timezone.utc)
    record = {
        "schema_version": GATE_SCHEMA_VERSION,
        "activated_at": supplied.astimezone(timezone.utc).isoformat(),
        "docs": _snapshot_docs(root),
    }
    eos = _eos(root)
    with writer_lock(eos):
        if load_gate(root) is not None:
            return load_gate(root)  # type: ignore[return-value]
        atomic_write(
            gate_path(root),
            (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
    return record


def is_new_doc(gate: dict[str, Any] | None, relative_file: str) -> bool:
    """A doc is new when its path is absent from the activation snapshot."""
    if gate is None:
        return False
    return relative_file not in gate.get("docs", {})


def activation_review_at(
    gate: dict[str, Any] | None, relative_file: str, content_hash: str | None
) -> datetime | None:
    """Initial review for docs already tracked at activation.

    While a tracked doc's content still matches the activation snapshot, the
    activation timestamp is its first review. Any later edit without a review
    event leaves it with no computable expiry (unknown, advisory).
    """
    if gate is None or not content_hash:
        return None
    if gate.get("docs", {}).get(relative_file) != content_hash:
        return None
    activated = gate.get("activated_at")
    return _parse_time(activated) if isinstance(activated, str) else None


def record_review_event(
    root: Path,
    *,
    target: str,
    content_hash: str,
    proposal_id: str,
    session_id: str,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    """Append a review event bound to the exact promoted content hash."""
    event = _review_event(
        target=target,
        content_hash=content_hash,
        proposal_id=proposal_id,
        session_id=session_id,
        reviewed_at=reviewed_at,
    )
    line = (json.dumps(event, sort_keys=True) + "\n").encode("utf-8")
    eos = _eos(root)
    with writer_lock(eos):
        path = reviews_path(root)
        try:
            existing = path.read_bytes() if path.is_file() else b""
        except OSError:
            existing = b""
        atomic_write(path, existing + line)
    return event


def _review_event(
    *,
    target: str,
    content_hash: str,
    proposal_id: str,
    session_id: str,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": REVIEW_EVENT_VERSION,
        "target": target,
        "content_hash": content_hash,
        "reviewed_at": reviewed_at or datetime.now(timezone.utc).isoformat(),
        "proposal_id": proposal_id,
        "session_id": session_id,
    }


def format_review_event(
    *,
    target: str,
    content_hash: str,
    proposal_id: str,
    session_id: str,
    reviewed_at: str | None = None,
) -> bytes:
    """One review-event log line, for atomic appends inside a transaction."""
    return (json.dumps(_review_event(
        target=target,
        content_hash=content_hash,
        proposal_id=proposal_id,
        session_id=session_id,
        reviewed_at=reviewed_at,
    ), sort_keys=True) + "\n").encode("utf-8")


def _accepted_review_hashes(root: Path) -> set[tuple[str, str]]:
    """(proposal_id, content hash) pairs with an accepted approval.

    A review event counts only when it links to one of these, so a forged
    reviews.jsonl line cannot move expiry on its own.
    """
    try:
        lines = (root / ".eos" / "approvals.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    linked: set[tuple[str, str]] = set()
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            not isinstance(record, dict)
            or record.get("decision") != "accepted"
            or not isinstance(record.get("proposal_id"), str)
            or not isinstance(record.get("proposed_result_hash"), str)
        ):
            continue
        linked.add((record["proposal_id"], record["proposed_result_hash"]))
    return linked


def _valid_review_event(
    record: Any, *, target: str, now: datetime, linked: set[tuple[str, str]]
) -> tuple[datetime, str] | None:
    if not isinstance(record, dict):
        return None
    if record.get("schema_version") != REVIEW_EVENT_VERSION:
        return None
    if record.get("target") != target:
        return None
    content_hash = record.get("content_hash")
    proposal_id = record.get("proposal_id")
    if (
        not isinstance(content_hash, str)
        or not content_hash.startswith("sha256:")
        or len(content_hash) != len("sha256:") + 64
        or not isinstance(proposal_id, str)
        or not proposal_id
    ):
        return None
    reviewed_at = record.get("reviewed_at")
    parsed = _parse_time(reviewed_at) if isinstance(reviewed_at, str) else None
    if parsed is None or parsed > now:
        # Unparseable or future-dated lines are rejected, never trusted.
        return None
    if (proposal_id, content_hash) not in linked:
        # No accepted approval for this proposal id and content hash.
        return None
    return parsed, content_hash


def latest_review_event(
    root: Path, target: str, *, now: datetime | None = None
) -> tuple[datetime, str] | None:
    """Latest linkage-valid review event for the target, with its hash.

    Returns None when the target was never reviewed through the proposal
    flow. Callers treat a hash mismatch with this event as stale (edited
    since review), never unknown.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    try:
        lines = reviews_path(root).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    linked = _accepted_review_hashes(root)
    latest: tuple[datetime, str] | None = None
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        event = _valid_review_event(record, target=target, now=current, linked=linked)
        if event is None:
            continue
        if latest is None or event[0] > latest[0]:
            latest = event
    return latest
