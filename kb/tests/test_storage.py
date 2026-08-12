from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from eos_kb.storage import (
    StorageError,
    atomic_write,
    begin_transaction,
    create_database,
    recover_stale_transaction,
    stage_bytes,
    state_directory,
    transactional_replace,
    write_staged,
)


def test_create_database_requires_fts5_and_configures_sqlite(tmp_path: Path) -> None:
    database = tmp_path / "state" / "index.sqlite3"
    connection = create_database(database)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        connection.execute("SELECT * FROM concepts_fts")
    finally:
        connection.close()


def test_atomic_write_uses_destination_directory_and_replaces_bytes(tmp_path: Path) -> None:
    destination = tmp_path / "nested" / "result.json"
    atomic_write(destination, b"new bytes")
    assert destination.read_bytes() == b"new bytes"
    assert list(destination.parent.glob("*.tmp")) == []


def test_state_directory_is_external_deterministic_and_environment_controlled(
    tmp_path: Path,
) -> None:
    root = tmp_path / "knowledge"
    other = tmp_path / "other-knowledge"
    home = tmp_path / "home"

    default = state_directory(root, environ={"HOME": str(home)})
    repeated = state_directory(root / ".." / "knowledge", environ={"HOME": str(home)})
    overridden = state_directory(
        root,
        environ={"HOME": str(home), "EOS_KB_STATE_ROOT": str(tmp_path / "state")},
    )

    assert default.parent == home / ".local" / "state" / "eos" / "kb"
    assert default == repeated
    assert overridden.parent == tmp_path / "state"
    assert overridden != state_directory(other, environ={"HOME": str(home)})
    assert root not in overridden.parents


def test_stage_bytes_uses_destination_directory(tmp_path: Path) -> None:
    destination = tmp_path / "router" / "index.md"
    staged = stage_bytes(destination, b"router bytes", transaction_id="tx-stage")

    assert staged.parent == destination.parent
    assert staged.read_bytes() == b"router bytes"
    staged.unlink()


def test_transactional_replace_records_recovery_and_recovers_stale_transaction(
    tmp_path: Path,
) -> None:
    live = tmp_path / "index.sqlite3"
    recovery = tmp_path / "state" / "transaction.json"
    live.write_bytes(b"old")
    replacements = begin_transaction(
        [live],
        recovery_path=recovery,
        transaction_id="tx-1",
        allowed_destinations=(live,),
    )
    write_staged(replacements[live.resolve()], b"new")

    with pytest.raises(StorageError):
        transactional_replace(
            replacements,
            recovery_path=recovery,
            transaction_id="tx-1",
            allowed_destinations=(live,),
            simulate_failure_after=0,
        )
    assert live.read_bytes() == b"old"
    assert not recovery.exists()


def test_failed_transaction_does_not_promote_partial_files(tmp_path: Path) -> None:
    live_a = tmp_path / "a"
    live_b = tmp_path / "b"
    live_a.write_bytes(b"old-a")
    live_b.write_bytes(b"old-b")
    recovery = tmp_path / "state" / "transaction.json"
    replacements = begin_transaction(
        [live_a, live_b],
        recovery_path=recovery,
        transaction_id="tx-2",
        allowed_destinations=(live_a, live_b),
    )
    staged_a = replacements[live_a.resolve()]
    staged_b = replacements[live_b.resolve()]
    write_staged(staged_a, b"new-a")
    write_staged(staged_b, b"new-b")

    with pytest.raises(StorageError):
        transactional_replace(
            replacements,
            recovery_path=recovery,
            transaction_id="tx-2",
            allowed_destinations=(live_a, live_b),
            simulate_failure_after=1,
        )
    assert live_a.read_bytes() == b"old-a"
    assert live_b.read_bytes() == b"old-b"
    assert not staged_a.exists()
    assert not staged_b.exists()
    assert not list(tmp_path.glob("*.backup.tmp"))


@pytest.mark.parametrize("fail_on_copy", (2, 3))
def test_backup_preparation_failure_cleans_all_transaction_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_on_copy: int,
) -> None:
    destinations = [tmp_path / name for name in ("a", "b", "c")]
    for index, destination in enumerate(destinations):
        destination.write_bytes(f"old-{index}".encode())
    recovery = tmp_path / "state" / "transaction.json"
    replacements = begin_transaction(
        destinations,
        recovery_path=recovery,
        transaction_id="tx-backup",
        allowed_destinations=destinations,
    )
    staged = list(replacements.values())
    for index, path in enumerate(staged):
        write_staged(path, f"new-{index}".encode())
    real_copy = shutil.copy2
    copy_count = 0

    def fail_copy(source: Path, destination: Path) -> Path:
        nonlocal copy_count
        copy_count += 1
        if copy_count == fail_on_copy:
            raise OSError("injected backup failure")
        return real_copy(source, destination)

    monkeypatch.setattr("eos_kb.storage.shutil.copy2", fail_copy)
    with pytest.raises(OSError, match="injected backup failure"):
        transactional_replace(
            replacements,
            recovery_path=recovery,
            transaction_id="tx-backup",
            allowed_destinations=destinations,
        )

    assert [path.read_bytes() for path in destinations] == [b"old-0", b"old-1", b"old-2"]
    assert not recovery.exists()
    assert not any(path.exists() for path in staged)
    assert not list(tmp_path.glob(".*.backup.tmp"))


def test_recovery_record_write_failure_cleans_prepared_backups_and_staged_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destinations = [tmp_path / "a", tmp_path / "b"]
    destinations[0].write_bytes(b"old-a")
    destinations[1].write_bytes(b"old-b")
    recovery = tmp_path / "state" / "transaction.json"
    real_replace = os.replace

    def fail_recovery_write(source: Path | str, destination: Path | str) -> None:
        if Path(destination) == recovery:
            raise OSError("injected recovery write failure")
        real_replace(source, destination)

    monkeypatch.setattr("eos_kb.storage.os.replace", fail_recovery_write)

    with pytest.raises(OSError, match="injected recovery write failure"):
        begin_transaction(
            destinations,
            recovery_path=recovery,
            transaction_id="tx-record",
            allowed_destinations=destinations,
        )

    assert [path.read_bytes() for path in destinations] == [b"old-a", b"old-b"]
    assert not recovery.exists()
    assert not list(tmp_path.glob(".*.stage.tmp"))
    assert not list(tmp_path.glob(".*.backup.tmp"))
    assert not list(recovery.parent.glob("*.tmp"))


def test_valid_recovery_record_survives_process_interruption_until_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SimulatedCrash(BaseException):
        pass

    live_a = tmp_path / "a"
    live_b = tmp_path / "b"
    live_a.write_bytes(b"old-a")
    live_b.write_bytes(b"old-b")
    recovery = tmp_path / "state" / "transaction.json"
    replacements = begin_transaction(
        [live_a, live_b],
        recovery_path=recovery,
        transaction_id="tx-crash",
        allowed_destinations=(live_a, live_b),
    )
    staged_a = replacements[live_a.resolve()]
    staged_b = replacements[live_b.resolve()]
    write_staged(staged_a, b"new-a")
    write_staged(staged_b, b"new-b")
    real_replace = os.replace

    def interrupt(source: Path | str, destination: Path | str) -> None:
        if Path(source) == staged_b:
            raise SimulatedCrash()
        real_replace(source, destination)

    monkeypatch.setattr("eos_kb.storage.os.replace", interrupt)

    with pytest.raises(SimulatedCrash):
        transactional_replace(
            replacements,
            recovery_path=recovery,
            transaction_id="tx-crash",
            allowed_destinations=(live_a, live_b),
        )

    assert recovery.exists()
    assert json.loads(recovery.read_text(encoding="utf-8"))["transaction_id"] == "tx-crash"
    monkeypatch.setattr("eos_kb.storage.os.replace", real_replace)

    recover_stale_transaction(
        recovery,
        allowed_destinations=(live_a, live_b),
    )

    assert live_a.read_bytes() == b"old-a"
    assert live_b.read_bytes() == b"old-b"
    assert not recovery.exists()
    assert not staged_a.exists()
    assert not staged_b.exists()
    assert not list(tmp_path.glob(".*.backup.tmp"))


def test_process_interruption_during_backup_preserves_intent_for_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SimulatedCrash(BaseException):
        pass

    destinations = [tmp_path / "a", tmp_path / "b"]
    destinations[0].write_bytes(b"old-a")
    destinations[1].write_bytes(b"old-b")
    recovery = tmp_path / "state" / "transaction.json"
    replacements = begin_transaction(
        destinations,
        recovery_path=recovery,
        transaction_id="tx-backup-crash",
        allowed_destinations=destinations,
    )
    for staged, data in zip(replacements.values(), (b"new-a", b"new-b"), strict=True):
        write_staged(staged, data)
    real_copy = shutil.copy2
    copies = 0

    def interrupt(source: Path, destination: Path) -> Path:
        nonlocal copies
        copies += 1
        if copies == 2:
            raise SimulatedCrash()
        return real_copy(source, destination)

    monkeypatch.setattr("eos_kb.storage.shutil.copy2", interrupt)
    with pytest.raises(SimulatedCrash):
        transactional_replace(
            replacements,
            recovery_path=recovery,
            transaction_id="tx-backup-crash",
            allowed_destinations=destinations,
        )

    assert recovery.exists()
    assert json.loads(recovery.read_text(encoding="utf-8"))["phase"] == "intent"
    assert list(tmp_path.glob(".*.backup.tmp"))

    monkeypatch.setattr("eos_kb.storage.shutil.copy2", real_copy)
    recover_stale_transaction(recovery, allowed_destinations=destinations)

    assert [path.read_bytes() for path in destinations] == [b"old-a", b"old-b"]
    assert not recovery.exists()
    assert not list(tmp_path.glob(".*.stage.tmp"))
    assert not list(tmp_path.glob(".*.backup.tmp"))


def test_transaction_intent_is_durable_before_staging_and_recovers_staging_crash(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    router_root = tmp_path / "knowledge"
    database = state / "index.sqlite3"
    router = router_root / "areas" / "index.md"
    recovery = state / "transaction.json"
    database.parent.mkdir(parents=True)
    router.parent.mkdir(parents=True)
    database.write_bytes(b"old database")
    router.write_bytes(b"old router")

    replacements = begin_transaction(
        [database, router],
        recovery_path=recovery,
        transaction_id="tx-staging-crash",
        allowed_destinations=(database, router),
    )

    payload = json.loads(recovery.read_text(encoding="utf-8"))
    assert payload["phase"] == "intent"
    assert all(not staged.exists() for staged in replacements.values())
    write_staged(replacements[database], b"new database")

    recover_stale_transaction(
        recovery,
        allowed_destinations=(database, router),
    )

    assert database.read_bytes() == b"old database"
    assert router.read_bytes() == b"old router"
    assert not recovery.exists()
    assert not any(path.exists() for path in replacements.values())


def test_rollback_failure_preserves_artifacts_for_stale_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "state"
    router_root = tmp_path / "knowledge"
    first = router_root / "first.md"
    second = router_root / "second.md"
    recovery = state / "transaction.json"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"old first")
    second.write_bytes(b"old second")
    replacements = begin_transaction(
        [first, second],
        recovery_path=recovery,
        transaction_id="tx-rollback-failure",
        allowed_destinations=(first, second),
    )
    write_staged(replacements[first], b"new first")
    write_staged(replacements[second], b"new second")
    real_replace = os.replace

    def fail_restore(source: Path | str, destination: Path | str) -> None:
        source_path = Path(source)
        if source_path.name.endswith(".backup.tmp"):
            raise OSError("injected rollback failure")
        real_replace(source, destination)

    monkeypatch.setattr("eos_kb.storage.os.replace", fail_restore)
    with pytest.raises(StorageError) as failure:
        transactional_replace(
            replacements,
            recovery_path=recovery,
            transaction_id="tx-rollback-failure",
            allowed_destinations=(first, second),
            simulate_failure_after=1,
        )

    assert failure.value.code == "storage.rollback_failed"
    assert recovery.exists()
    payload = json.loads(recovery.read_text(encoding="utf-8"))
    assert payload["phase"] == "rollback_failed"
    assert any(Path(entry["backup"]).exists() for entry in payload["entries"])
    assert any(Path(entry["staged"]).exists() for entry in payload["entries"])

    monkeypatch.setattr("eos_kb.storage.os.replace", real_replace)
    recover_stale_transaction(
        recovery,
        allowed_destinations=(first, second),
    )

    assert first.read_bytes() == b"old first"
    assert second.read_bytes() == b"old second"
    assert not recovery.exists()
    assert not any(Path(entry["backup"]).exists() for entry in payload["entries"])
    assert not any(Path(entry["staged"]).exists() for entry in payload["entries"])


def test_recovery_rejects_malformed_journal_without_mutating_files(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    router_root = tmp_path / "knowledge"
    recovery = state / "transaction.json"
    outside = tmp_path / "outside.md"
    state.mkdir()
    router_root.mkdir()
    outside.write_bytes(b"outside")
    recovery.write_text('{"schema_version": 1, "entries": "invalid"}', encoding="utf-8")

    with pytest.raises(StorageError) as failure:
        recover_stale_transaction(
            recovery,
            allowed_destinations=(state / "index.sqlite3", router_root / "index.md"),
        )

    assert failure.value.code == "storage.recovery_journal_invalid"
    assert outside.read_bytes() == b"outside"
    assert recovery.exists()


def test_recovery_rejects_destination_outside_exact_allowlist(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    router_root = tmp_path / "knowledge"
    recovery = state / "transaction.json"
    outside = tmp_path / "outside.md"
    state.mkdir()
    router_root.mkdir()
    outside.write_bytes(b"outside")
    recovery.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "transaction_id": "forged",
                "phase": "promoting",
                "entries": [
                    {
                        "destination": str(outside),
                        "staged": str(tmp_path / ".outside.md.forged.stage.tmp"),
                        "backup": str(tmp_path / ".outside.md.forged.backup.tmp"),
                        "existed": True,
                        "original_hash": hashlib.sha256(b"outside").hexdigest(),
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    with pytest.raises(StorageError) as failure:
        recover_stale_transaction(
            recovery,
            allowed_destinations=(state / "index.sqlite3", router_root / "index.md"),
        )

    assert failure.value.code == "storage.recovery_destination_not_allowed"
    assert outside.read_bytes() == b"outside"
    assert recovery.exists()
