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
from eos_kb.gate import (
    GateError,
    ensure_gate_activation,
    latest_review_event,
    record_review_event,
    require_gate,
)
from eos_kb.indexer import index_bundle, validate_bundle
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
    freshness: str | None = None,
    review_every: str | None = None,
    reviewed_at: str | None = None,
    status: str = "stable",
    concept_type: str = "Decision",
    claims: tuple[tuple[str, object], ...] = (),
    sources: tuple[str, ...] = (),
    verified: tuple[dict[str, object], ...] = (),
    body: str = "# Note\nDocumented behavior.",
) -> None:
    metadata: dict[str, object] = {
        "type": concept_type,
        "title": Path(relative).stem,
        "resource": resource,
        "status": status,
    }
    if stale_after is not None:
        metadata["stale_after"] = stale_after
    if freshness is not None:
        metadata["freshness"] = freshness
    if review_every is not None:
        metadata["review_every"] = review_every
    if reviewed_at is not None:
        metadata["reviewed_at"] = reviewed_at
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


def _indexed_content_hash(kb: Path, relative: str) -> str:
    manifest = json.loads((state_directory(kb) / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["concepts"]:
        if item["path"] == relative:
            return item["content_hash"]
    raise AssertionError(f"{relative} is not indexed")


def _record_linked_review(
    kb: Path,
    target: str,
    content_hash: str,
    reviewed_at: str,
    *,
    proposal_id: str = "proposal-1",
    session_id: str = "session-1",
) -> None:
    """Write an accepted approval plus its review event, as promote would.

    Review events only count when linked to an accepted approval for the
    same proposal id and content hash, so tests must write both halves.
    """
    approvals = kb / ".eos" / "approvals.jsonl"
    approvals.parent.mkdir(parents=True, exist_ok=True)
    with approvals.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps({
                "schema_version": 1,
                "proposal_id": proposal_id,
                "actor": "test",
                "timestamp": reviewed_at,
                "proposal_hash": "sha256:" + "0" * 64,
                "base_target_hash": content_hash,
                "proposed_result_hash": content_hash,
                "decision": "accepted",
                "session_id": session_id,
            })
            + "\n"
        )
    record_review_event(
        kb,
        target=target,
        content_hash=content_hash,
        proposal_id=proposal_id,
        session_id=session_id,
        reviewed_at=reviewed_at,
    )


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
    # Indexing activates the durable gate boundary in the KB's own .eos/.
    assert (isolated_state / ".eos" / "freshness-gate.json").is_file()


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
    # The doc is untagged, so its expired stale_after is inert: no time
    # finding at all, and the doc stays advisory unknown, never blocking.
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
    assert fresh_source.time == ()
    assert [(item.resource, item.state) for item in fresh_source.concepts] == [
        ("kb:alpha/external", "fresh")
    ]
    assert fresh_source.overall == "fresh"

    external.write_text("changed", encoding="utf-8")
    changed = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    assert changed.external_sources[0].state == "drifted"
    assert changed.time == ()


def test_a_log_is_a_dated_record_and_never_goes_time_stale(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    _concept(
        isolated_state,
        "logs/2026/old-session.md",
        resource="kb:alpha/old-session",
        stale_after="2026-01-01T00:00:00+00:00",
        concept_type="Log",
    )
    index_bundle(isolated_state)

    report = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    assert report.time == ()
    assert report.overall != "stale"


def test_a_deprecated_concept_is_frozen_and_never_goes_time_stale(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    _concept(
        isolated_state,
        "projects/alpha/retired.md",
        resource="kb:alpha/retired",
        stale_after="2026-01-01T00:00:00+00:00",
        status="deprecated",
    )
    index_bundle(isolated_state)

    report = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    assert report.time == ()
    assert report.overall != "stale"


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
        freshness="tracked",
        review_every="30d",
        body="# Note\ntimetoken",
    )
    index_bundle(isolated_state)
    content_hash = _indexed_content_hash(isolated_state, "time.md")
    _record_linked_review(
        isolated_state,
        target="time.md",
        content_hash=content_hash,
        proposal_id="proposal-1",
        session_id="session-1",
        reviewed_at="2026-01-01T00:00:00+00:00",
    )

    report = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 1, 31),
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


def test_untagged_doc_with_expired_stale_after_stays_unknown_never_blocking(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    # stale_after is inert: an untagged doc with a long-past date reports
    # unknown (advisory) instead of stale, so it can never block.
    repo = _repo(tmp_path)
    _concept(
        isolated_state,
        "legacy.md",
        resource="kb:alpha/legacy",
        stale_after="2026-01-01T00:00:00+00:00",
        body="# Note\nlegacytoken",
    )
    index_bundle(isolated_state)

    report = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    assert report.time == ()
    assert [(item.resource, item.state) for item in report.concepts] == [
        ("kb:alpha/legacy", "unknown")
    ]
    assert "freshness unknown: kb:alpha/legacy" in report.warnings
    assert report.overall == "unknown"


def test_historical_doc_never_unknown_including_deprecated(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    _concept(
        isolated_state,
        "logs/2026/old-session.md",
        resource="kb:alpha/old-session",
        stale_after="2026-01-01T00:00:00+00:00",
        freshness="historical",
        concept_type="Log",
        status="deprecated",
        body="# Note\nsessiontoken",
    )
    index_bundle(isolated_state)

    report = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    assert report.time == ()
    assert [(item.resource, item.state) for item in report.concepts] == [
        ("kb:alpha/old-session", "fresh")
    ]
    assert report.overall == "fresh"
    assert "freshness unknown: kb:alpha/old-session" not in report.warnings
    assert search(isolated_state, "sessiontoken", include_deprecated=True)[0].freshness == "fresh"


def test_historical_conflict_can_still_report_stale(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    # Historical is never *unknown*, but conflicting evidence still reports
    # stale: the contradiction (not expiry) is what blocks.
    repo = _repo(tmp_path)
    _concept(
        isolated_state,
        "a.md",
        resource="kb:alpha/a",
        freshness="historical",
        claims=(("mode", "one"),),
    )
    _concept(
        isolated_state,
        "b.md",
        resource="kb:alpha/b",
        freshness="historical",
        claims=(("mode", "two"),),
    )
    index_bundle(isolated_state)

    report = audit_freshness(isolated_state, repo)

    assert {item.resource: item.state for item in report.concepts} == {
        "kb:alpha/a": "stale",
        "kb:alpha/b": "stale",
    }
    assert len(report.contradictions) == 1


def test_tracked_window_expiry_uses_hash_bound_review_event(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    _concept(
        isolated_state,
        "router.md",
        resource="kb:alpha/router",
        freshness="tracked",
        review_every="30d",
        body="# Note\nroutertoken",
    )
    index_bundle(isolated_state)
    content_hash = _indexed_content_hash(isolated_state, "router.md")
    _record_linked_review(
        isolated_state,
        target="router.md",
        content_hash=content_hash,
        proposal_id="proposal-1",
        session_id="session-1",
        reviewed_at="2026-01-01T00:00:00+00:00",
    )

    expired = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 2, 15, tzinfo=timezone.utc),
    )
    assert expired.time[0].state == "stale"
    assert expired.time[0].stale_after == "2026-01-31T00:00:00+00:00"

    _record_linked_review(
        isolated_state,
        target="router.md",
        content_hash=content_hash,
        proposal_id="proposal-2",
        session_id="session-1",
        reviewed_at="2026-02-01T00:00:00+00:00",
    )
    current = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 2, 15, tzinfo=timezone.utc),
    )
    assert current.time[0].state == "current"


def test_review_event_hash_mismatch_reports_stale(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    # Expiry survives edits: content changed after the review, so the latest
    # event no longer matches and the doc reports stale until re-review,
    # never unknown.
    repo = _repo(tmp_path)
    _concept(
        isolated_state,
        "router.md",
        resource="kb:alpha/router",
        freshness="tracked",
        review_every="30d",
        body="# Note\nroutertoken",
    )
    index_bundle(isolated_state)
    _record_linked_review(
        isolated_state,
        target="router.md",
        content_hash=_indexed_content_hash(isolated_state, "router.md"),
        proposal_id="proposal-1",
        session_id="session-1",
        reviewed_at="2026-01-01T00:00:00+00:00",
    )
    _concept(
        isolated_state,
        "router.md",
        resource="kb:alpha/router",
        freshness="tracked",
        review_every="30d",
        body="# Note\nroutertoken changed",
    )
    index_bundle(isolated_state)

    report = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    assert report.time[0].state == "stale"
    assert report.time[0].stale_after == "2026-01-31T00:00:00+00:00"
    assert report.overall == "stale"


def test_bare_reviewed_at_edit_reports_stale(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    # reviewed_at is informational only and no review event exists: editing it
    # changes the hash without a review, so expiry survives the edit and the
    # doc reports stale instead of an extended window or unknown.
    repo = _repo(tmp_path)
    _concept(
        isolated_state,
        "router.md",
        resource="kb:alpha/router",
        freshness="tracked",
        review_every="30d",
        reviewed_at="2026-01-01T00:00:00+00:00",
        body="# Note\nroutertoken",
    )
    ensure_gate_activation(isolated_state, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    index_bundle(isolated_state)
    _concept(
        isolated_state,
        "router.md",
        resource="kb:alpha/router",
        freshness="tracked",
        review_every="30d",
        reviewed_at="2026-06-01T00:00:00+00:00",
        body="# Note\nroutertoken",
    )
    index_bundle(isolated_state)

    report = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    # No review event exists and the content changed since activation, so
    # the edit cannot lift expiry: the time finding is stale, dated from
    # the activation timestamp plus the window.
    assert report.time[0].state == "stale"
    assert report.time[0].stale_after == "2026-01-31T00:00:00+00:00"
    assert [(item.resource, item.state) for item in report.concepts] == [
        ("kb:alpha/router", "stale")
    ]
    assert report.overall == "stale"


def test_activation_gives_existing_tracked_docs_an_initial_review(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    repo = _repo(tmp_path)
    _concept(
        isolated_state,
        "router.md",
        resource="kb:alpha/router",
        freshness="tracked",
        review_every="30d",
        body="# Note\nroutertoken",
    )
    ensure_gate_activation(isolated_state, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    index_bundle(isolated_state)

    current = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 1, 15, tzinfo=timezone.utc),
    )
    assert current.time[0].state == "current"
    assert current.time[0].stale_after == "2026-01-31T00:00:00+00:00"

    expired = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 2, 15, tzinfo=timezone.utc),
    )
    assert expired.time[0].state == "stale"


def test_stale_after_is_inert_when_window_present(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    # The window wins: a long-past stale_after does not force immediate
    # stale while the window is still current.
    repo = _repo(tmp_path)
    _concept(
        isolated_state,
        "router.md",
        resource="kb:alpha/router",
        freshness="tracked",
        review_every="30d",
        stale_after="2026-01-01T00:00:00+00:00",
        body="# Note\nroutertoken",
    )
    index_bundle(isolated_state)
    _record_linked_review(
        isolated_state,
        target="router.md",
        content_hash=_indexed_content_hash(isolated_state, "router.md"),
        proposal_id="proposal-1",
        session_id="session-1",
        reviewed_at="2026-06-01T00:00:00+00:00",
    )

    report = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 6, 15, tzinfo=timezone.utc),
    )

    assert report.time[0].state == "current"
    assert report.time[0].stale_after == "2026-07-01T00:00:00+00:00"


def test_forged_future_and_unlinked_review_lines_are_rejected(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    # A doc created after activation was never reviewed and has no review
    # events. Forged lines (bad hash, future date, or no linked approval)
    # must not resurrect one: it stays unknown, never stale, never current.
    repo = _repo(tmp_path)
    ensure_gate_activation(isolated_state, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    _concept(
        isolated_state,
        "router.md",
        resource="kb:alpha/router",
        freshness="tracked",
        review_every="30d",
        body="# Note\nroutertoken",
    )
    index_bundle(isolated_state)
    content_hash = _indexed_content_hash(isolated_state, "router.md")
    reviews = isolated_state / ".eos" / "reviews.jsonl"

    def append_event(payload: dict) -> None:
        with reviews.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload) + "\n")

    valid_event = {
        "schema_version": 1,
        "target": "router.md",
        "content_hash": content_hash,
        "reviewed_at": "2026-06-01T00:00:00+00:00",
        "proposal_id": "proposal-1",
        "session_id": "session-1",
    }
    # Malformed hash.
    append_event({**valid_event, "content_hash": "not-a-hash"})
    # Future timestamp, otherwise well-formed and approved below.
    append_event({**valid_event, "reviewed_at": "2999-01-01T00:00:00+00:00"})
    # Well-formed but no accepted approval links it.
    append_event(valid_event)
    assert latest_review_event(
        isolated_state, "router.md", now=datetime(2026, 7, 1, tzinfo=timezone.utc)
    ) is None
    report = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    assert report.time == ()
    assert [item.state for item in report.concepts] == ["unknown"]

    # Linking the valid line to an accepted approval makes it count.
    _record_linked_review(
        isolated_state,
        target="router.md",
        content_hash=content_hash,
        reviewed_at="2026-06-01T00:00:00+00:00",
    )
    assert latest_review_event(
        isolated_state, "router.md", now=datetime(2026, 7, 1, tzinfo=timezone.utc)
    ) == (datetime(2026, 6, 1, tzinfo=timezone.utc), content_hash)
    current = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 6, 15, tzinfo=timezone.utc),
    )
    assert current.time[0].state == "current"


def test_missing_gate_fails_closed(tmp_path: Path, isolated_state: Path) -> None:
    repo = _repo(tmp_path)
    _concept(isolated_state, "a.md", resource="kb:alpha/a")
    index_bundle(isolated_state)
    (isolated_state / ".eos" / "freshness-gate.json").unlink()

    with pytest.raises(FreshnessValidationError) as raised:
        audit_freshness(isolated_state, repo)
    assert raised.value.code == "gate.missing"


def test_corrupt_gate_fails_closed(tmp_path: Path, isolated_state: Path) -> None:
    repo = _repo(tmp_path)
    _concept(isolated_state, "a.md", resource="kb:alpha/a")
    index_bundle(isolated_state)
    (isolated_state / ".eos" / "freshness-gate.json").write_text("{truncated", encoding="utf-8")

    with pytest.raises(FreshnessValidationError) as raised:
        audit_freshness(isolated_state, repo)
    assert raised.value.code == "gate.corrupt"
    with pytest.raises(GateError) as gate_raised:
        require_gate(isolated_state)
    assert gate_raised.value.code == "gate.corrupt"


def test_wrong_version_gate_fails_closed(tmp_path: Path, isolated_state: Path) -> None:
    repo = _repo(tmp_path)
    _concept(isolated_state, "a.md", resource="kb:alpha/a")
    index_bundle(isolated_state)
    gate_path = isolated_state / ".eos" / "freshness-gate.json"
    gate_path.write_text(
        json.dumps({"schema_version": 999, "activated_at": "2026-01-01T00:00:00+00:00", "docs": {}}),
        encoding="utf-8",
    )

    with pytest.raises(FreshnessValidationError) as raised:
        audit_freshness(isolated_state, repo)
    assert raised.value.code == "gate.version_mismatch"


def test_validate_is_read_only_and_refuses_without_gate(
    tmp_path: Path, isolated_state: Path
) -> None:
    _concept(isolated_state, "a.md", resource="kb:alpha/a")
    index_bundle(isolated_state)
    (isolated_state / ".eos" / "freshness-gate.json").unlink()

    report = validate_bundle(isolated_state)

    assert ("gate.missing", "freshness-gate.json") in {(error.code, error.relative_file) for error in report.errors}
    # No silent re-activation: the gate file is still gone.
    assert not (isolated_state / ".eos" / "freshness-gate.json").exists()


def test_edit_after_review_reports_stale_even_within_window(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    # A linked review at T0 with a 30d window is current at T0+10d, but any
    # content edit without re-review forces stale with the same effective
    # date: expiry survives the edit, even inside the window.
    repo = _repo(tmp_path)
    _concept(
        isolated_state,
        "router.md",
        resource="kb:alpha/router",
        freshness="tracked",
        review_every="30d",
        body="# Note\nroutertoken",
    )
    index_bundle(isolated_state)
    _record_linked_review(
        isolated_state,
        target="router.md",
        content_hash=_indexed_content_hash(isolated_state, "router.md"),
        proposal_id="proposal-1",
        session_id="session-1",
        reviewed_at="2026-01-01T00:00:00+00:00",
    )
    _concept(
        isolated_state,
        "router.md",
        resource="kb:alpha/router",
        freshness="tracked",
        review_every="30d",
        body="# Note\nroutertoken edited",
    )
    index_bundle(isolated_state)

    report = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 1, 10, tzinfo=timezone.utc),
    )

    assert report.time[0].state == "stale"
    assert report.time[0].stale_after == "2026-01-31T00:00:00+00:00"
    assert report.overall == "stale"


def test_unreindexed_edit_counts_as_edited_since_review(
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    # The audit hashes tracked docs from disk, not the index manifest: an
    # edit without reindex still mismatches the review event and reports
    # stale. Under manifest-hash logic this would wrongly stay current.
    repo = _repo(tmp_path)
    _concept(
        isolated_state,
        "router.md",
        resource="kb:alpha/router",
        freshness="tracked",
        review_every="30d",
        body="# Note\nroutertoken",
    )
    index_bundle(isolated_state)
    _record_linked_review(
        isolated_state,
        target="router.md",
        content_hash=_indexed_content_hash(isolated_state, "router.md"),
        proposal_id="proposal-1",
        session_id="session-1",
        reviewed_at="2026-01-01T00:00:00+00:00",
    )
    (isolated_state / "router.md").write_text(
        (isolated_state / "router.md").read_text(encoding="utf-8") + "\n# extra\n",
        encoding="utf-8",
    )

    report = audit_freshness(
        isolated_state,
        repo,
        now=datetime(2026, 1, 10, tzinfo=timezone.utc),
    )

    assert report.time[0].state == "stale"
    assert report.overall == "stale"


def test_missing_review_ledger_fails_closed(tmp_path: Path, isolated_state: Path) -> None:
    repo = _repo(tmp_path)
    _concept(
        isolated_state,
        "router.md",
        resource="kb:alpha/router",
        freshness="tracked",
        review_every="30d",
        body="# Note\nroutertoken",
    )
    index_bundle(isolated_state)
    _record_linked_review(
        isolated_state,
        target="router.md",
        content_hash=_indexed_content_hash(isolated_state, "router.md"),
        proposal_id="proposal-1",
        session_id="session-1",
        reviewed_at="2026-01-01T00:00:00+00:00",
    )
    (isolated_state / ".eos" / "reviews.jsonl").unlink()

    with pytest.raises(FreshnessValidationError) as raised:
        audit_freshness(isolated_state, repo)
    assert raised.value.code == "reviews.missing"


def test_missing_approvals_ledger_fails_closed(tmp_path: Path, isolated_state: Path) -> None:
    repo = _repo(tmp_path)
    _concept(
        isolated_state,
        "router.md",
        resource="kb:alpha/router",
        freshness="tracked",
        review_every="30d",
        body="# Note\nroutertoken",
    )
    index_bundle(isolated_state)
    _record_linked_review(
        isolated_state,
        target="router.md",
        content_hash=_indexed_content_hash(isolated_state, "router.md"),
        proposal_id="proposal-1",
        session_id="session-1",
        reviewed_at="2026-01-01T00:00:00+00:00",
    )
    (isolated_state / ".eos" / "approvals.jsonl").unlink()

    with pytest.raises(FreshnessValidationError) as raised:
        audit_freshness(isolated_state, repo)
    assert raised.value.code == "approvals.missing"


def test_unreadable_review_ledger_fails_closed(tmp_path: Path, isolated_state: Path) -> None:
    repo = _repo(tmp_path)
    _concept(
        isolated_state,
        "router.md",
        resource="kb:alpha/router",
        freshness="tracked",
        review_every="30d",
        body="# Note\nroutertoken",
    )
    index_bundle(isolated_state)
    _record_linked_review(
        isolated_state,
        target="router.md",
        content_hash=_indexed_content_hash(isolated_state, "router.md"),
        proposal_id="proposal-1",
        session_id="session-1",
        reviewed_at="2026-01-01T00:00:00+00:00",
    )
    ledger = isolated_state / ".eos" / "reviews.jsonl"
    ledger.unlink()
    ledger.mkdir()

    with pytest.raises(FreshnessValidationError) as raised:
        audit_freshness(isolated_state, repo)
    assert raised.value.code == "reviews.unreadable"
