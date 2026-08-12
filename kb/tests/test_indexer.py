from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from eos_kb.indexer import index_bundle, validate_bundle
from eos_kb.config import initialize_bundle
from eos_kb.cli import ExitCode, main
from eos_kb.schema import load_schema
from eos_kb.storage import (
    StorageError,
    state_directory,
    transactional_replace as real_transactional_replace,
)


def write_concept(root: Path, relative: str, *, resource: str, title: str, body: str, **metadata: object) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = {"type": "Decision", "title": title, "resource": resource, **metadata}
    yaml_lines = ["---"] + [f"{key}: {json.dumps(value)}" for key, value in fields.items()] + ["---", body]
    path.write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))
    root = tmp_path / "knowledge"
    write_concept(root, "areas/a.md", resource="kb:a", title="A", body="# Intro\nA links to [B](../patterns/b.md).")
    write_concept(root, "patterns/b.md", resource="kb:b", title="B", body="# Details\nB body.\n[A](../areas/a.md)")
    write_concept(root, "projects/demo/index.md", resource="kb:router", title="Router", body="Old router", generated=True)
    (root / ".eos").mkdir()
    (root / ".eos" / "state.md").write_text("not a concept", encoding="utf-8")
    return root


def test_index_stores_concepts_headings_links_reverse_edges_and_fts(bundle: Path) -> None:
    report = index_bundle(bundle)
    assert report.errors == []
    assert report.database_path.parent == state_directory(bundle)
    assert sorted(path.name for path in (bundle / ".eos").iterdir()) == ["state.md"]
    connection = report.connection
    assert connection.execute("SELECT count(*) FROM concepts").fetchone()[0] == 2
    assert connection.execute("SELECT title FROM headings").fetchone()[0] == "Intro"
    assert connection.execute("SELECT source, target FROM links").fetchone() == ("areas/a.md", "patterns/b.md")
    assert connection.execute("SELECT source FROM reverse_links WHERE target = 'patterns/b.md'").fetchone()[0] == "areas/a.md"
    assert connection.execute("SELECT relative_file FROM concepts_fts WHERE concepts_fts MATCH 'body'").fetchone()[0] == "patterns/b.md"


def test_index_reports_graph_and_resource_diagnostics(bundle: Path) -> None:
    write_concept(bundle, "areas/index.md", resource="kb:areas", title="Areas", body="[A](a.md)")
    write_concept(bundle, "areas/duplicate.md", resource="kb:b", title="Duplicate", body="duplicate")
    write_concept(bundle, "areas/broken.md", resource="kb:broken", title="Broken", body="[missing](missing.md)")
    write_concept(bundle, "areas/deprecated.md", resource="kb:old", title="Old", body="old", status="deprecated")
    write_concept(bundle, "areas/current.md", resource="kb:current", title="Current", body="[old](deprecated.md)")
    write_concept(bundle, "areas/orphan.md", resource="kb:orphan", title="Orphan", body="orphan")
    report = index_bundle(bundle)
    codes = {error.code for error in report.errors}
    assert {"broken_link", "duplicate_resource", "orphan", "deprecated_current_link"} <= codes


def test_validate_reports_supersession_cycle_and_router_drift(bundle: Path) -> None:
    write_concept(bundle, "areas/one.md", resource="kb:one", title="One", body="one", eos={"supersedes": ["areas/two.md"]})
    write_concept(bundle, "areas/two.md", resource="kb:two", title="Two", body="two", eos={"supersedes": ["areas/one.md"]})
    index_bundle(bundle)
    router = bundle / "projects/demo/index.md"
    router.write_text(router.read_text(encoding="utf-8") + "manual edit\n", encoding="utf-8")
    report = validate_bundle(bundle, strict=True)
    codes = {error.code for error in report.errors}
    assert "supersession_cycle" in codes
    assert "router_drift" in codes


def test_router_generation_is_immediate_deterministic_and_excludes_generated_inputs(bundle: Path) -> None:
    write_concept(bundle, "areas/generated.md", resource="kb:generated", title="Generated", body="generated", generated=True)
    write_concept(bundle, "areas/child/nested.md", resource="kb:nested", title="Nested", body="[A](../a.md)")
    with (bundle / "areas" / "a.md").open("a", encoding="utf-8") as stream:
        stream.write("\n[Nested](child/nested.md)\n")
    first = index_bundle(bundle)
    router = bundle / "areas/index.md"
    first_bytes = router.read_bytes()
    second = index_bundle(bundle)
    assert first_bytes == router.read_bytes()
    text = router.read_text(encoding="utf-8")
    assert "(a.md)" in text
    assert "child/index.md" in text
    assert "generated.md" not in text
    assert "generated: true" in text
    assert first.manifest["routers"]["areas/index.md"]["input_hash"] == second.manifest["routers"]["areas/index.md"]["input_hash"]


def test_failed_rebuild_preserves_prior_database(bundle: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = index_bundle(bundle)
    original = first.database_path.read_bytes()
    write_concept(bundle, "areas/new.md", resource="kb:new", title="New", body="new")
    with monkeypatch.context() as context:
        context.setattr("eos_kb.indexer.parse_concept", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
        with pytest.raises(RuntimeError):
            index_bundle(bundle)
    assert first.database_path.read_bytes() == original


def test_first_invalid_build_promotes_no_state_or_routers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "knowledge"
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))
    invalid = root / "areas" / "invalid.md"
    invalid.parent.mkdir(parents=True)
    invalid.write_text("---\ntitle: Missing type\n---\nInvalid\n", encoding="utf-8")

    report = index_bundle(root)

    assert {error.code for error in report.errors} == {"invalid_concept"}
    assert report.connection is None
    assert not report.database_path.exists()
    assert not (report.database_path.parent / "manifest.json").exists()
    assert not (root / "areas" / "index.md").exists()
    assert not (root / ".eos").exists()


def test_invalid_rebuild_preserves_database_manifest_and_router_bytes(bundle: Path) -> None:
    first = index_bundle(bundle)
    manifest_path = first.database_path.parent / "manifest.json"
    router_path = bundle / "areas" / "index.md"
    before = {
        "database": first.database_path.read_bytes(),
        "manifest": manifest_path.read_bytes(),
        "router": router_path.read_bytes(),
    }
    write_concept(bundle, "areas/duplicate.md", resource="kb:a", title="Changed", body="changed")

    report = index_bundle(bundle, rebuild=True)

    assert "duplicate_resource" in {error.code for error in report.errors}
    assert first.database_path.read_bytes() == before["database"]
    assert manifest_path.read_bytes() == before["manifest"]
    assert router_path.read_bytes() == before["router"]


def test_validate_recomputes_all_graph_diagnostics_without_changing_index(bundle: Path) -> None:
    first = index_bundle(bundle)
    database_before = first.database_path.read_bytes()
    manifest_path = first.database_path.parent / "manifest.json"
    manifest_before = manifest_path.read_bytes()
    write_concept(bundle, "areas/index.md", resource="kb:areas", title="Areas", body="[A](a.md)")
    write_concept(bundle, "areas/duplicate.md", resource="kb:b", title="Duplicate", body="duplicate")
    write_concept(bundle, "areas/broken.md", resource="kb:broken", title="Broken", body="[missing](missing.md)")
    write_concept(bundle, "areas/deprecated.md", resource="kb:old", title="Old", body="old", status="deprecated")
    write_concept(bundle, "areas/current.md", resource="kb:current", title="Current", body="[old](deprecated.md)")
    write_concept(bundle, "areas/one.md", resource="kb:one", title="One", body="one", eos={"supersedes": ["areas/two.md"]})
    write_concept(bundle, "areas/two.md", resource="kb:two", title="Two", body="two", eos={"supersedes": ["areas/one.md"]})
    invalid = bundle / "areas" / "invalid.md"
    invalid.write_text("---\ntitle: Invalid\n---\ninvalid\n", encoding="utf-8")

    report = validate_bundle(bundle, strict=True)

    assert {
        "broken_link",
        "duplicate_resource",
        "deprecated_current_link",
        "orphan",
        "supersession_cycle",
        "invalid_concept",
    } <= {error.code for error in report.errors}
    assert first.database_path.read_bytes() == database_before
    assert manifest_path.read_bytes() == manifest_before


def test_validate_missing_index_does_not_create_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))
    state = state_directory(root)

    report = validate_bundle(root, strict=True)

    assert "index_missing" in {error.code for error in report.errors}
    assert report.connection is None
    assert not (state / "index.sqlite3").exists()
    assert not state.exists()


def test_router_inputs_include_empty_and_deep_on_disk_children(bundle: Path) -> None:
    (bundle / "areas" / "empty").mkdir()
    nested = bundle / "areas" / "deep" / "nested"
    nested.mkdir(parents=True)
    write_concept(bundle, "areas/deep/nested/index.md", resource="kb:generated", title="Generated", body="generated", generated=True)
    (bundle / "areas" / ".git").mkdir()
    (bundle / "areas" / ".eos").mkdir()

    report = index_bundle(bundle)

    inputs = report.manifest["routers"]["areas/index.md"]["inputs"]
    assert {entry["directory"] for entry in inputs if "directory" in entry} == {
        "areas/deep",
        "areas/empty",
    }
    text = (bundle / "areas" / "index.md").read_text(encoding="utf-8")
    assert "deep/index.md" in text
    assert "empty/index.md" in text
    assert ".git" not in text
    assert ".eos" not in text


def test_discovery_keeps_non_generated_router_names_and_lifecycle_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "knowledge"
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))
    write_concept(root, "index.md", resource="kb:root", title="Root", body="[Log](logs/00-index.md) [Archive](archive/_pending-kb-updates.md) [Inbox](inbox/item.md)")
    write_concept(root, "logs/00-index.md", resource="kb:log", title="Log", body="[Root](../index.md)")
    write_concept(root, "archive/_pending-kb-updates.md", resource="kb:archive", title="Archive", body="[Root](../index.md)")
    write_concept(root, "inbox/item.md", resource="kb:inbox", title="Inbox", body="[Root](../index.md)")
    write_concept(root, ".eos/ignored.md", resource="kb:eos", title="Ignored", body="ignored")
    write_concept(root, ".git/ignored.md", resource="kb:git", title="Ignored", body="ignored")

    report = index_bundle(root)

    assert report.errors == []
    assert {row[0] for row in report.connection.execute("SELECT relative_file FROM concepts")} == {
        "index.md",
        "logs/00-index.md",
        "archive/_pending-kb-updates.md",
        "inbox/item.md",
    }


def test_index_stages_every_artifact_next_to_its_destination(
    bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[Path, Path]] = []

    def capture(replacements: dict[Path, Path], **kwargs: object) -> None:
        observed.extend(replacements.items())
        real_transactional_replace(replacements, **kwargs)

    monkeypatch.setattr("eos_kb.indexer.transactional_replace", capture)

    index_bundle(bundle)

    assert observed
    assert all(destination.parent == staged.parent for destination, staged in observed)
    assert not [path for path in bundle.rglob("*.tmp")]


def test_index_distinguishes_standard_sources_from_source_paths(bundle: Path) -> None:
    write_concept(
        bundle,
        "areas/sourced.md",
        resource="kb:sourced",
        title="Sourced",
        body="[A](a.md)",
        sources=["https://example.test/reference"],
        eos={"source_paths": ["src/example.py"]},
    )
    with (bundle / "areas" / "a.md").open("a", encoding="utf-8") as stream:
        stream.write("\n[Sourced](sourced.md)\n")

    report = index_bundle(bundle)

    assert set(report.connection.execute("SELECT source_kind, source_value FROM sources WHERE relative_file = 'areas/sourced.md'")) == {
        ("source", "https://example.test/reference"),
        ("source_path", "src/example.py"),
    }


def test_manifest_schema_describes_runtime_router_inputs() -> None:
    schema = load_schema("manifest")
    router = schema["properties"]["routers"]["additionalProperties"]
    inputs = router["properties"]["inputs"]["items"]

    assert inputs["oneOf"] == [
        {
            "type": "object",
            "required": ["path", "metadata_hash"],
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "metadata_hash": {"$ref": "#/$defs/sha256"},
            },
            "additionalProperties": False,
        },
        {
            "type": "object",
            "required": ["directory"],
            "properties": {"directory": {"type": "string", "minLength": 1}},
            "additionalProperties": False,
        },
    ]


def test_initialized_bundle_indexes_validates_and_reruns_deterministically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "knowledge"
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))
    initialize_bundle(root, "demo")

    first = index_bundle(root)
    assert first.errors == []
    assert first.database_path.is_file()
    manifest_path = first.database_path.parent / "manifest.json"
    assert manifest_path.is_file()
    first_manifest = manifest_path.read_bytes()
    first_routers = {
        relative: (root / relative).read_bytes()
        for relative in first.manifest["routers"]
    }
    validation = validate_bundle(root, strict=True)
    assert validation.errors == []

    second = index_bundle(root, rebuild=True)
    assert second.errors == []
    assert manifest_path.read_bytes() == first_manifest
    assert {
        relative: (root / relative).read_bytes()
        for relative in second.manifest["routers"]
    } == first_routers


def test_generated_parent_router_reaches_authored_child_router(bundle: Path) -> None:
    write_concept(
        bundle,
        "areas/index.md",
        resource="kb:areas",
        title="Areas",
        body="[A](a.md)",
    )

    report = index_bundle(bundle)

    assert report.errors == []
    assert "generated: true" not in (bundle / "areas" / "index.md").read_text(
        encoding="utf-8"
    )


def test_generated_router_for_numeric_directory_is_valid_yaml(bundle: Path) -> None:
    write_concept(
        bundle,
        "logs/2026/session.md",
        resource="kb:session",
        title="Session",
        body="# Session\n",
    )

    indexed = index_bundle(bundle)
    validated = validate_bundle(bundle, strict=True)

    assert indexed.errors == []
    assert validated.errors == []
    assert 'title: "2026"' in (bundle / "logs" / "2026" / "index.md").read_text(
        encoding="utf-8"
    )


def test_index_repairs_invalid_generated_router_from_older_runtime(bundle: Path) -> None:
    write_concept(
        bundle,
        "logs/2026/session.md",
        resource="kb:session",
        title="Session",
        body="# Session\n",
    )
    router = bundle / "logs" / "2026" / "index.md"
    router.write_text(
        "---\n"
        "type: index\n"
        "title: 2026\n"
        "description: Generated directory router.\n"
        "generated: true\n"
        "---\n"
        "# 2026\n",
        encoding="utf-8",
    )

    indexed = index_bundle(bundle)
    validated = validate_bundle(bundle, strict=True)

    assert indexed.errors == []
    assert validated.errors == []
    assert 'title: "2026"' in router.read_text(encoding="utf-8")


def test_external_markdown_urls_do_not_create_local_graph_edges(bundle: Path) -> None:
    with (bundle / "areas" / "a.md").open("a", encoding="utf-8") as stream:
        stream.write(
            "\n[HTTPS](https://example.test/reference.md) "
            "[Protocol relative](//cdn.example.test/reference.md) "
            "[Mail](mailto:owner@example.test)\n"
        )

    report = index_bundle(bundle)

    assert report.errors == []
    links = set(report.connection.execute("SELECT source, target FROM links"))
    assert links == {
        ("areas/a.md", "patterns/b.md"),
        ("patterns/b.md", "areas/a.md"),
    }


def test_validate_reports_corrupt_database_as_typed_diagnostic(bundle: Path) -> None:
    indexed = index_bundle(bundle)
    indexed.connection.close()
    indexed.database_path.write_bytes(b"not sqlite")

    report = validate_bundle(bundle, strict=True)

    assert report.connection is None
    assert "index_corrupt" in {error.code for error in report.errors}


def test_validate_reports_corrupt_manifest_as_typed_diagnostic(bundle: Path) -> None:
    indexed = index_bundle(bundle)
    manifest_path = indexed.database_path.parent / "manifest.json"
    manifest_path.write_bytes(b'{"truncated":')

    report = validate_bundle(bundle, strict=True)

    assert "manifest_corrupt" in {error.code for error in report.errors}
    assert "index_missing" not in {error.code for error in report.errors}


def test_validate_reports_manifest_with_invalid_runtime_shape_as_corrupt(
    bundle: Path,
) -> None:
    indexed = index_bundle(bundle)
    manifest_path = indexed.database_path.parent / "manifest.json"
    manifest_path.write_text(
        json.dumps({"schema_version": 1, "concepts": "invalid", "routers": {}}),
        encoding="utf-8",
    )

    report = validate_bundle(bundle, strict=True)

    assert "manifest_corrupt" in {error.code for error in report.errors}
    assert "index_missing" not in {error.code for error in report.errors}


def test_strict_validation_exempts_generated_routers_from_direct_change_gate(bundle: Path) -> None:
    index_bundle(bundle)
    router = bundle / "projects/demo/index.md"
    router.write_text(router.read_text(encoding="utf-8") + "manual edit\n", encoding="utf-8")

    report = validate_bundle(bundle, strict=True)

    codes = {error.code for error in report.errors}
    assert "router_drift" in codes
    assert "unreviewed_direct_change" not in codes


def test_index_writes_durable_intent_before_staging_any_artifact(
    bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = state_directory(bundle)
    recovery = state / "transaction.json"
    observed: list[Path] = []
    declared: set[Path] = set()
    from eos_kb.storage import write_staged as real_write_staged

    def capture(path: Path, data: bytes) -> None:
        payload = json.loads(recovery.read_text(encoding="utf-8"))
        assert payload["phase"] == "intent"
        declared.update(Path(entry["staged"]) for entry in payload["entries"])
        observed.append(path)
        real_write_staged(path, data)

    monkeypatch.setattr("eos_kb.indexer.write_staged", capture)

    report = index_bundle(bundle)

    assert report.errors == []
    assert set(observed) == declared
    assert not recovery.exists()


def test_index_cli_reports_forged_recovery_journal_with_stable_storage_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))
    state = state_directory(root)
    recovery = state / "transaction.json"
    outside = tmp_path / "outside.md"
    outside.write_bytes(b"outside")
    state.mkdir(parents=True)
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

    exit_code = main(["index", "--kb", str(root)])
    output = capsys.readouterr()

    assert exit_code == ExitCode.VALIDATION
    assert output.out == ""
    assert output.err == (
        "error[storage.recovery_destination_not_allowed]: "
        "Recovery journal destination is not in the trusted allowlist.\n"
    )
    assert outside.read_bytes() == b"outside"


@pytest.mark.parametrize(
    "relative_file",
    ("areas/a.md", "areas/index.md"),
    ids=("authored-concept", "authored-router"),
)
def test_recovery_rejects_schema_valid_journal_for_authored_file(
    bundle: Path,
    relative_file: str,
) -> None:
    state = state_directory(bundle)
    recovery = state / "transaction.json"
    if relative_file.endswith("index.md"):
        write_concept(
            bundle,
            relative_file,
            resource="kb:authored-router",
            title="Authored Router",
            body="[A](a.md)",
        )
    authored = bundle / relative_file
    original = authored.read_bytes()
    transaction_id = "forged-authored"
    staged = authored.parent / f".{authored.name}.{transaction_id}.stage.tmp"
    backup = authored.parent / f".{authored.name}.{transaction_id}.backup.tmp"
    state.mkdir(parents=True)
    staged.write_bytes(b"forged staged bytes")
    backup.write_bytes(b"forged backup bytes")
    recovery.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "transaction_id": transaction_id,
                "phase": "promoting",
                "entries": [
                    {
                        "destination": str(authored),
                        "staged": str(staged),
                        "backup": str(backup),
                        "existed": True,
                        "original_hash": hashlib.sha256(original).hexdigest(),
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    with pytest.raises(StorageError) as failure:
        index_bundle(bundle)

    assert failure.value.code == "storage.recovery_destination_not_allowed"
    assert authored.read_bytes() == original
    assert staged.read_bytes() == b"forged staged bytes"
    assert backup.read_bytes() == b"forged backup bytes"
    assert recovery.exists()
