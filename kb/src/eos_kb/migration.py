from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import yaml

from .paths import kb_config_path
from .sessions import SessionError, load_session
from .storage import atomic_write, state_directory, writer_lock


class MigrationError(ValueError):
    def __init__(self, code: str, field_path: str, message: str) -> None:
        self.code = code
        self.field_path = field_path
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class Verification:
    manifest_hash: str
    counts: dict[str, int]


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def manifest_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _content_hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _path_type(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if path.is_file():
        return "file"
    raise MigrationError("migration.path_unsupported", "$.entries", f"unsupported source path: {path}")


def _snapshot(path: Path, path_type: str | None = None) -> tuple[str, str | None]:
    actual_type = _path_type(path)
    if path_type is not None and actual_type != path_type:
        raise MigrationError("migration.path_type_changed", "$.entries", "path type changed")
    resolved_type = path_type or actual_type
    if resolved_type == "symlink":
        target = os.readlink(path)
        return _content_hash(f"symlink:{target}".encode("utf-8")), target
    if resolved_type == "file":
        return _content_hash(path.read_bytes()), None
    raise MigrationError("migration.path_unsupported", "$.entries", f"unsupported path type: {resolved_type}")


def _safe_relative(value: str) -> Path:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise MigrationError("migration.path_invalid", "$.entries", f"unsafe path: {value}")
    return Path(*path.parts)


def _title(data: bytes, relative: str) -> str:
    text = data.decode("utf-8", errors="replace")
    for line in text.splitlines():
        if line.startswith("# ") and line[2:].strip():
            return line[2:].strip().replace("\u2014", "-")
    return Path(relative).stem.replace("-", " ").replace("_", " ").title()


def _type(relative: str) -> str:
    path = PurePosixPath(relative)
    name = path.name.lower()
    if name in {"00-index.md", "index.md", "_pending-kb-updates.md"}:
        return "Index"
    if "incident" in path.parts or "failure" in name:
        return "Incident"
    if "patterns" in path.parts:
        return "Pattern"
    if "decision" in name:
        return "Decision"
    return "Note"


def _legacy_frontmatter(data: bytes) -> tuple[dict[str, Any], int] | None:
    lines = data.splitlines(keepends=True)
    if not lines or lines[0].rstrip(b"\r\n") != b"---":
        return None
    offset = len(lines[0])
    for line in lines[1:]:
        if line.rstrip(b"\r\n") in {b"---", b"..."}:
            try:
                value = yaml.safe_load(data[len(lines[0]):offset].decode("utf-8"))
            except (UnicodeDecodeError, yaml.YAMLError):
                return None
            return (value, offset) if isinstance(value, dict) else None
        offset += len(line)
    return None


def inventory(root: Path) -> tuple[dict[str, Any], ...]:
    canonical = root.expanduser().resolve()
    entries: list[dict[str, Any]] = []
    for path in sorted(canonical.rglob("*")):
        if ".eos" in path.relative_to(canonical).parts:
            continue
        if not path.is_file() and not path.is_symlink():
            continue
        relative = path.relative_to(canonical).as_posix()
        path_type = _path_type(path)
        source_hash, link_target = _snapshot(path, path_type)
        data = path.read_bytes() if path_type == "file" else b""
        inferred = _type(relative)
        existing = _legacy_frontmatter(data) if path_type == "file" and path.suffix.lower() == ".md" else None
        if path_type == "symlink" or path.suffix.lower() != ".md":
            action = "preserve"
            planned_metadata: dict[str, str] = {}
        elif existing is None:
            action = "add-frontmatter"
            planned_metadata = {"type": inferred, "title": _title(data, relative)}
        else:
            metadata, _ = existing
            planned_metadata = {}
            if not isinstance(metadata.get("type"), str) or not metadata["type"].strip():
                planned_metadata["type"] = inferred
            if not isinstance(metadata.get("title"), str) or not metadata["title"].strip():
                planned_metadata["title"] = _title(data, relative)
            action = "enrich-frontmatter" if planned_metadata else "preserve"
        entries.append(
            {
                "source_path": relative,
                "source_hash": source_hash,
                "source_type": path_type,
                "link_target": link_target,
                "target_path": relative,
                "inferred_type": inferred,
                "planned_metadata": planned_metadata,
                "permissions": stat.S_IMODE(path.lstat().st_mode),
                "action": action,
            }
        )
    return tuple(entries)


def _session_for_kb(root: Path, session_id: str) -> dict[str, Any]:
    try:
        session = load_session(root, session_id)
    except SessionError as exc:
        raise MigrationError("migration.session_invalid", "$.approval_session", str(exc)) from exc
    if session.get("state") != "active":
        raise MigrationError("migration.session_invalid", "$.approval_session", "approval session is not active")
    return session


def _approval_log(root: Path) -> Path:
    return state_directory(root) / "migration-approvals.jsonl"


def _validate_manifest_hash(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise MigrationError("migration.hash_invalid", "$.manifest_hash", "manifest hash must be a SHA-256 hex digest")


def record_migration_approval(
    root: Path,
    *,
    manifest_hash: str,
    approved_by: str,
    session_id: str,
) -> dict[str, Any]:
    canonical = root.expanduser().resolve()
    _validate_manifest_hash(manifest_hash)
    if not approved_by.strip():
        raise MigrationError("migration.approval_required", "$.approved_by", "approver is required")
    _session_for_kb(canonical, session_id)
    record = {
        "schema_version": 1,
        "event": "migration_approval",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kb_root": str(canonical),
        "manifest_hash": manifest_hash,
        "approved_by": approved_by,
        "approval_session": session_id,
    }
    log = _approval_log(canonical)
    with writer_lock(state_directory(canonical)):
        existing = log.read_bytes() if log.exists() else b""
        atomic_write(log, existing + (json.dumps(record, sort_keys=True) + "\n").encode("utf-8"))
    return record


def _matching_approval(root: Path, *, manifest_hash: str, approved_by: str, session_id: str) -> dict[str, Any]:
    _session_for_kb(root, session_id)
    log = _approval_log(root)
    if not log.exists():
        raise MigrationError("migration.approval_missing", "$.approval", "no migration approval record exists")
    try:
        records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError("migration.approval_invalid", "$.approval", "migration approval log is unreadable") from exc
    for record in reversed(records):
        if (
            isinstance(record, dict)
            and record.get("event") == "migration_approval"
            and record.get("kb_root") == str(root)
            and record.get("manifest_hash") == manifest_hash
            and record.get("approved_by") == approved_by
            and record.get("approval_session") == session_id
        ):
            return record
    raise MigrationError("migration.approval_missing", "$.approval", "no exact approval exists for this manifest and session")


def _scope_config(path: Path | None = None) -> dict[str, Any]:
    source = path or kb_config_path("migration-scopes.yaml")
    value = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise MigrationError("migration.scope_invalid", "$.scope", "invalid scope configuration")
    return value


def _matches(path: str, patterns: Iterable[str]) -> bool:
    candidate = PurePosixPath(path)
    return any(pattern == "**" or candidate.match(pattern) for pattern in patterns)


def _selected_paths(
    entries: tuple[dict[str, Any], ...],
    *,
    scope: str,
    mode: str,
    scopes: dict[str, Any],
) -> set[str]:
    definitions = scopes.get(mode)
    if not isinstance(definitions, dict) or scope not in definitions:
        raise MigrationError("migration.scope_unknown", "$.scope", f"unknown {mode} scope: {scope}")
    definition = definitions[scope]
    if not isinstance(definition, dict):
        raise MigrationError("migration.scope_invalid", "$.scope", "scope must be a mapping")
    all_paths = {entry["source_path"] for entry in entries}
    if "remainder_after" in definition:
        prior: set[str] = set()
        for name in definition["remainder_after"]:
            prior.update(_selected_paths(entries, scope=name, mode=mode, scopes=scopes))
        return all_paths - prior
    include = definition.get("include", [])
    exclude = definition.get("exclude", [])
    selected = {path for path in all_paths if _matches(path, include) and not _matches(path, exclude)}
    return selected


def plan(
    root: Path,
    *,
    scope: str | None = None,
    mode: str | None = None,
    scopes_path: Path | None = None,
) -> dict[str, Any]:
    canonical = root.expanduser().resolve()
    entries = inventory(canonical)
    selected_mode = mode or ("work" if "/work/" in canonical.as_posix() else "personal")
    selected_scope = scope or ("all" if selected_mode == "personal" else "high-value-nova")
    scopes = _scope_config(scopes_path)
    selected = _selected_paths(entries, scope=selected_scope, mode=selected_mode, scopes=scopes)
    scope_definition = scopes[selected_mode][selected_scope]
    return {
        "schema_version": 1,
        "kb_root": str(canonical),
        "scope": selected_scope,
        "scope_hash": hashlib.sha256(_json_bytes(scope_definition)).hexdigest(),
        "baseline_hash": hashlib.sha256(_json_bytes(entries)).hexdigest(),
        "entries": [entry for entry in entries if entry["source_path"] in selected],
    }


def verify_plan(value: dict[str, Any], *, scopes_path: Path | None = None) -> Verification:
    root = Path(str(value.get("kb_root", "")))
    mode = "work" if "/work/" in root.as_posix() else "personal"
    current = plan(root, scope=str(value.get("scope", "")), mode=mode, scopes_path=scopes_path)
    if current != value:
        raise MigrationError("migration.plan_changed", "$", "manifest inputs changed; create a new plan")
    counts: dict[str, int] = {}
    for entry in value["entries"]:
        counts[entry["action"]] = counts.get(entry["action"], 0) + 1
    return Verification(manifest_hash(value), counts)


def _render(entry: dict[str, Any], data: bytes) -> bytes:
    if entry["action"] == "preserve":
        return data
    metadata = entry["planned_metadata"]
    header = yaml.safe_dump(metadata, sort_keys=False).encode("utf-8")
    if entry["action"] == "enrich-frontmatter":
        existing = _legacy_frontmatter(data)
        if existing is None:
            raise MigrationError("migration.frontmatter_changed", "$.entries", "legacy frontmatter is no longer valid")
        _, close_offset = existing
        return data[:close_offset] + header + data[close_offset:]
    return b"---\n" + header + b"---\n" + data


def apply(
    root: Path,
    value: dict[str, Any],
    *,
    expected_hash: str,
    approved_by: str,
    approval_session: str,
    receipt_out: Path,
    simulate_failure_after: int | None = None,
) -> dict[str, Any]:
    verification = verify_plan(value)
    if verification.manifest_hash != expected_hash:
        raise MigrationError("migration.hash_mismatch", "$.manifest_hash", "manifest hash changed")
    canonical = root.expanduser().resolve()
    if canonical != Path(value["kb_root"]).resolve():
        raise MigrationError("migration.root_mismatch", "$.kb_root", "manifest belongs to another KB")
    _matching_approval(canonical, manifest_hash=expected_hash, approved_by=approved_by, session_id=approval_session)
    transaction_id = uuid.uuid4().hex
    backup_root = state_directory(canonical) / "migration-backups" / transaction_id
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "state": "in_progress",
        "kb_root": str(canonical),
        "manifest_hash": expected_hash,
        "approved_by": approved_by,
        "approval_session": approval_session,
        "backup_root": str(backup_root),
        "entries": [],
    }
    for entry in value["entries"]:
        relative = _safe_relative(entry["target_path"])
        target = canonical / relative
        source_type = entry.get("source_type", "file")
        if not os.path.lexists(target):
            raise MigrationError("migration.source_changed", f"$.entries.{entry['source_path']}", "source changed")
        try:
            current_hash, current_link_target = _snapshot(target, source_type)
        except MigrationError as exc:
            raise MigrationError("migration.source_changed", f"$.entries.{entry['source_path']}", "source type changed") from exc
        if current_hash != entry["source_hash"] or current_link_target != entry.get("link_target"):
            raise MigrationError("migration.source_changed", f"$.entries.{entry['source_path']}", "source changed")
        backup = backup_root / relative
        receipt["entries"].append(
            {
                "path": relative.as_posix(),
                "original_hash": entry["source_hash"],
                "backup_hash": entry["source_hash"],
                "source_type": source_type,
                "link_target": entry.get("link_target"),
                "permissions": entry["permissions"],
            }
        )
    atomic_write(receipt_out, _json_bytes(receipt))
    with writer_lock(state_directory(canonical)):
        backup_root.mkdir(parents=True, exist_ok=False)
        try:
            for index, entry in enumerate(value["entries"]):
                if simulate_failure_after is not None and index >= simulate_failure_after:
                    raise MigrationError("migration.interrupted", "$.apply", "simulated interruption")
                relative = _safe_relative(entry["target_path"])
                target = canonical / relative
                backup = backup_root / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                source_type = entry.get("source_type", "file")
                if source_type == "symlink":
                    backup.symlink_to(os.readlink(target))
                else:
                    shutil.copy2(target, backup)
                    if entry["action"] != "preserve":
                        atomic_write(target, _render(entry, target.read_bytes()))
                    os.chmod(target, entry["permissions"])
        except Exception:
            rollback(canonical, value, expected_hash=expected_hash, receipt=receipt_out)
            raise
        receipt["state"] = "applied"
        atomic_write(receipt_out, _json_bytes(receipt))
    return receipt


def rollback(
    root: Path,
    value: dict[str, Any],
    *,
    expected_hash: str,
    receipt: Path,
) -> dict[str, Any]:
    canonical = root.expanduser().resolve()
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    if payload.get("state") not in {"in_progress", "applied"}:
        raise MigrationError("migration.receipt_state", "$.receipt.state", "receipt is not recoverable")
    if payload.get("manifest_hash") != expected_hash or manifest_hash(value) != expected_hash:
        raise MigrationError("migration.hash_mismatch", "$.manifest_hash", "manifest or receipt hash changed")
    backup_root = Path(payload["backup_root"])
    owned = {entry["target_path"] for entry in value["entries"]}
    for entry in payload["entries"]:
        if entry["path"] not in owned:
            raise MigrationError("migration.receipt_path", "$.receipt.entries", "receipt contains an unowned path")
        backup = backup_root / _safe_relative(entry["path"])
        target = canonical / _safe_relative(entry["path"])
        source_type = entry.get("source_type", "file")
        if not os.path.lexists(backup):
            if os.path.lexists(target):
                current_hash, current_link_target = _snapshot(target, source_type)
                if current_hash == entry["original_hash"] and current_link_target == entry.get("link_target"):
                    continue
            if target.is_file() and _content_hash(target.read_bytes()) == entry["original_hash"]:
                continue
            raise MigrationError(
                "migration.backup_missing",
                "$.receipt.entries",
                "backup is missing for a changed target",
            )
        backup_hash, backup_link_target = _snapshot(backup, source_type)
        if backup_hash != entry["backup_hash"] or backup_link_target != entry.get("link_target"):
            raise MigrationError("migration.backup_changed", "$.receipt.entries", "backup hash changed")
        if os.path.lexists(target):
            target.unlink()
        if source_type == "symlink":
            target.symlink_to(os.readlink(backup))
        else:
            atomic_write(target, backup.read_bytes())
            os.chmod(target, entry["permissions"])
    payload["state"] = "rolled_back"
    atomic_write(receipt, _json_bytes(payload))
    return payload
