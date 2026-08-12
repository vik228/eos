from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from eos_kb.cli import ExitCode, main
from eos_kb.config import initialize_bundle
from eos_kb.frontmatter import parse_concept
from eos_kb.schema import SchemaValidationError


def file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_initialize_bundle_creates_approved_layout(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    initialize_bundle(root, "demo")

    expected_files = {
        "index.md",
        "00-index.md",
        "_pending-kb-updates.md",
        "inbox/demo/index.md",
        "projects/demo/index.md",
        "projects/demo/_pending-kb-updates.md",
    }
    expected_dirs = {
        "areas",
        "patterns",
        "projects/demo/architecture",
        "projects/demo/invariants",
        "projects/demo/decisions",
        "projects/demo/runbooks",
        "projects/demo/failure-modes",
        "projects/demo/incidents",
        "projects/demo/specifications",
        "projects/demo/references",
        "logs",
        "inbox",
        "inbox/demo",
        "archive",
    }
    assert {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()} == expected_files
    assert {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_dir()} >= expected_dirs

    root_pending = parse_concept(root / "_pending-kb-updates.md", root=root)
    project_pending = parse_concept(root / "projects" / "demo" / "_pending-kb-updates.md", root=root)
    proposal_inbox = parse_concept(root / "inbox" / "demo" / "index.md", root=root)
    root_index = parse_concept(root / "index.md", root=root)
    legacy_index = parse_concept(root / "00-index.md", root=root)
    project_index = parse_concept(root / "projects" / "demo" / "index.md", root=root)
    assert [link.target for link in root_pending.links] == ["inbox/demo/index.md"]
    assert [link.target for link in project_pending.links] == ["../../inbox/demo/index.md"]
    assert proposal_inbox.concept_type == "index"
    assert root_index.generated is True
    assert project_index.generated is True
    assert proposal_inbox.generated is True
    assert legacy_index.generated is False
    assert root_pending.generated is False
    assert project_pending.generated is False


def test_initialize_bundle_preserves_existing_bytes_and_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    (root / "projects" / "demo").mkdir(parents=True)
    (root / "inbox" / "demo").mkdir(parents=True)
    (root / "index.md").write_bytes(b"user-owned bytes\n")
    (root / "_pending-kb-updates.md").write_bytes(b"root pending bytes\n")
    (root / "projects" / "demo" / "_pending-kb-updates.md").write_bytes(b"project pending bytes\n")
    (root / "inbox" / "demo" / "index.md").write_bytes(b"inbox bytes\n")
    initialize_bundle(root, "demo")
    before = file_hashes(root)
    initialize_bundle(root, "demo")

    assert (root / "index.md").read_bytes() == b"user-owned bytes\n"
    assert (root / "_pending-kb-updates.md").read_bytes() == b"root pending bytes\n"
    assert (root / "projects" / "demo" / "_pending-kb-updates.md").read_bytes() == b"project pending bytes\n"
    assert (root / "inbox" / "demo" / "index.md").read_bytes() == b"inbox bytes\n"
    assert file_hashes(root) == before


def test_initialize_bundle_rejects_symlinked_directory_below_root(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "inbox").symlink_to(outside, target_is_directory=True)

    with pytest.raises(SchemaValidationError) as raised:
        initialize_bundle(root, "demo")

    assert raised.value.code == "init.layout_conflict"
    assert raised.value.field_path == "$.layout.inbox"
    assert not (outside / "demo").exists()


def test_initialize_bundle_rejects_dangling_symlink_file(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    outside = tmp_path / "outside.md"
    root.mkdir()
    (root / "index.md").symlink_to(outside)

    with pytest.raises(SchemaValidationError) as raised:
        initialize_bundle(root, "demo")

    assert raised.value.code == "init.layout_conflict"
    assert raised.value.field_path == "$.layout.index.md"
    assert not outside.exists()


def test_initialize_bundle_rejects_file_where_directory_is_required(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "areas").write_bytes(b"keep me\n")

    with pytest.raises(SchemaValidationError) as raised:
        initialize_bundle(root, "demo")

    assert raised.value.code == "init.layout_conflict"
    assert raised.value.field_path == "$.layout.areas"
    assert (root / "areas").read_bytes() == b"keep me\n"


def test_init_cli_renders_layout_conflict_as_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "areas").write_bytes(b"keep me\n")

    exit_code = main(["init", "--kb", str(root), "--project", "demo"])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.CONFLICT
    assert captured.out == ""
    assert captured.err == "error[init.layout_conflict]: Expected 'areas' to be a directory without symlinks.\n"


def test_init_cli_renders_layout_conflict_as_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "areas").write_bytes(b"keep me\n")

    exit_code = main(["init", "--kb", str(root), "--project", "demo", "--json"])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.CONFLICT
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "command": "init",
        "error": {"code": "init.layout_conflict", "field_path": "$.layout.areas"},
        "exit_code": ExitCode.CONFLICT,
        "message": "Expected 'areas' to be a directory without symlinks.",
        "status": "conflict",
    }


def test_init_cli_converts_oserror_to_stable_conflict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_initialize(root: Path, project: str) -> None:
        raise PermissionError("host-specific details")

    monkeypatch.setattr("eos_kb.cli.initialize_bundle", fail_initialize)

    exit_code = main(["init", "--kb", str(tmp_path / "knowledge"), "--project", "demo", "--json"])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.CONFLICT
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "command": "init",
        "error": {"code": "init.io_error", "field_path": "$.layout"},
        "exit_code": ExitCode.CONFLICT,
        "message": "Unable to initialize knowledge bundle.",
        "status": "conflict",
    }
