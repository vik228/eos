from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Mapping


class StorageError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


SCHEMA_VERSION = 4
_JOURNAL_SCHEMA_VERSION = 1
_JOURNAL_PHASES = {
    "intent",
    "prepared",
    "promoting",
    "rollback_failed",
    "rolled_back",
    "committed",
}
_TRANSACTION_ID_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
)


def state_directory(
    root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    env = dict(os.environ if environ is None else environ)
    home_path = Path(home or env.get("HOME", str(Path.home()))).expanduser()
    configured = env.get("EOS_KB_STATE_ROOT")
    if configured:
        if configured == "~" or configured.startswith("~/"):
            configured = str(home_path) + configured[1:]
        configured = configured.replace("$HOME", str(home_path))
        state_root = Path(configured).expanduser()
    else:
        state_root = home_path / ".local" / "state" / "eos" / "kb"
    canonical_root = root.expanduser().resolve()
    bundle_id = hashlib.sha256(os.fsencode(canonical_root)).hexdigest()
    return state_root.resolve() / bundle_id


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def stage_bytes(destination: Path, data: bytes, *, transaction_id: str) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=f".{destination.name}.{transaction_id}.",
        suffix=".stage.tmp",
        dir=destination.parent,
    )
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return staged
    except Exception:
        staged.unlink(missing_ok=True)
        raise


def atomic_write(destination: Path, data: bytes) -> None:
    temporary = stage_bytes(destination, data, transaction_id="atomic")
    try:
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def writer_lock(state: Path) -> Iterator[None]:
    state.mkdir(parents=True, exist_ok=True)
    path = state / "writer.lock"
    with path.open("a+") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def create_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        connection.executescript(
            """
            CREATE TABLE concepts (
                relative_file TEXT PRIMARY KEY,
                resource TEXT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                type TEXT NOT NULL,
                status TEXT NOT NULL,
                generated INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                metadata_hash TEXT NOT NULL,
                project TEXT,
                tags TEXT NOT NULL,
                components TEXT NOT NULL,
                symptoms TEXT NOT NULL,
                trust TEXT NOT NULL,
                freshness TEXT NOT NULL,
                verified TEXT NOT NULL,
                body TEXT NOT NULL,
                source_revision TEXT,
                stale_after TEXT
            );
            CREATE TABLE headings (
                relative_file TEXT NOT NULL REFERENCES concepts(relative_file) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL,
                level INTEGER NOT NULL,
                title TEXT NOT NULL,
                PRIMARY KEY(relative_file, ordinal)
            );
            CREATE VIRTUAL TABLE concepts_fts USING fts5(relative_file UNINDEXED, text);
            CREATE TABLE links (source TEXT NOT NULL REFERENCES concepts(relative_file) ON DELETE CASCADE, target TEXT NOT NULL);
            CREATE TABLE reverse_links (source TEXT NOT NULL, target TEXT NOT NULL);
            CREATE TABLE claims (relative_file TEXT NOT NULL REFERENCES concepts(relative_file) ON DELETE CASCADE, claim_id TEXT NOT NULL, normalized_value TEXT NOT NULL);
            CREATE TABLE sources (
                relative_file TEXT NOT NULL REFERENCES concepts(relative_file) ON DELETE CASCADE,
                source_kind TEXT NOT NULL CHECK(source_kind IN ('source', 'source_path')),
                source_value TEXT NOT NULL
            );
            CREATE TABLE supersession (source TEXT NOT NULL, target TEXT NOT NULL);
            """
        )
        connection.commit()
        return connection
    except sqlite3.OperationalError as exc:
        connection.close()
        if "fts5" in str(exc).lower() or "virtual table" in str(exc).lower():
            raise StorageError(
                "storage.fts5_unavailable",
                "SQLite was built without FTS5 support.",
            ) from exc
        raise


def _content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _trusted_destinations(allowed_destinations: Iterable[Path]) -> frozenset[Path]:
    destinations = frozenset(
        Path(destination).resolve(strict=False)
        for destination in allowed_destinations
    )
    if not destinations:
        raise StorageError(
            "storage.recovery_destinations_required",
            "Recovery requires at least one trusted destination.",
        )
    return destinations


def _artifact_paths(destination: Path, transaction_id: str) -> tuple[Path, Path]:
    return (
        destination.parent / f".{destination.name}.{transaction_id}.stage.tmp",
        destination.parent / f".{destination.name}.{transaction_id}.backup.tmp",
    )


def _journal_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _write_journal(recovery_path: Path, payload: dict[str, object]) -> None:
    atomic_write(recovery_path, _journal_bytes(payload))


def begin_transaction(
    destinations: Iterable[Path],
    *,
    recovery_path: Path,
    transaction_id: str,
    allowed_destinations: Iterable[Path],
) -> dict[Path, Path]:
    trusted_destinations = _trusted_destinations(allowed_destinations)
    if not transaction_id or any(
        character not in _TRANSACTION_ID_CHARACTERS for character in transaction_id
    ):
        raise StorageError(
            "storage.transaction_id_invalid",
            "Transaction identifiers may contain only letters, digits, dot, underscore, and hyphen.",
        )
    replacements: dict[Path, Path] = {}
    entries: list[dict[str, object]] = []
    for supplied_destination in destinations:
        destination = Path(supplied_destination).resolve(strict=False)
        if destination in replacements:
            raise StorageError(
                "storage.recovery_journal_invalid",
                "Transaction destinations must be unique.",
            )
        if destination not in trusted_destinations:
            raise StorageError(
                "storage.recovery_destination_not_allowed",
                "Transaction destination is not in the trusted allowlist.",
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        staged, backup = _artifact_paths(destination, transaction_id)
        existed = destination.is_file()
        replacements[destination] = staged
        entries.append(
            {
                "destination": str(destination),
                "staged": str(staged),
                "backup": str(backup),
                "existed": existed,
                "original_hash": _content_hash(destination) if existed else None,
            }
        )

    payload: dict[str, object] = {
        "schema_version": _JOURNAL_SCHEMA_VERSION,
        "transaction_id": transaction_id,
        "phase": "intent",
        "entries": entries,
    }
    try:
        _write_journal(recovery_path, payload)
    except BaseException:
        for entry in entries:
            _remove_artifact(Path(str(entry["staged"])))
            Path(str(entry["backup"])).unlink(missing_ok=True)
        recovery_path.unlink(missing_ok=True)
        raise
    return replacements


def write_staged(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_directory(path.parent)
    except BaseException:
        _remove_artifact(path)
        raise


def transactional_replace(
    replacements: Mapping[Path, Path],
    *,
    recovery_path: Path,
    transaction_id: str,
    allowed_destinations: Iterable[Path],
    simulate_failure_after: int | None = None,
) -> None:
    trusted_destinations = _trusted_destinations(allowed_destinations)
    payload = _load_journal(recovery_path, trusted_destinations)
    if payload["transaction_id"] != transaction_id or payload["phase"] != "intent":
        raise StorageError(
            "storage.recovery_journal_invalid",
            "Recovery journal does not describe an unprepared transaction intent.",
        )
    entries = payload["entries"]
    assert isinstance(entries, list)
    declared = {
        Path(str(entry["destination"])): Path(str(entry["staged"]))
        for entry in entries
    }
    normalized = {
        Path(destination).resolve(strict=False): Path(staged).resolve(strict=False)
        for destination, staged in replacements.items()
    }
    if normalized != declared:
        raise StorageError(
            "storage.recovery_journal_invalid",
            "Replacement mapping does not match the durable transaction intent.",
        )

    try:
        for entry in entries:
            staged = Path(str(entry["staged"]))
            if not staged.is_file():
                raise StorageError(
                    "storage.stage_missing",
                    "A predeclared staged artifact is missing.",
                )
            if entry["existed"]:
                destination = Path(str(entry["destination"]))
                backup = Path(str(entry["backup"]))
                shutil.copy2(destination, backup)
                with backup.open("rb") as stream:
                    os.fsync(stream.fileno())
                _fsync_directory(backup.parent)
        payload["phase"] = "prepared"
        _write_journal(recovery_path, payload)
    except Exception:
        _cleanup_transaction_artifacts(entries)
        recovery_path.unlink(missing_ok=True)
        _fsync_directory(recovery_path.parent)
        raise

    payload["phase"] = "promoting"
    try:
        _write_journal(recovery_path, payload)
    except Exception:
        _cleanup_transaction_artifacts(entries)
        recovery_path.unlink(missing_ok=True)
        _fsync_directory(recovery_path.parent)
        raise

    try:
        for index, entry in enumerate(entries):
            if simulate_failure_after is not None and index >= simulate_failure_after:
                raise StorageError(
                    "storage.promotion_failed",
                    "Simulated promotion failure.",
                )
            destination = Path(str(entry["destination"]))
            staged = Path(str(entry["staged"]))
            os.replace(staged, destination)
            _fsync_directory(destination.parent)
    except Exception as promotion_error:
        try:
            _restore_transaction_entries(entries)
            payload["phase"] = "rolled_back"
            _write_journal(recovery_path, payload)
        except Exception as rollback_error:
            payload["phase"] = "rollback_failed"
            try:
                _write_journal(recovery_path, payload)
            except Exception:
                pass
            raise StorageError(
                "storage.rollback_failed",
                "Promotion failed and the prior state could not be completely restored.",
            ) from rollback_error
        _cleanup_transaction_artifacts(entries)
        recovery_path.unlink(missing_ok=True)
        _fsync_directory(recovery_path.parent)
        raise promotion_error

    payload["phase"] = "committed"
    _write_journal(recovery_path, payload)
    _cleanup_transaction_artifacts(entries)
    recovery_path.unlink(missing_ok=True)
    _fsync_directory(recovery_path.parent)


def _restore_transaction_entries(entries: list[dict[str, object]]) -> None:
    for entry in entries:
        destination = Path(str(entry["destination"]))
        backup = Path(str(entry["backup"]))
        if entry["existed"] and backup.exists():
            os.replace(backup, destination)
            _fsync_directory(destination.parent)
        elif entry["existed"]:
            original_hash = entry["original_hash"]
            if not destination.is_file() or _content_hash(destination) != original_hash:
                raise StorageError(
                    "storage.recovery_backup_missing",
                    "A required transaction backup is missing.",
                )
            _fsync_directory(destination.parent)
        else:
            existed = destination.exists()
            destination.unlink(missing_ok=True)
            if existed:
                _fsync_directory(destination.parent)


def _cleanup_transaction_artifacts(
    entries: list[dict[str, object]],
) -> None:
    for entry in entries:
        _remove_artifact(Path(str(entry["staged"])))
        Path(str(entry["backup"])).unlink(missing_ok=True)


def _remove_artifact(path: Path) -> None:
    path.unlink(missing_ok=True)
    Path(f"{path}-wal").unlink(missing_ok=True)
    Path(f"{path}-shm").unlink(missing_ok=True)


def _load_journal(
    recovery_path: Path,
    allowed_destinations: frozenset[Path],
) -> dict[str, object]:
    try:
        payload = json.loads(recovery_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StorageError(
            "storage.recovery_journal_invalid",
            "Recovery journal is unreadable or malformed.",
        ) from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "transaction_id",
        "phase",
        "entries",
    }:
        raise StorageError(
            "storage.recovery_journal_invalid",
            "Recovery journal has invalid top-level fields.",
        )
    transaction_id = payload["transaction_id"]
    phase = payload["phase"]
    entries = payload["entries"]
    if (
        payload["schema_version"] != _JOURNAL_SCHEMA_VERSION
        or not isinstance(transaction_id, str)
        or not transaction_id
        or any(
            character not in _TRANSACTION_ID_CHARACTERS
            for character in transaction_id
        )
        or phase not in _JOURNAL_PHASES
        or not isinstance(entries, list)
        or not entries
    ):
        raise StorageError(
            "storage.recovery_journal_invalid",
            "Recovery journal schema is invalid.",
        )

    destinations: set[Path] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "destination",
            "staged",
            "backup",
            "existed",
            "original_hash",
        }:
            raise StorageError(
                "storage.recovery_journal_invalid",
                "Recovery journal entry schema is invalid.",
            )
        if not all(
            isinstance(entry[field], str)
            for field in ("destination", "staged", "backup")
        ) or not isinstance(entry["existed"], bool):
            raise StorageError(
                "storage.recovery_journal_invalid",
                "Recovery journal entry types are invalid.",
            )
        original_hash = entry["original_hash"]
        if entry["existed"]:
            if (
                not isinstance(original_hash, str)
                or len(original_hash) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in original_hash
                )
            ):
                raise StorageError(
                    "storage.recovery_journal_invalid",
                    "Recovery journal original hash is invalid.",
                )
        elif original_hash is not None:
            raise StorageError(
                "storage.recovery_journal_invalid",
                "New destinations cannot declare an original hash.",
            )
        destination = Path(str(entry["destination"])).resolve(strict=False)
        staged = Path(str(entry["staged"])).resolve(strict=False)
        backup = Path(str(entry["backup"])).resolve(strict=False)
        if destination not in allowed_destinations:
            raise StorageError(
                "storage.recovery_destination_not_allowed",
                "Recovery journal destination is not in the trusted allowlist.",
            )
        expected_staged, expected_backup = _artifact_paths(destination, transaction_id)
        if staged != expected_staged or backup != expected_backup or destination in destinations:
            raise StorageError(
                "storage.recovery_journal_invalid",
                "Recovery journal artifact paths are invalid.",
            )
        destinations.add(destination)
        entry["destination"] = str(destination)
        entry["staged"] = str(staged)
        entry["backup"] = str(backup)
    return payload


def recover_stale_transaction(
    recovery_path: Path,
    *,
    allowed_destinations: Iterable[Path],
) -> None:
    if not recovery_path.exists():
        return
    trusted_destinations = _trusted_destinations(allowed_destinations)
    payload = _load_journal(recovery_path, trusted_destinations)
    entries = payload["entries"]
    assert isinstance(entries, list)
    if payload["phase"] in {"promoting", "rollback_failed"}:
        _restore_transaction_entries(entries)
        payload["phase"] = "rolled_back"
        _write_journal(recovery_path, payload)
    _cleanup_transaction_artifacts(entries)
    recovery_path.unlink(missing_ok=True)
    _fsync_directory(recovery_path.parent)
