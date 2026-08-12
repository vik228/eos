from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from eos_kb.cli import ExitCode, main
from eos_kb.freshness import (
    CoverageRule,
    FreshnessValidationError,
    PendingCoverage,
    audit_freshness,
    load_freshness,
)
from eos_kb.indexer import index_bundle
from eos_kb.retrieval import search
from eos_kb.schema import load_schema
from eos_kb.storage import SCHEMA_VERSION, state_directory


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "EOS Test")
    return root


def _commit(root: Path, message: str = "baseline") -> str:
    _git(root, "add", ".")
    _git(root, "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD")


def _concept(
    kb: Path,
    relative: str,
    *,
    resource: str,
    project: str = "alpha",
    source_paths: tuple[str, ...] = (),
    source_revision: str | None = None,
    stale_after: str | None = None,
    status: str = "stable",
    claims: tuple[tuple[str, object], ...] = (),
    sources: tuple[str, ...] = (),
    verified: tuple[dict[str, object], ...] = (),
    body: str = "# Note\nDocumented behavior.",
) -> None:
    metadata: dict[str, object] = {
        "type": "Decision",
        "title": Path(relative).stem,
        "resource": resource,
        "status": status,
    }
    if stale_after is not None:
        metadata["stale_after"] = stale_after
    if sources:
        metadata["sources"] = list(sources)
    if verified:
        metadata["verified"] = list(verified)
    eos: dict[str, object] = {"project": project}
    if source_paths:
        eos["source_paths"] = list(source_paths)
    if source_revision is not None:
        eos["source_revision"] = source_revision
    if claims:
        eos["claims"] = [{"id": claim_id, "value": value} for claim_id, value in claims]
    metadata["eos"] = eos
    lines = ["---", *[f"{key}: {json.dumps(value)}" for key, value in metadata.items()], "---", body]
    path = kb / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))
    return tmp_path / "knowledge"


def test_git_source_drift_uses_revision_blob_and_persists_external_state(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    source = repo / "src/service.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    revision = _commit(repo)
    _concept(
        isolated_state,
        "projects/alpha/service.md",
        resource="kb:alpha/service",
        source_paths=("src/service.py",),
        source_revision=revision,
    )
    index_bundle(isolated_state)

    current = audit_freshness(isolated_state, repo)
    assert current.sources[0].state == "current"
    assert current.sources[0].baseline_blob == current.sources[0].current_blob
    assert current.overall == "fresh"

    source.write_text("VALUE = 2\n", encoding="utf-8")
    drifted = audit_freshness(isolated_state, repo)
    assert drifted.sources[0].state == "drifted"
    assert drifted.overall == "stale"
    assert "source drift: kb:alpha/service (src/service.py)" in drifted.warnings
    assert load_freshness(isolated_state).as_dict() == drifted.as_dict()
    assert (state_directory(isolated_state) / "freshness.json").is_file()
    assert not (isolated_state / ".eos").exists()


def test_git_rename_without_content_change_is_current(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    original = repo / "src/original.py"
    original.parent.mkdir()
    original.write_text("VALUE = 1\n", encoding="utf-8")
    revision = _commit(repo)
    _concept(
        isolated_state,
        "projects/alpha/rename.md",
        resource="kb:alpha/rename",
        source_paths=("src/original.py",),
        source_revision=revision,
    )
    index_bundle(isolated_state)
    _git(repo, "mv", "src/original.py", "src/renamed.py")

    report = audit_freshness(isolated_state, repo)

    assert report.sources[0].state == "current"
    assert report.sources[0].current_path == "src/renamed.py"
    assert report.sources[0].renamed is True


def test_untracked_and_absent_baselines_are_unknown_not_fresh(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    tracked = repo / "src/tracked.py"
    tracked.parent.mkdir()
    tracked.write_text("VALUE = 1\n", encoding="utf-8")
    revision = _commit(repo)
    (repo / "src/untracked.py").write_text("VALUE = 2\n", encoding="utf-8")
    _concept(
        isolated_state,
        "projects/alpha/untracked.md",
        resource="kb:alpha/untracked",
        source_paths=("src/untracked.py",),
        source_revision=revision,
    )
    _concept(
        isolated_state,
        "projects/alpha/no-baseline.md",
        resource="kb:alpha/no-baseline",
        source_paths=("src/tracked.py",),
    )
    index_bundle(isolated_state)

    report = audit_freshness(isolated_state, repo)

    assert {finding.resource: finding.state for finding in report.sources} == {
        "kb:alpha/no-baseline": "unknown",
        "kb:alpha/untracked": "unknown",
    }
    assert report.overall == "unknown"
    assert "freshness: fresh" not in report.warnings


def test_time_drift_and_external_content_hashes_are_independent(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    external = tmp_path / "external.txt"
    external.write_text("baseline", encoding="utf-8")
    baseline = "sha256:" + hashlib.sha256(external.read_bytes()).hexdigest()
    _concept(
        isolated_state,
        "projects/alpha/external.md",
        resource="kb:alpha/external",
        stale_after="2026-01-01T00:00:00+00:00",
        sources=(external.as_uri(),),
        verified=({"source": external.as_uri(), "content_hash": baseline},),
    )
    index_bundle(isolated_state)

    fresh_source = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    assert fresh_source.external_sources[0].state == "current"
    assert fresh_source.time[0].state == "stale"

    external.write_text("changed", encoding="utf-8")
    changed = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    assert changed.external_sources[0].state == "drifted"
    assert changed.time[0].state == "stale"


def test_unverified_external_file_is_unknown_without_being_read(
    tmp_path: Path,
    isolated_state: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    external = tmp_path / "private.txt"
    external.write_text("private", encoding="utf-8")
    _concept(
        isolated_state,
        "external.md",
        resource="kb:alpha/external",
        sources=(external.as_uri(),),
    )
    index_bundle(isolated_state)

    def fail_read(_: Path) -> str:
        raise AssertionError("unverified external source was read")

    monkeypatch.setattr("eos_kb.freshness._sha256", fail_read)

    report = audit_freshness(isolated_state, repo)

    assert report.external_sources[0].state == "unknown"
    assert report.external_sources[0].current_hash is None


def test_naive_audit_time_is_interpreted_as_utc(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    _concept(
        isolated_state,
        "time.md",
        resource="kb:alpha/time",
        stale_after="2026-01-01T00:00:00+00:00",
    )
    index_bundle(isolated_state)

    report = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 1, 1),
    )

    assert report.time[0].state == "stale"


def test_claim_contradictions_are_project_scoped_and_ignore_deprecated_and_prose(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    _concept(isolated_state, "a.md", resource="kb:alpha/a", claims=(("mode", "one"),))
    _concept(isolated_state, "b.md", resource="kb:alpha/b", claims=(("mode", "two"),))
    _concept(isolated_state, "same.md", resource="kb:alpha/same", claims=(("mode", "one"),))
    _concept(isolated_state, "other.md", resource="kb:beta/other", project="beta", claims=(("mode", "three"),))
    _concept(isolated_state, "old.md", resource="kb:alpha/old", status="deprecated", claims=(("mode", "old"),))
    _concept(isolated_state, "prose.md", resource="kb:alpha/prose", body="# Note\nMode should actually be four.")
    index_bundle(isolated_state)

    report = audit_freshness(isolated_state, repo)

    assert len(report.contradictions) == 1
    contradiction = report.contradictions[0]
    assert contradiction.project == "alpha"
    assert contradiction.claim_id == "mode"
    assert contradiction.resources == ("kb:alpha/a", "kb:alpha/b", "kb:alpha/same")
    assert contradiction.values == ('"one"', '"two"')


def test_coverage_aggregates_current_pending_drifted_and_unknown(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    for relative in ("src/current.py", "src/pending.py", "src/drifted.py", "misc/unmapped.py"):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {relative}\n", encoding="utf-8")
    revision = _commit(repo)
    _concept(
        isolated_state,
        "projects/alpha/current.md",
        resource="kb:alpha/current",
        source_paths=("src/current.py",),
        source_revision=revision,
    )
    _concept(
        isolated_state,
        "projects/alpha/pending.md",
        resource="kb:alpha/pending",
        source_paths=("src/pending.py",),
        source_revision=revision,
    )
    _concept(
        isolated_state,
        "projects/alpha/explicit.md",
        resource="kb:alpha/explicit",
        source_revision=revision,
    )
    index_bundle(isolated_state)
    (repo / "src/pending.py").write_text("# changed pending\n", encoding="utf-8")
    (repo / "src/drifted.py").write_text("# changed drifted\n", encoding="utf-8")
    (repo / "misc/unmapped.py").write_text("# changed unknown\n", encoding="utf-8")
    pending_blob = _git(repo, "hash-object", "src/pending.py")

    report = audit_freshness(
        isolated_state,
        repo,
        coverage_rules=(
            CoverageRule(paths=("src/*.py",), concepts=("kb:alpha/explicit",), ignore=("src/ignored.py",)),
        ),
        pending_coverage=(
            PendingCoverage("kb:alpha/pending", "src/pending.py", pending_blob),
        ),
    )

    states = {finding.path: finding.state for finding in report.coverage}
    assert states == {
        "misc/unmapped.py": "unknown",
        "src/current.py": "current",
        "src/drifted.py": "drifted",
        "src/pending.py": "pending",
    }
    assert "coverage pending: src/pending.py" in report.warnings
    assert "coverage drifted: src/drifted.py" in report.warnings
    assert "coverage unknown: misc/unmapped.py" in report.warnings


def test_coverage_ignore_excludes_matching_changed_path(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    ignored = repo / "src/generated.py"
    ignored.parent.mkdir()
    ignored.write_text("# baseline\n", encoding="utf-8")
    revision = _commit(repo)
    _concept(isolated_state, "concept.md", resource="kb:alpha/concept", source_revision=revision)
    index_bundle(isolated_state)
    ignored.write_text("# changed\n", encoding="utf-8")

    report = audit_freshness(
        isolated_state,
        repo,
        coverage_rules=(
            CoverageRule(
                paths=("src/*.py",),
                concepts=("kb:alpha/concept",),
                ignore=("src/generated.py",),
            ),
        ),
    )

    assert report.coverage == ()


def test_manifest_blobs_bind_registered_coverage_to_source_revision(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    source = repo / "src/service.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    revision = _commit(repo)
    source.write_text("VALUE = 2\n", encoding="utf-8")
    _concept(
        isolated_state,
        "service.md",
        resource="kb:alpha/service",
        source_revision=revision,
    )
    rules = (
        CoverageRule(
            paths=("src/*.py",),
            concepts=("kb:alpha/service",),
        ),
    )

    indexed = index_bundle(
        isolated_state,
        source_root=repo,
        coverage_rules=rules,
    )
    report = audit_freshness(
        isolated_state,
        repo,
        coverage_rules=rules,
    )

    manifest_concept = indexed.manifest["concepts"][0]
    assert manifest_concept["source_blobs"] == [
        {
            "path": "src/service.py",
            "blob_hash": _git(repo, "rev-parse", f"{revision}:src/service.py"),
        }
    ]
    assert [(item.path, item.state) for item in report.coverage] == [
        ("src/service.py", "drifted")
    ]


def test_implicit_source_without_revision_remains_unknown(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    source = repo / "src/service.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    _commit(repo)
    source.write_text("VALUE = 2\n", encoding="utf-8")
    _concept(
        isolated_state,
        "service.md",
        resource="kb:alpha/service",
        source_paths=("src/service.py",),
    )
    index_bundle(isolated_state, source_root=repo)

    report = audit_freshness(isolated_state, repo)

    assert [(item.path, item.state) for item in report.sources] == [
        ("src/service.py", "unknown")
    ]
    assert [(item.path, item.state) for item in report.coverage] == [
        ("src/service.py", "unknown")
    ]


def test_reindex_does_not_advance_registered_coverage_baseline(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    source = repo / "src/service.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    revision = _commit(repo)
    _concept(
        isolated_state,
        "service.md",
        resource="kb:alpha/service",
        source_revision=revision,
    )
    rules = (
        CoverageRule(
            paths=("src/*.py",),
            concepts=("kb:alpha/service",),
        ),
    )
    index_bundle(isolated_state, source_root=repo, coverage_rules=rules)
    source.write_text("VALUE = 2\n", encoding="utf-8")
    assert audit_freshness(
        isolated_state,
        repo,
        coverage_rules=rules,
    ).coverage[0].state == "drifted"

    index_bundle(isolated_state, source_root=repo, coverage_rules=rules)
    after_reindex = audit_freshness(
        isolated_state,
        repo,
        coverage_rules=rules,
    )

    assert after_reindex.coverage[0].state == "drifted"
    assert "coverage drifted: src/service.py" in after_reindex.warnings


def test_audit_rejects_coverage_resource_missing_from_index(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    source = repo / "src/service.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    _commit(repo)
    _concept(isolated_state, "present.md", resource="kb:alpha/present")
    index_bundle(isolated_state)

    with pytest.raises(FreshnessValidationError) as raised:
        audit_freshness(
            isolated_state,
            repo,
            coverage_rules=(
                CoverageRule(
                    paths=("src/*.py",),
                    concepts=("kb:alpha/missing",),
                ),
            ),
        )

    assert raised.value.code == "freshness.coverage_resource_missing"
    assert raised.value.field_path == "$.coverage[0].concepts[0]"


def test_coverage_ignore_is_scoped_to_each_overlapping_rule(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    source = repo / "src/service.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    revision = _commit(repo)
    _concept(
        isolated_state,
        "ignored.md",
        resource="kb:alpha/ignored",
        source_revision=revision,
    )
    _concept(
        isolated_state,
        "tracked.md",
        resource="kb:alpha/tracked",
        source_revision=revision,
    )
    rules = (
        CoverageRule(
            paths=("src/*.py",),
            concepts=("kb:alpha/ignored",),
            ignore=("src/service.py",),
        ),
        CoverageRule(
            paths=("src/*.py",),
            concepts=("kb:alpha/tracked",),
        ),
    )
    index_bundle(isolated_state, source_root=repo, coverage_rules=rules)
    source.write_text("VALUE = 2\n", encoding="utf-8")

    report = audit_freshness(
        isolated_state,
        repo,
        coverage_rules=rules,
    )

    assert [(item.path, item.state, item.resources) for item in report.coverage] == [
        ("src/service.py", "drifted", ("kb:alpha/tracked",))
    ]


def test_freshness_schema_declares_exact_states() -> None:
    schema = load_schema("freshness")
    assert schema["properties"]["schema_version"] == {"const": 1}
    assert schema["$defs"]["state"]["enum"] == [
        "current",
        "pending",
        "drifted",
        "stale",
        "unknown",
    ]
    assert schema["properties"]["sources"]["items"] == {
        "$ref": "#/$defs/source_finding"
    }
    assert schema["properties"]["coverage"]["items"] == {
        "$ref": "#/$defs/coverage_finding"
    }
    assert set(schema["$defs"]["source_finding"]["required"]) == {
        "resource",
        "path",
        "state",
        "baseline_blob",
        "current_blob",
        "current_path",
        "renamed",
        "reason",
    }


def test_load_freshness_rejects_invalid_runtime_shape(
    isolated_state: Path,
) -> None:
    state = state_directory(isolated_state)
    state.mkdir(parents=True)
    (state / "freshness.json").write_text(
        '{"schema_version": 1, "overall": "fresh"}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="freshness state is missing or corrupt"):
        load_freshness(isolated_state)


def test_unsafe_source_path_and_revision_are_unknown(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    tracked = repo / "src/tracked.py"
    tracked.parent.mkdir()
    tracked.write_text("VALUE = 1\n", encoding="utf-8")
    _commit(repo)
    _concept(
        isolated_state,
        "unsafe.md",
        resource="kb:alpha/unsafe",
        source_paths=("../outside.py",),
        source_revision="--help",
    )
    _concept(
        isolated_state,
        "bad-revision.md",
        resource="kb:alpha/bad-revision",
        source_paths=("src/tracked.py",),
        source_revision="--help",
    )
    index_bundle(isolated_state)

    report = audit_freshness(isolated_state, repo)

    assert {item.resource: item.state for item in report.sources} == {
        "kb:alpha/bad-revision": "unknown",
        "kb:alpha/unsafe": "unknown",
    }


def test_concept_without_freshness_contract_remains_unknown(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    _concept(
        isolated_state,
        "untracked.md",
        resource="kb:alpha/untracked",
        body="# Note\nuntrackedtoken",
    )
    index_bundle(isolated_state)

    report = audit_freshness(isolated_state, repo)

    assert [(item.resource, item.state) for item in report.concepts] == [
        ("kb:alpha/untracked", "unknown")
    ]
    assert report.overall == "unknown"
    assert "freshness unknown: kb:alpha/untracked" in report.warnings
    assert search(isolated_state, "untrackedtoken")[0].freshness == "unknown"


def test_search_uses_persisted_freshness_without_reindex(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    source = repo / "src/service.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    revision = _commit(repo)
    _concept(
        isolated_state,
        "service.md",
        resource="kb:alpha/service",
        source_paths=("src/service.py",),
        source_revision=revision,
        body="# Service\nsearchtoken",
    )
    index_bundle(isolated_state)

    audit_freshness(isolated_state, repo)
    current = search(isolated_state, "searchtoken")[0]
    assert current.freshness == "fresh"
    assert "freshness: unknown" not in current.warnings
    assert search(isolated_state, "searchtoken", freshness="fresh")
    assert search(isolated_state, "searchtoken", freshness="stale") == []

    source.write_text("VALUE = 2\n", encoding="utf-8")
    audit_freshness(isolated_state, repo)
    stale = search(isolated_state, "searchtoken")[0]
    assert stale.freshness == "stale"
    assert "source drift: kb:alpha/service (src/service.py)" in stale.warnings
    assert search(isolated_state, "searchtoken", freshness="fresh") == []
    assert search(isolated_state, "searchtoken", freshness="stale")


def test_reindex_invalidates_persisted_freshness_overlay(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    source = repo / "src/service.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    revision = _commit(repo)
    _concept(
        isolated_state,
        "service.md",
        resource="kb:alpha/service",
        source_paths=("src/service.py",),
        source_revision=revision,
        body="# Service\nmanifesttoken",
    )
    index_bundle(isolated_state)
    audit_freshness(isolated_state, repo)
    assert search(isolated_state, "manifesttoken")[0].freshness == "fresh"

    _concept(
        isolated_state,
        "service.md",
        resource="kb:alpha/service",
        source_paths=("src/service.py",),
        source_revision=revision,
        body="# Service\nmanifesttoken changed",
    )
    index_bundle(isolated_state, rebuild=True)

    assert search(isolated_state, "manifesttoken")[0].freshness == "unknown"
    with pytest.raises(ValueError, match="freshness state does not match"):
        load_freshness(isolated_state)


def test_audit_rejects_corrupt_index_with_typed_error(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    state = state_directory(isolated_state)
    state.mkdir(parents=True)
    connection = sqlite3.connect(state / "index.sqlite3")
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
    connection.close()

    with pytest.raises(FreshnessValidationError) as raised:
        audit_freshness(isolated_state, repo)
    assert raised.value.code == "freshness.index_corrupt"
    assert raised.value.field_path == "$.index"


def test_cli_audit_and_stale_use_registered_source_workspace(
    tmp_path: Path,
    isolated_state: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path)
    source = repo / "src/service.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    revision = _commit(repo)
    _concept(
        isolated_state,
        "service.md",
        resource="kb:alpha/service",
        source_paths=("src/service.py",),
        source_revision=revision,
    )
    index_bundle(isolated_state)
    registry = tmp_path / "workspaces.yaml"
    registry.write_text(
        "workspaces:\n"
        f"  {repo}:\n"
        f"    kb: {isolated_state}\n"
        "    project: alpha\n"
        "    coverage:\n"
        "      - paths: ['src/*.py']\n"
        "        concepts: ['kb:alpha/service']\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EOS_KB_REGISTRY", str(registry))
    monkeypatch.chdir(repo)

    assert main(["audit", "--json"]) == ExitCode.SUCCESS
    audited = json.loads(capsys.readouterr().out)
    assert audited["status"] == "audited"
    assert audited["data"]["overall"] == "fresh"

    source.write_text("VALUE = 2\n", encoding="utf-8")
    assert main(["audit", "--json"]) == ExitCode.SUCCESS
    changed = json.loads(capsys.readouterr().out)
    assert changed["data"]["overall"] == "stale"

    assert main(["stale", "--json"]) == ExitCode.SUCCESS
    stale = json.loads(capsys.readouterr().out)
    assert stale["status"] == "stale"
    assert "source drift: kb:alpha/service (src/service.py)" in stale["data"]["warnings"]


def test_cli_stale_without_audit_is_typed_validation(
    tmp_path: Path,
    isolated_state: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = tmp_path / "workspaces.yaml"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    isolated_state.mkdir()
    registry.write_text(
        f"workspaces:\n  {workspace}:\n    kb: {isolated_state}\n    project: alpha\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EOS_KB_REGISTRY", str(registry))
    monkeypatch.chdir(workspace)

    assert main(["stale", "--json"]) == ExitCode.VALIDATION
    payload = json.loads(capsys.readouterr().err)
    assert payload["error"] == {
        "code": "freshness.state_unavailable",
        "field_path": "$.freshness",
    }
