from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from eos_kb.cli import ExitCode, main
from eos_kb.indexer import index_bundle
from eos_kb.retrieval import (
    RetrievalValidationError,
    context,
    estimate_units,
    related,
    search,
    show,
    status,
)
from eos_kb.storage import SCHEMA_VERSION, state_directory


def _write(root: Path, relative: str, **fields: object) -> None:
    body = str(fields.pop("body"))
    values = {"type": "Decision", "title": relative, "resource": f"kb:test/{relative}", **fields}
    lines = ["---"]
    for key, value in values.items():
        lines.append(f"{key}: {json.dumps(value)}")
    lines.extend(["---", body])
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _fixed_package_units(
    *, query: str, warnings: tuple[str, ...], cards: list[dict[str, object]]
) -> int:
    units = 0
    while True:
        payload = {
            "query": query,
            "budget": units,
            "estimated_units": units,
            "estimator": "utf8-bytes-div-2-ceil",
            "warnings_reserved": True,
            "warnings": list(warnings),
            "cards": cards,
        }
        measured = estimate_units(_canonical_json(payload))
        if measured == units:
            return units
        units = measured


@pytest.fixture
def retrieval_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))
    root = tmp_path / "knowledge"
    _write(
        root,
        "projects/nova/error.md",
        title="Booking Family Status",
        body="# Overview\nThe exact error ERR_FAMILY_SPLIT occurs in `resolve_family()` when NOVA-123 is retried.\n\n## Usage\nUse --include-draft with path domains/identity.py.\n\n## Unresolved Questions\nWhich retry owner closes the incident?",
        tags=["booking", "family"],
        sources=["runbook://booking-family"],
        status="stable",
        verified=[{"check": "pytest", "result": "passed"}],
        eos={"project": "backend-project", "components": ["identity"], "symptoms": ["family-split"], "source_paths": ["domains/identity.py"], "source_revision": "abc123", "supersedes": ["kb:test/projects/nova/old.md"], "claims": [{"id": "family.mode", "value": "current"}]},
    )
    _write(
        root,
        "projects/nova/linked.md",
        title="Family Retry Runbook",
        body="# Runbook\nA resilient retry procedure repairs the family resolver after the error.\n[status](error.md)",
        tags=["retry"],
        eos={"project": "backend-project", "components": ["identity"], "symptoms": ["retry-loop"]},
    )
    _write(root, "projects/nova/draft.md", title="Draft Identity Note", body="# Draft\nexperimental", status="draft")
    _write(root, "projects/nova/log.md", type="Session Log", title="Session", body="# Log\nsecret")
    _write(root, "projects/nova/proposal.md", type="Knowledge Proposal", title="Proposal", body="# Proposal\nproposal")
    _write(root, "projects/nova/old.md", title="Old Family", body="# Old\nlegacy", status="deprecated", eos={"claims": [{"id": "family.mode", "value": "legacy"}]})
    index_bundle(root)
    return root


@pytest.mark.parametrize("term", ["ERR_FAMILY_SPLIT", "resolve_family", "domains/identity.py", "NOVA-123", "--include-draft", "Booking Family Status", "family", "identity", "family-split", "kb:test/projects/nova/error.md"])
def test_search_matches_exact_metadata_terms(retrieval_bundle: Path, term: str) -> None:
    results = search(retrieval_bundle, term)
    assert results
    assert results[0].resource == "kb:test/projects/nova/error.md"
    assert results[0].reasons


def test_search_uses_bm25_and_one_hop_graph_expansion(retrieval_bundle: Path) -> None:
    lexical = search(retrieval_bundle, "resilient procedure")
    assert lexical[0].title == "Family Retry Runbook"
    expanded = search(retrieval_bundle, "ERR_FAMILY_SPLIT")
    assert [card.title for card in expanded] == ["Booking Family Status", "Family Retry Runbook"]
    assert expanded[1].graph_distance == 1


def test_bm25_term_frequency_breaks_resource_order_tie(retrieval_bundle: Path) -> None:
    _write(
        retrieval_bundle,
        "areas/single.md",
        title="Single Occurrence",
        resource="kb:test/a-single",
        body="# Note\nquasar",
    )
    _write(
        retrieval_bundle,
        "areas/repeated.md",
        title="Repeated Occurrence",
        resource="kb:test/z-repeated",
        body="# Note\nquasar quasar quasar quasar quasar quasar quasar quasar",
    )
    index_bundle(retrieval_bundle, rebuild=True)

    results = search(retrieval_bundle, "quasar")

    assert [card.resource for card in results[:2]] == [
        "kb:test/z-repeated",
        "kb:test/a-single",
    ]
    assert results[0].reasons == ("BM25 lexical text",)


def test_fts_query_quotes_operators_and_punctuation_safely(retrieval_bundle: Path) -> None:
    _write(
        retrieval_bundle,
        "areas/punctuation.md",
        title="Punctuation",
        resource="kb:test/punctuation",
        body="# Note\nquasar x:y odd",
    )
    index_bundle(retrieval_bundle, rebuild=True)

    results = search(retrieval_bundle, '\"quasar\" OR NOT (x:y) --odd')

    assert results
    assert results[0].resource == "kb:test/punctuation"


def test_source_path_frontmatter_is_ranked_as_exact_path_metadata(retrieval_bundle: Path) -> None:
    _write(
        retrieval_bundle,
        "areas/source-only.md",
        title="Opaque Loader",
        resource="kb:test/source-only",
        body="# Note\nNo implementation path is repeated here.",
        eos={"source_paths": ["services/private/opaque_loader.py"]},
    )
    index_bundle(retrieval_bundle, rebuild=True)

    results = search(retrieval_bundle, "services/private/opaque_loader.py")

    assert results[0].resource == "kb:test/source-only"
    assert "exact source_path" in results[0].reasons


def test_lifecycle_filters_and_truthful_labels(retrieval_bundle: Path) -> None:
    default = {card.title for card in search(retrieval_bundle, "family")}
    assert "Draft Identity Note" not in default
    assert "Session" not in default
    assert "Proposal" not in default
    assert "Old Family" not in default
    assert "Booking Family Status" in default
    assert search(retrieval_bundle, "family", include_draft=True, include_deprecated=True)
    card = search(retrieval_bundle, "family")[0]
    assert card.trust == "unverified"
    assert card.freshness == "unknown"
    assert card.authority_label == "unverified"
    assert "Old Family" in {card.title for card in search(retrieval_bundle, "family history")}


def test_explicit_status_filter_includes_non_default_lifecycle(
    retrieval_bundle: Path,
) -> None:
    assert [card.title for card in search(retrieval_bundle, "experimental", status="draft")] == [
        "Draft Identity Note"
    ]
    assert [card.title for card in search(retrieval_bundle, "legacy", status="deprecated")] == [
        "Old Family"
    ]


def test_deterministic_ties_use_canonical_resource(retrieval_bundle: Path) -> None:
    first = [card.resource for card in search(retrieval_bundle, "family", limit=20)]
    second = [card.resource for card in search(retrieval_bundle, "family", limit=20)]
    assert first == second


def test_show_resolves_resource_path_and_exact_section(retrieval_bundle: Path) -> None:
    card = show(retrieval_bundle, "projects/nova/error.md", section="Usage")
    assert card.excerpt == "## Usage\nUse --include-draft with path domains/identity.py."
    resource = show(retrieval_bundle, "kb:test/projects/nova/error.md")
    assert resource.relative_file == "projects/nova/error.md"


def test_show_rejects_indexed_path_outside_kb(
    retrieval_bundle: Path,
    tmp_path: Path,
) -> None:
    secret = tmp_path / "secret.md"
    secret.write_text("outside", encoding="utf-8")
    database = state_directory(retrieval_bundle) / "index.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE concepts SET relative_file = ?, resource = ? WHERE title = ?",
        ("../secret.md", "kb:test/outside", "Booking Family Status"),
    )
    connection.commit()
    connection.close()

    with pytest.raises(RetrievalValidationError) as raised:
        show(retrieval_bundle, "kb:test/outside")
    assert raised.value.code == "show.path_outside_kb"


def test_related_is_one_hop_forward_and_reverse_and_reports_ambiguous(retrieval_bundle: Path) -> None:
    assert [card.relative_file for card in related(retrieval_bundle, "projects/nova/error.md")] == ["projects/nova/linked.md"]
    with pytest.raises(ValueError, match="ambiguous"):
        related(retrieval_bundle, "nova")


def test_context_reserves_warnings_and_omits_incomplete_next_card(retrieval_bundle: Path) -> None:
    result = context(retrieval_bundle, "family", budget=2500)
    assert result.estimated_units <= 2500
    assert result.estimator == "utf8-bytes-div-2-ceil"
    assert result.warnings_reserved is True
    warning_units = estimate_units("\n".join(result.warnings))
    with pytest.raises(ValueError, match="context budget too small"):
        context(retrieval_bundle, "family", budget=warning_units - 1)


def test_context_estimate_equals_complete_warning_and_card_envelope(retrieval_bundle: Path) -> None:
    result = context(retrieval_bundle, "family", budget=2500)
    package = _canonical_json(result.as_dict())
    assert result.estimated_units == estimate_units(package)
    assert result.estimated_units <= result.budget

    exact_first_budget = _fixed_package_units(
        query="family",
        warnings=result.warnings,
        cards=[result.cards[0].as_dict()],
    )
    bounded = context(retrieval_bundle, "family", budget=exact_first_budget)
    assert len(bounded.cards) == 1
    assert bounded.estimated_units == exact_first_budget
    assert estimate_units(_canonical_json(bounded.as_dict())) == exact_first_budget


def test_context_rejects_budget_below_base_package_and_warnings(retrieval_bundle: Path) -> None:
    with pytest.raises(ValueError, match="context budget too small") as raised:
        context(retrieval_bundle, "family", budget=1)
    assert getattr(raised.value, "code") == "context.budget_too_small"
    assert getattr(raised.value, "field_path") == "$.budget"


def test_context_cards_include_selected_content_and_indexed_metadata(retrieval_bundle: Path) -> None:
    result = context(retrieval_bundle, "ERR_FAMILY_SPLIT", budget=2500)
    card = result.cards[0]
    assert card.section == "Overview"
    assert "ERR_FAMILY_SPLIT" in card.excerpt
    assert card.sources == ("runbook://booking-family",)
    assert card.source_paths == ("domains/identity.py",)
    assert card.source_revision == "abc123"
    assert "kb:test/projects/nova/old.md" in card.supersession_refs
    assert "kb:test/projects/nova/old.md" in card.contradiction_refs
    assert "retry owner" in card.unresolved_questions
    assert "contradiction: kb:test/projects/nova/old.md" in result.warnings


def test_context_omits_next_populated_card_without_truncating(retrieval_bundle: Path) -> None:
    full = context(retrieval_bundle, "family", budget=2500)
    one_card_budget = _fixed_package_units(
        query="family",
        warnings=full.warnings,
        cards=[full.cards[0].as_dict()],
    )
    bounded = context(retrieval_bundle, "family", budget=one_card_budget)
    assert len(bounded.cards) == 1
    assert bounded.cards[0].excerpt == full.cards[0].excerpt


def test_context_cli_rejects_budget_smaller_than_mandatory_warnings(
    retrieval_bundle: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = context(retrieval_bundle, "family", budget=2500)
    warning_units = estimate_units("\n".join(result.warnings))

    exit_code = main([
        "context",
        "family",
        "--budget",
        str(warning_units - 1),
        "--kb",
        str(retrieval_bundle),
        "--json",
    ])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.VALIDATION
    assert captured.out == ""
    payload = json.loads(captured.err)
    assert payload["error"] == {
        "code": "context.budget_too_small",
        "field_path": "$.budget",
    }


def test_status_is_stable_and_structural(retrieval_bundle: Path) -> None:
    first = status(retrieval_bundle)
    second = status(retrieval_bundle)
    assert first == second
    assert first["schema_version"] >= 2
    assert first["bundle"]["concepts"] == 6
    assert "missing" in first["state"]


def test_status_reports_corrupt_external_state_without_mutating_it(retrieval_bundle: Path) -> None:
    state = state_directory(retrieval_bundle)
    (state / "index.sqlite3").write_bytes(b"not sqlite")
    result = status(retrieval_bundle)
    assert result["state"]["corrupt"] == ["database"]


def test_retrieval_rejects_structurally_incomplete_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))
    root = tmp_path / "knowledge"
    root.mkdir()
    state = state_directory(root)
    state.mkdir(parents=True)
    connection = sqlite3.connect(state / "index.sqlite3")
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
    connection.close()

    with pytest.raises(RetrievalValidationError) as raised:
        search(root, "anything")
    assert raised.value.code == "retrieval.index_corrupt"

    assert main(["search", "anything", "--kb", str(root), "--json"]) == ExitCode.VALIDATION
    payload = json.loads(capsys.readouterr().err)
    assert payload["error"] == {
        "code": "retrieval.index_corrupt",
        "field_path": "$.index",
    }


def test_retrieval_rejects_required_tables_with_invalid_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))
    root = tmp_path / "knowledge"
    root.mkdir()
    state = state_directory(root)
    state.mkdir(parents=True)
    connection = sqlite3.connect(state / "index.sqlite3")
    for table in (
        "claims",
        "concepts",
        "concepts_fts",
        "headings",
        "links",
        "reverse_links",
        "sources",
        "supersession",
    ):
        connection.execute(f'CREATE TABLE "{table}" (wrong_column TEXT)')
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
    connection.close()

    with pytest.raises(RetrievalValidationError) as raised:
        search(root, "anything")
    assert raised.value.code == "retrieval.index_corrupt"
    assert status(root)["state"]["corrupt"] == ["database"]


def test_retrieval_rejects_non_fts_table_with_matching_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))
    root = tmp_path / "knowledge"
    _write(root, "note.md", title="Note", body="# Note\ncontent")
    index_bundle(root)
    database = state_directory(root) / "index.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("DROP TABLE concepts_fts")
    connection.execute("CREATE TABLE concepts_fts (relative_file, text)")
    connection.commit()
    connection.close()

    with pytest.raises(RetrievalValidationError) as raised:
        search(root, "content")
    assert raised.value.code == "retrieval.index_corrupt"
    assert status(root)["state"]["corrupt"] == ["database"]


def test_status_rejects_valid_json_with_invalid_manifest_shape(
    retrieval_bundle: Path,
) -> None:
    manifest = state_directory(retrieval_bundle) / "manifest.json"
    manifest.write_text('{"schema_version": 99}', encoding="utf-8")

    result = status(retrieval_bundle)

    assert result["state"]["corrupt"] == ["manifest"]


def test_cli_retrieval_uses_workspace_project_and_allows_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    root = tmp_path / "knowledge"
    _write(root, "projects/alpha/note.md", title="Alpha", resource="kb:test/alpha", body="# Note\nsharedterm", eos={"project": "alpha"})
    _write(root, "projects/beta/note.md", title="Beta", resource="kb:test/beta", body="# Note\nsharedterm", eos={"project": "beta"})
    index_bundle(root)
    registry = tmp_path / "workspaces.yaml"
    registry.write_text(
        f"workspaces:\n  {workspace}:\n    kb: {root}\n    project: alpha\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EOS_KB_REGISTRY", str(registry))
    monkeypatch.chdir(workspace)

    assert main(["search", "sharedterm", "--json"]) == ExitCode.SUCCESS
    default_search = json.loads(capsys.readouterr().out)
    assert [card["resource"] for card in default_search["data"]] == ["kb:test/alpha"]

    assert main(["search", "sharedterm", "--project", "beta", "--json"]) == ExitCode.SUCCESS
    override_search = json.loads(capsys.readouterr().out)
    assert [card["resource"] for card in override_search["data"]] == ["kb:test/beta"]

    assert main(["context", "sharedterm", "--budget", "2500", "--json"]) == ExitCode.SUCCESS
    default_context = json.loads(capsys.readouterr().out)
    assert [card["resource"] for card in default_context["data"]["cards"]] == ["kb:test/alpha"]


def test_cli_explicit_shared_kb_uses_project_from_current_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    eos_workspace = tmp_path / "eos"
    genesis_workspace = tmp_path / "genesis"
    eos_workspace.mkdir()
    genesis_workspace.mkdir()
    root = tmp_path / "knowledge"
    _write(root, "projects/eos/note.md", title="EOS", resource="kb:test/eos", body="# Note\nsharedterm", eos={"project": "eos"})
    _write(root, "projects/genesis/note.md", title="research project", resource="kb:test/genesis", body="# Note\nsharedterm", eos={"project": "nlp-to-llm-evolution"})
    index_bundle(root)
    registry = tmp_path / "workspaces.yaml"
    registry.write_text(
        "workspaces:\n"
        f"  {eos_workspace}:\n    kb: {root}\n    project: eos\n"
        f"  {genesis_workspace}:\n    kb: {root}\n    project: nlp-to-llm-evolution\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EOS_KB_REGISTRY", str(registry))

    monkeypatch.chdir(eos_workspace)
    assert main(["search", "sharedterm", "--kb", str(root), "--json"]) == ExitCode.SUCCESS
    eos = json.loads(capsys.readouterr().out)

    monkeypatch.chdir(genesis_workspace)
    assert main(["search", "sharedterm", "--kb", str(root), "--json"]) == ExitCode.SUCCESS
    genesis = json.loads(capsys.readouterr().out)

    assert [card["resource"] for card in eos["data"]] == ["kb:test/eos"]
    assert [card["resource"] for card in genesis["data"]] == ["kb:test/genesis"]


def test_cli_explicit_unregistered_kb_does_not_invent_project_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registered_workspace = tmp_path / "registered"
    registered_workspace.mkdir()
    registered_kb = tmp_path / "registered-knowledge"
    registered_kb.mkdir()
    standalone_kb = tmp_path / "standalone-knowledge"
    _write(
        standalone_kb,
        "projects/alpha/note.md",
        title="Alpha",
        resource="kb:test/alpha",
        body="# Note\nsharedterm",
        eos={"project": "alpha"},
    )
    index_bundle(standalone_kb)
    registry = tmp_path / "workspaces.yaml"
    registry.write_text(
        f"workspaces:\n  {registered_workspace}:\n    kb: {registered_kb}\n    project: registered\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EOS_KB_REGISTRY", str(registry))

    assert main(["search", "sharedterm", "--kb", str(standalone_kb), "--json"]) == ExitCode.SUCCESS
    payload = json.loads(capsys.readouterr().out)
    assert [card["resource"] for card in payload["data"]] == ["kb:test/alpha"]


def test_cli_status_returns_degraded_for_missing_and_corrupt_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    external = state_directory(root)
    assert not external.exists()

    assert main(["status", "--kb", str(root)]) == ExitCode.VALIDATION
    missing_text = capsys.readouterr()
    assert missing_text.out == ""
    assert missing_text.err == "error[status.degraded]: knowledge index degraded: missing database, manifest\n"
    assert not external.exists()

    _write(root, "note.md", title="Note", body="# Note\ncontent")
    index_bundle(root)
    (external / "manifest.json").write_text("not json", encoding="utf-8")
    assert main(["status", "--kb", str(root), "--json"]) == ExitCode.VALIDATION
    corrupt_json = json.loads(capsys.readouterr().err)
    assert corrupt_json["status"] == "degraded"
    assert corrupt_json["error"] == {"code": "status.degraded", "field_path": "$.state"}
    assert corrupt_json["data"]["state"]["corrupt"] == ["manifest"]


def test_archive_and_internal_content_classes_require_explicit_intent(retrieval_bundle: Path) -> None:
    _write(retrieval_bundle, "archive/legacy.md", type="Reference", title="Archived Legacy", body="# Legacy\narchive-keyword")
    index_bundle(retrieval_bundle, rebuild=True)

    assert search(retrieval_bundle, "archive-keyword") == []
    assert search(retrieval_bundle, "secret", include_draft=True) == []
    assert search(retrieval_bundle, "proposal", include_draft=True) == []
    assert search(retrieval_bundle, "archive-keyword history")[0].title == "Archived Legacy"
    assert search(retrieval_bundle, "archive-keyword", types=["Reference"])[0].title == "Archived Legacy"
    assert search(retrieval_bundle, "secret", types=["Session Log"])[0].title == "Session"
    assert search(retrieval_bundle, "proposal", types=["Knowledge Proposal"])[0].title == "Proposal"


def test_component_filter_is_enforced_by_api_and_cli(
    retrieval_bundle: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    api = search(retrieval_bundle, "family", components=["identity"])
    assert api
    assert all("identity" in card.components for card in api)

    assert main(["search", "family", "--component", "identity", "--project", "backend-project", "--kb", str(retrieval_bundle), "--json"]) == ExitCode.SUCCESS
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]
    assert all("identity" in card["components"] for card in payload["data"])


def test_included_lifecycle_results_receive_deterministic_penalties(retrieval_bundle: Path) -> None:
    for name, resource, status_value in (
        ("stable", "kb:test/z-stable", "stable"),
        ("machine", "kb:test/a-machine", "stable"),
        ("draft", "kb:test/a-draft", "draft"),
        ("stale", "kb:test/a-stale", "stable"),
        ("deprecated", "kb:test/a-deprecated", "deprecated"),
    ):
        _write(retrieval_bundle, f"areas/{name}.md", title=name, resource=resource, status=status_value, body="# Note\npenaltytoken")
    report = index_bundle(retrieval_bundle, rebuild=True)
    report.connection.execute("UPDATE concepts SET trust = 'machine-confirmed' WHERE resource = 'kb:test/a-machine'")
    report.connection.execute("UPDATE concepts SET freshness = 'stale' WHERE resource = 'kb:test/a-stale'")
    report.connection.commit()

    cards = search(retrieval_bundle, "penaltytoken", include_draft=True, include_deprecated=True)
    assert [card.resource for card in cards[:5]] == [
        "kb:test/z-stable",
        "kb:test/a-machine",
        "kb:test/a-draft",
        "kb:test/a-stale",
        "kb:test/a-deprecated",
    ]
    assert cards[0].score > cards[1].score > cards[2].score > cards[3].score > cards[4].score
