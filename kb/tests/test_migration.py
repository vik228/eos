from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from eos_kb.migration import (
    MigrationError,
    apply,
    inventory,
    manifest_hash,
    plan,
    record_migration_approval,
    rollback,
    verify_plan,
)
from eos_kb.sessions import end_session, start_session


@pytest.fixture(autouse=True)
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))


def _legacy(root: Path) -> None:
    (root / "areas").mkdir(parents=True)
    (root / "00-index.md").write_text("# Knowledge\n", encoding="utf-8")
    (root / "_pending-kb-updates.md").write_text("# Pending\n", encoding="utf-8")
    (root / "areas/coding-guidelines.md").write_text("# Coding Guidelines\n", encoding="utf-8")
    (root / "unknown.bin").write_bytes(b"opaque")
    (root / "areas/coding-guidelines.md").chmod(0o640)


def _approval(root: Path, manifest: dict[str, object], *, session_root: Path | None = None) -> str:
    state_root = session_root or root
    session = start_session(
        state_root,
        cwd=state_root,
        agent="codex",
        profile="migration",
        session_id="migration-session",
    )
    record = record_migration_approval(
        root,
        manifest_hash=manifest_hash(manifest),
        approved_by="Vikas",
        session_id=session["session_id"],
    )
    assert record["event"] == "migration_approval"
    assert record["timestamp"]
    return session["session_id"]


def test_inventory_is_lossless_and_infers_only_type_and_title(tmp_path: Path) -> None:
    root = tmp_path / "personal" / "knowledge"
    _legacy(root)

    entries = inventory(root)
    guideline = next(item for item in entries if item["source_path"] == "areas/coding-guidelines.md")

    assert set(guideline) == {
        "source_path", "source_hash", "source_type", "link_target", "target_path", "inferred_type",
        "planned_metadata", "permissions", "action",
    }
    assert guideline["source_type"] == "file"
    assert guideline["link_target"] is None
    assert guideline["planned_metadata"] == {"type": "Note", "title": "Coding Guidelines"}
    assert "description" not in guideline["planned_metadata"]
    assert "claims" not in guideline["planned_metadata"]
    assert guideline["permissions"] == 0o640


def test_migration_enriches_partial_legacy_frontmatter_without_rewriting_it(tmp_path: Path) -> None:
    root = tmp_path / "personal" / "knowledge"
    _legacy(root)
    log = root / "areas" / "legacy-log.md"
    original = (
        "---\n"
        "date: 2026-07-21 to 2026-07-24\n"
        "paper: Collobert & Weston 2008\n"
        "---\n"
        "# Code Walkthrough\n\n"
        "Durable body.\n"
    )
    log.write_text(original, encoding="utf-8")

    manifest = plan(root, mode="personal", scope="all")
    entry = next(item for item in manifest["entries"] if item["source_path"] == "areas/legacy-log.md")

    assert entry["action"] == "enrich-frontmatter"
    assert entry["planned_metadata"] == {"type": "Note", "title": "Code Walkthrough"}

    receipt = tmp_path / "receipt.json"
    apply(
        root,
        manifest,
        expected_hash=manifest_hash(manifest),
        approved_by="Vikas",
        approval_session=_approval(root, manifest),
        receipt_out=receipt,
    )

    migrated = log.read_text(encoding="utf-8")
    assert "date: 2026-07-21 to 2026-07-24\n" in migrated
    assert "paper: Collobert & Weston 2008\n" in migrated
    assert "type: Note\n" in migrated
    assert "title: Code Walkthrough\n" in migrated
    assert migrated.endswith("# Code Walkthrough\n\nDurable body.\n")


def test_personal_plan_verifies_content_addressed_inputs(tmp_path: Path) -> None:
    root = tmp_path / "personal" / "knowledge"
    _legacy(root)
    manifest = plan(root, mode="personal", scope="all")

    verification = verify_plan(manifest)
    assert verification.manifest_hash == manifest_hash(manifest)
    assert len(manifest["entries"]) == 4

    (root / "00-index.md").write_text("changed\n", encoding="utf-8")
    with pytest.raises(MigrationError) as raised:
        verify_plan(manifest)
    assert raised.value.code == "migration.plan_changed"


def test_apply_and_rollback_preserve_bytes_permissions_and_unknown_files(tmp_path: Path) -> None:
    root = tmp_path / "personal" / "knowledge"
    _legacy(root)
    original = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    manifest = plan(root, mode="personal", scope="all")
    digest = manifest_hash(manifest)
    receipt = tmp_path / "receipt.json"
    session_id = _approval(root, manifest)

    apply(
        root,
        manifest,
        expected_hash=digest,
        approved_by="Vikas",
        approval_session=session_id,
        receipt_out=receipt,
    )
    assert (root / "00-index.md").read_bytes().startswith(b"---\n")
    assert (root / "unknown.bin").read_bytes() == b"opaque"
    assert stat.S_IMODE((root / "areas/coding-guidelines.md").stat().st_mode) == 0o640

    rolled_back = rollback(root, manifest, expected_hash=digest, receipt=receipt)
    assert rolled_back["state"] == "rolled_back"
    assert {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()} == original


def test_interrupted_apply_restores_old_live_state(tmp_path: Path) -> None:
    root = tmp_path / "personal" / "knowledge"
    _legacy(root)
    original = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    manifest = plan(root, mode="personal", scope="all")
    receipt = tmp_path / "receipt.json"
    session_id = _approval(root, manifest)

    with pytest.raises(MigrationError):
        apply(
            root,
            manifest,
            expected_hash=manifest_hash(manifest),
            approved_by="Vikas",
            approval_session=session_id,
            receipt_out=receipt,
            simulate_failure_after=1,
        )

    assert {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()} == original
    assert json.loads(receipt.read_text())["state"] == "rolled_back"


def test_inventory_and_round_trip_preserve_symlink_type_and_target(tmp_path: Path) -> None:
    root = tmp_path / "personal" / "knowledge"
    _legacy(root)
    target = root / "areas" / "coding-guidelines.md"
    link = root / "areas" / "guidelines-alias.md"
    link.symlink_to(target.relative_to(link.parent))

    manifest = plan(root, mode="personal", scope="all")
    entry = next(item for item in manifest["entries"] if item["source_path"] == "areas/guidelines-alias.md")
    assert entry["source_type"] == "symlink"
    assert entry["link_target"] == "coding-guidelines.md"

    digest = manifest_hash(manifest)
    session_id = _approval(root, manifest)
    receipt = tmp_path / "receipt.json"
    apply(
        root,
        manifest,
        expected_hash=digest,
        approved_by="Vikas",
        approval_session=session_id,
        receipt_out=receipt,
    )
    assert link.is_symlink()
    assert os.readlink(link) == "coding-guidelines.md"

    rollback(root, manifest, expected_hash=digest, receipt=receipt)
    assert link.is_symlink()
    assert os.readlink(link) == "coding-guidelines.md"


@pytest.mark.parametrize(
    ("approval_session", "approval_hash", "expected_code"),
    [
        ("missing-session", None, "migration.session_invalid"),
        ("migration-session", "0" * 64, "migration.approval_missing"),
    ],
)
def test_apply_requires_valid_same_kb_session_and_exact_approval(
    tmp_path: Path,
    approval_session: str,
    approval_hash: str | None,
    expected_code: str,
) -> None:
    root = tmp_path / "personal" / "knowledge"
    _legacy(root)
    manifest = plan(root, mode="personal", scope="all")
    if approval_hash is not None:
        session = start_session(root, cwd=root, agent="codex", profile="migration", session_id=approval_session)
        record_migration_approval(
            root,
            manifest_hash=approval_hash,
            approved_by="Vikas",
            session_id=session["session_id"],
        )
    receipt = tmp_path / "receipt.json"

    with pytest.raises(MigrationError) as raised:
        apply(
            root,
            manifest,
            expected_hash=manifest_hash(manifest),
            approved_by="Vikas",
            approval_session=approval_session,
            receipt_out=receipt,
        )
    assert raised.value.code == expected_code


def test_apply_rejects_approval_from_another_kb(tmp_path: Path) -> None:
    source_root = tmp_path / "personal" / "knowledge"
    other_root = tmp_path / "other" / "knowledge"
    _legacy(source_root)
    _legacy(other_root)
    manifest = plan(source_root, mode="personal", scope="all")
    session = start_session(other_root, cwd=other_root, agent="codex", profile="migration", session_id="other-session")
    record_migration_approval(
        other_root,
        manifest_hash=manifest_hash(manifest),
        approved_by="Vikas",
        session_id=session["session_id"],
    )

    with pytest.raises(MigrationError) as raised:
        apply(
            source_root,
            manifest,
            expected_hash=manifest_hash(manifest),
            approved_by="Vikas",
            approval_session=session["session_id"],
            receipt_out=tmp_path / "receipt.json",
        )
    assert raised.value.code == "migration.session_invalid"


def test_apply_rejects_file_replaced_by_symlink_even_when_bytes_match(tmp_path: Path) -> None:
    root = tmp_path / "personal" / "knowledge"
    _legacy(root)
    target = root / "areas" / "coding-guidelines.md"
    manifest = plan(root, mode="personal", scope="all")
    session_id = _approval(root, manifest)
    target.unlink()
    target.symlink_to("../00-index.md")

    with pytest.raises(MigrationError) as raised:
        apply(
            root,
            manifest,
            expected_hash=manifest_hash(manifest),
            approved_by="Vikas",
            approval_session=session_id,
            receipt_out=tmp_path / "receipt.json",
        )
    assert raised.value.code in {"migration.plan_changed", "migration.source_changed"}


def test_apply_rejects_inactive_session_and_wrong_approver(tmp_path: Path) -> None:
    root = tmp_path / "personal" / "knowledge"
    _legacy(root)
    manifest = plan(root, mode="personal", scope="all")
    session = start_session(root, cwd=root, agent="codex", profile="migration", session_id="migration-session")
    record_migration_approval(
        root,
        manifest_hash=manifest_hash(manifest),
        approved_by="Vikas",
        session_id=session["session_id"],
    )
    end_session(root, session["session_id"], exit_code=0)

    with pytest.raises(MigrationError) as inactive:
        apply(
            root,
            manifest,
            expected_hash=manifest_hash(manifest),
            approved_by="Vikas",
            approval_session=session["session_id"],
            receipt_out=tmp_path / "inactive.json",
        )
    assert inactive.value.code == "migration.session_invalid"

    active = start_session(root, cwd=root, agent="codex", profile="migration", session_id="active-session")
    with pytest.raises(MigrationError) as wrong_actor:
        apply(
            root,
            manifest,
            expected_hash=manifest_hash(manifest),
            approved_by="Someone Else",
            approval_session=active["session_id"],
            receipt_out=tmp_path / "wrong-actor.json",
        )
    assert wrong_actor.value.code == "migration.approval_missing"
