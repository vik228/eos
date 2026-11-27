from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from eos_kb.governance import (
    GovernanceError,
    ProposalState,
    capture_proposal,
    load_proposal,
    promote_proposal,
    review_direct_change,
    review_proposal,
    transition,
)
from eos_kb.indexer import index_bundle, validate_bundle, valid_manifest
from eos_kb.storage import StorageError, state_directory


ALLOWED_TRANSITIONS = {
    (ProposalState.CAPTURED, ProposalState.READY_FOR_REVIEW),
    (ProposalState.READY_FOR_REVIEW, ProposalState.ACCEPTED),
    (ProposalState.READY_FOR_REVIEW, ProposalState.REJECTED),
    (ProposalState.READY_FOR_REVIEW, ProposalState.SUPERSEDED),
    (ProposalState.ACCEPTED, ProposalState.PROMOTED),
    (ProposalState.ACCEPTED, ProposalState.SUPERSEDED),
}


@pytest.fixture(autouse=True)
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))


def _session(root: Path, session_id: str, *, parent: str | None = None) -> None:
    path = state_directory(root) / "sessions" / f"{session_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "session_id": session_id, "parent_session_id": parent, "state": "active"}, sort_keys=True), encoding="utf-8")


def _proposal_input(path: Path, result_content: str) -> None:
    path.write_text("schema_version: 1\nsummary: Record durable behavior\nevidence: [tests/test_service.py]\nsource_paths: [src/service.py]\nconfidence: high\nknown_gaps: []\nsuggested_freshness: {stale_after: '2027-01-01T00:00:00Z'}\nconflicts: []\nresult_content: " + json.dumps(result_content) + "\n", encoding="utf-8")


def test_state_machine_allows_only_declared_transitions() -> None:
    for source in ProposalState:
        for target in ProposalState:
            if (source, target) in ALLOWED_TRANSITIONS:
                assert transition(source, target) is target
            else:
                with pytest.raises(GovernanceError) as raised:
                    transition(source, target)
                assert raised.value.code == "governance.transition_invalid"


def test_capture_review_and_promote_are_hash_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    _session(root, "parent")
    index_bundle(root)
    proposal_file = tmp_path / "proposal.yaml"
    result = "---\ntype: Decision\ntitle: Service\nresource: kb:demo/service\nfreshness: historical\n---\n# Service\nCurrent behavior.\n"
    _proposal_input(proposal_file, result)
    proposal = capture_proposal(root, target="projects/demo/service.md", proposal_file=proposal_file, session_id="parent")
    assert load_proposal(root, proposal.proposal_id) == proposal
    assert proposal.state is ProposalState.READY_FOR_REVIEW
    assert proposal.base_target_hash is None
    assert proposal.proposed_result_hash.startswith("sha256:")
    assert proposal.proposal_hash.startswith("sha256:")
    reviewed = review_proposal(root, proposal.proposal_id, actor="Vikas", session_id="parent", decision="accepted")
    assert reviewed.proposal_hash == proposal.proposal_hash
    source_root = tmp_path / "source"
    source_root.mkdir()
    coverage = (SimpleNamespace(paths=("src/*.py",), concepts=("kb:demo/service",), ignore=()),)
    observed: dict[str, object] = {}
    real_index_bundle = index_bundle

    def observe_index(*args: object, **kwargs: object):
        observed.update(kwargs)
        return real_index_bundle(*args, **kwargs)

    monkeypatch.setattr("eos_kb.governance.index_bundle", observe_index)
    assert promote_proposal(
        root,
        proposal.proposal_id,
        session_id="parent",
        source_root=source_root,
        coverage_rules=coverage,
    ).state is ProposalState.PROMOTED
    assert observed["source_root"] == source_root
    assert observed["coverage_rules"] == coverage

    state = state_directory(root)
    manifest = json.loads((state / "manifest.json").read_text(encoding="utf-8"))
    assert valid_manifest(manifest)
    assert {item["path"] for item in manifest["concepts"]} == {"projects/demo/service.md"}


def test_direct_change_approval_is_bound_to_exact_current_hash(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    _session(root, "parent")
    target = root / "concept.md"
    target.write_text(
        "---\ntype: Decision\ntitle: Concept\nresource: kb:concept\n---\nOriginal\n",
        encoding="utf-8",
    )
    index_bundle(root)

    target.write_text(
        "---\ntype: Decision\ntitle: Concept\nresource: kb:concept\n---\nApproved edit\n",
        encoding="utf-8",
    )
    before_review = validate_bundle(root, strict=True)
    assert "unreviewed_direct_change" in {error.code for error in before_review.errors}

    approval = review_direct_change(root, "concept.md", actor="Vikas", session_id="parent")
    assert approval["base_target_hash"] == approval["proposed_result_hash"]
    after_review = validate_bundle(root, strict=True)
    assert "unreviewed_direct_change" not in {error.code for error in after_review.errors}

    target.write_text(
        "---\ntype: Decision\ntitle: Concept\nresource: kb:concept\n---\nChanged again\n",
        encoding="utf-8",
    )
    changed_again = validate_bundle(root, strict=True)
    assert "unreviewed_direct_change" in {error.code for error in changed_again.errors}


def test_promotion_failure_restores_source_proposal_and_derived_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "knowledge"
    target = root / "projects/demo/service.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        "---\ntype: Decision\ntitle: Service\nresource: kb:demo/service\n---\nOriginal\n",
        encoding="utf-8",
    )
    _session(root, "parent")
    initial = index_bundle(root)
    initial.connection.close()
    router = root / "projects/demo/index.md"
    proposal_file = tmp_path / "proposal.yaml"
    _proposal_input(
        proposal_file,
        "---\ntype: Decision\ntitle: Service\nresource: kb:demo/service\n---\nUpdated\n",
    )
    proposal = capture_proposal(root, target="projects/demo/service.md", proposal_file=proposal_file, session_id="parent")
    review_proposal(root, proposal.proposal_id, actor="Vikas", session_id="parent", decision="accepted")
    state = state_directory(root)
    proposal_path = root / ".eos" / "proposals" / f"{proposal.proposal_id}.json"
    before = {
        path: path.read_bytes()
        for path in (target, proposal_path, state / "index.sqlite3", state / "manifest.json", router)
    }

    from eos_kb.storage import transactional_replace as real_transactional_replace

    def fail_after_partial_swap(replacements: dict[Path, Path], **kwargs: object) -> None:
        real_transactional_replace(replacements, **kwargs, simulate_failure_after=2)

    monkeypatch.setattr("eos_kb.governance.transactional_replace", fail_after_partial_swap)
    with pytest.raises(StorageError, match="storage.promotion_failed"):
        promote_proposal(root, proposal.proposal_id, session_id="parent")

    assert {path: path.read_bytes() for path in before} == before
    assert load_proposal(root, proposal.proposal_id).state is ProposalState.ACCEPTED


def test_changed_proposal_is_rejected_at_review(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    _session(root, "parent")
    proposal_file = tmp_path / "proposal.yaml"
    _proposal_input(proposal_file, "new\n")
    proposal = capture_proposal(root, target="concept.md", proposal_file=proposal_file, session_id="parent")
    stored = root / ".eos" / "proposals" / f"{proposal.proposal_id}.json"
    payload = json.loads(stored.read_text())
    payload["summary"] = "tampered"
    stored.write_text(json.dumps(payload, sort_keys=True))
    with pytest.raises(GovernanceError, match="proposal_hash_mismatch"):
        review_proposal(root, proposal.proposal_id, actor="Vikas", session_id="parent", decision="accepted")


def test_child_session_cannot_promote(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    _session(root, "child", parent="parent")
    proposal_file = tmp_path / "proposal.yaml"
    _proposal_input(proposal_file, "new\n")
    proposal = capture_proposal(root, target="concept.md", proposal_file=proposal_file, session_id="child")
    review_proposal(root, proposal.proposal_id, actor="Vikas", session_id="child", decision="accepted")
    with pytest.raises(GovernanceError) as raised:
        promote_proposal(root, proposal.proposal_id, session_id="child")
    assert raised.value.code == "governance.child_session_forbidden"


def test_missing_session_error_names_the_recovery_command(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    proposal_file = tmp_path / "proposal.yaml"
    _proposal_input(proposal_file, "new\n")
    with pytest.raises(GovernanceError) as raised:
        capture_proposal(root, target="concept.md", proposal_file=proposal_file, session_id="ghost")
    assert raised.value.code == "governance.session_missing"
    assert "kb session start" in raised.value.message
    assert "--kb" in raised.value.message
    assert "--cwd" in raised.value.message
    assert "--agent" in raised.value.message
    assert "--profile" in raised.value.message


def test_proposal_yaml_error_carries_parser_detail(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    _session(root, "parent")
    proposal_file = tmp_path / "proposal.yaml"
    proposal_file.write_text("summary: [unclosed\n  bad indent: : :\n", encoding="utf-8")
    with pytest.raises(GovernanceError) as raised:
        capture_proposal(root, target="concept.md", proposal_file=proposal_file, session_id="parent")
    assert raised.value.code == "governance.proposal_invalid"
    assert raised.value.message != "Proposal input is not valid YAML."
    assert "line" in raised.value.message or "column" in raised.value.message


def test_proposal_unreadable_file_carries_os_error(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    _session(root, "parent")
    with pytest.raises(GovernanceError) as raised:
        capture_proposal(root, target="concept.md", proposal_file=tmp_path / "absent.yaml", session_id="parent")
    assert raised.value.code == "governance.proposal_invalid"
    assert "absent.yaml" in raised.value.message


def test_surrogate_escaped_proposal_loads_emoji(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    _session(root, "parent")
    result = "---\ntype: Decision\ntitle: Party\nresource: kb:demo/party\n---\nShipped \U0001F600\n"
    proposal_file = tmp_path / "proposal.yaml"
    proposal_file.write_text(
        "schema_version: 1\nsummary: Emoji survives\n"
        "evidence: []\nsource_paths: []\nconfidence: high\nknown_gaps: []\n"
        "suggested_freshness: {}\nconflicts: []\nresult_content: "
        + json.dumps(result, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    assert "\\ud83d\\ude00" in proposal_file.read_text(encoding="utf-8")
    proposal = capture_proposal(root, target="projects/demo/party.md", proposal_file=proposal_file, session_id="parent")
    assert "\U0001F600" in proposal.result_content


def test_promote_refuses_new_doc_without_freshness(tmp_path: Path) -> None:
    from eos_kb.gate import load_gate

    root = tmp_path / "knowledge"
    root.mkdir()
    _session(root, "parent")
    index_bundle(root)
    assert load_gate(root) is not None
    proposal_file = tmp_path / "proposal.yaml"
    result = "---\ntype: Decision\ntitle: Service\nresource: kb:demo/service\n---\n# Service\nCurrent behavior.\n"
    _proposal_input(proposal_file, result)
    proposal = capture_proposal(root, target="projects/demo/service.md", proposal_file=proposal_file, session_id="parent")
    review_proposal(root, proposal.proposal_id, actor="Vikas", session_id="parent", decision="accepted")
    source_root = tmp_path / "source"
    source_root.mkdir()
    with pytest.raises(GovernanceError) as raised:
        promote_proposal(root, proposal.proposal_id, session_id="parent", source_root=source_root)
    assert raised.value.code == "governance.result_invalid"
    assert "freshness.contract_required" in raised.value.message
    assert load_proposal(root, proposal.proposal_id).state is ProposalState.ACCEPTED


def test_promote_writes_hash_bound_review_event(tmp_path: Path) -> None:
    import json as json_module

    from eos_kb.freshness import audit_freshness
    from eos_kb.gate import latest_review_event
    from eos_kb.normalize import normalized_content_hash

    root = tmp_path / "knowledge"
    root.mkdir()
    _session(root, "parent")
    index_bundle(root)
    proposal_file = tmp_path / "proposal.yaml"
    result = (
        "---\ntype: Decision\ntitle: Service\nresource: kb:demo/service\n"
        "freshness: tracked\nreview_every: 30d\n---\n# Service\nCurrent behavior.\n"
    )
    _proposal_input(proposal_file, result)
    proposal = capture_proposal(root, target="projects/demo/service.md", proposal_file=proposal_file, session_id="parent")
    review_proposal(root, proposal.proposal_id, actor="Vikas", session_id="parent", decision="accepted")
    source_root = tmp_path / "source"
    source_root.mkdir()
    promoted = promote_proposal(root, proposal.proposal_id, session_id="parent", source_root=source_root)
    assert promoted.state is ProposalState.PROMOTED
    content_hash = normalized_content_hash(result)
    latest = latest_review_event(root, "projects/demo/service.md")
    assert latest is not None
    assert latest[1] == content_hash
    lines = (root / ".eos" / "reviews.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json_module.loads(lines[0])
    assert event["target"] == "projects/demo/service.md"
    assert event["content_hash"] == content_hash
    report = audit_freshness(root, source_root)
    assert [item.state for item in report.time] == ["current"]


def test_direct_change_approval_writes_no_review_event(tmp_path: Path) -> None:
    from eos_kb.normalize import normalized_content_hash

    root = tmp_path / "knowledge"
    root.mkdir()
    _session(root, "parent")
    target = root / "concept.md"
    text = "---\ntype: Decision\ntitle: Concept\nresource: kb:concept\nfreshness: tracked\nreview_every: 30d\n---\nOriginal\n"
    target.write_text(text, encoding="utf-8")
    index_bundle(root)
    review_direct_change(root, "concept.md", actor="Vikas", session_id="parent")
    # Self-approval records the acceptance but must not move expiry.
    assert not (root / ".eos" / "reviews.jsonl").exists()
    approvals = [
        json.loads(line)
        for line in (root / ".eos" / "approvals.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert approvals[-1]["proposal_id"] == "direct-change:concept.md"
    assert approvals[-1]["proposed_result_hash"] == normalized_content_hash(text)


def test_direct_change_approval_does_not_reset_expiry(tmp_path: Path) -> None:
    from datetime import datetime, timedelta, timezone

    from eos_kb.freshness import audit_freshness
    from eos_kb.indexer import index_bundle

    root = tmp_path / "knowledge"
    root.mkdir()
    _session(root, "parent")
    source_root = tmp_path / "source"
    source_root.mkdir()
    index_bundle(root)
    proposal_file = tmp_path / "proposal.yaml"
    result = (
        "---\ntype: Decision\ntitle: Service\nresource: kb:demo/service\n"
        "freshness: tracked\nreview_every: 30d\n---\n# Service\nCurrent behavior.\n"
    )
    _proposal_input(proposal_file, result)
    proposal = capture_proposal(root, target="projects/demo/service.md", proposal_file=proposal_file, session_id="parent")
    review_proposal(root, proposal.proposal_id, actor="Vikas", session_id="parent", decision="accepted")
    promote_proposal(root, proposal.proposal_id, session_id="parent", source_root=source_root)

    expired_at = datetime.now(timezone.utc) + timedelta(days=40)
    assert audit_freshness(root, source_root, now=expired_at).time[0].state == "stale"
    # Approving the stale content directly changes nothing about expiry.
    review_direct_change(root, "projects/demo/service.md", actor="Vikas", session_id="parent")
    reread = audit_freshness(root, source_root, now=expired_at)
    assert reread.time[0].state == "stale"


def test_promote_normalizes_absolute_and_dot_targets(tmp_path: Path) -> None:
    import json as json_module

    root = tmp_path / "knowledge"
    root.mkdir()
    _session(root, "parent")
    (root / "projects" / "demo").mkdir(parents=True)
    index_bundle(root)
    proposal_file = tmp_path / "proposal.yaml"
    result = "---\ntype: Decision\ntitle: Service\nresource: kb:demo/service\nfreshness: historical\n---\n# Service\nCurrent behavior.\n"
    _proposal_input(proposal_file, result)
    absolute = (root / "projects" / "demo" / "service.md").as_posix()
    proposal = capture_proposal(root, target=absolute, proposal_file=proposal_file, session_id="parent")
    review_proposal(root, proposal.proposal_id, actor="Vikas", session_id="parent", decision="accepted")
    source_root = tmp_path / "source"
    source_root.mkdir()
    assert promote_proposal(root, proposal.proposal_id, session_id="parent", source_root=source_root).state is ProposalState.PROMOTED
    lines = (root / ".eos" / "reviews.jsonl").read_text(encoding="utf-8").splitlines()
    assert json_module.loads(lines[-1])["target"] == "projects/demo/service.md"

    proposal_file2 = tmp_path / "proposal2.yaml"
    _proposal_input(proposal_file2, result.replace("Current behavior.", "Second behavior."))
    dotted = capture_proposal(root, target="./projects/demo/service.md", proposal_file=proposal_file2, session_id="parent")
    review_proposal(root, dotted.proposal_id, actor="Vikas", session_id="parent", decision="accepted")
    assert promote_proposal(root, dotted.proposal_id, session_id="parent", source_root=source_root).state is ProposalState.PROMOTED
    lines = (root / ".eos" / "reviews.jsonl").read_text(encoding="utf-8").splitlines()
    assert json_module.loads(lines[-1])["target"] == "projects/demo/service.md"


def test_direct_change_normalizes_dot_target(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    _session(root, "parent")
    target = root / "concept.md"
    target.write_text("---\ntype: Decision\ntitle: Concept\nresource: kb:concept\n---\nOriginal\n", encoding="utf-8")
    index_bundle(root)
    record = review_direct_change(root, "./concept.md", actor="Vikas", session_id="parent")
    assert record["proposal_id"] == "direct-change:concept.md"


def test_promote_existing_untagged_doc_needs_no_contract(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    (root / "projects" / "demo").mkdir(parents=True)
    _session(root, "parent")
    target = root / "projects" / "demo" / "service.md"
    target.write_text("---\ntype: Decision\ntitle: Service\nresource: kb:demo/service\n---\nOriginal\n", encoding="utf-8")
    index_bundle(root)
    proposal_file = tmp_path / "proposal.yaml"
    result = "---\ntype: Decision\ntitle: Service\nresource: kb:demo/service\n---\nUpdated\n"
    _proposal_input(proposal_file, result)
    proposal = capture_proposal(root, target="projects/demo/service.md", proposal_file=proposal_file, session_id="parent")
    review_proposal(root, proposal.proposal_id, actor="Vikas", session_id="parent", decision="accepted")
    source_root = tmp_path / "source"
    source_root.mkdir()
    assert promote_proposal(root, proposal.proposal_id, session_id="parent", source_root=source_root).state is ProposalState.PROMOTED


def test_promote_without_gate_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    _session(root, "parent")
    proposal_file = tmp_path / "proposal.yaml"
    result = "---\ntype: Decision\ntitle: Service\nresource: kb:demo/service\nfreshness: historical\n---\n# Service\nCurrent behavior.\n"
    _proposal_input(proposal_file, result)
    proposal = capture_proposal(root, target="projects/demo/service.md", proposal_file=proposal_file, session_id="parent")
    review_proposal(root, proposal.proposal_id, actor="Vikas", session_id="parent", decision="accepted")
    source_root = tmp_path / "source"
    source_root.mkdir()
    with pytest.raises(GovernanceError) as raised:
        promote_proposal(root, proposal.proposal_id, session_id="parent", source_root=source_root)
    assert raised.value.code == "gate.missing"


def test_promote_with_corrupt_gate_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    _session(root, "parent")
    index_bundle(root)
    (root / ".eos" / "freshness-gate.json").write_text("{truncated", encoding="utf-8")
    proposal_file = tmp_path / "proposal.yaml"
    result = "---\ntype: Decision\ntitle: Service\nresource: kb:demo/service\nfreshness: historical\n---\n# Service\nCurrent behavior.\n"
    _proposal_input(proposal_file, result)
    proposal = capture_proposal(root, target="projects/demo/service.md", proposal_file=proposal_file, session_id="parent")
    review_proposal(root, proposal.proposal_id, actor="Vikas", session_id="parent", decision="accepted")
    source_root = tmp_path / "source"
    source_root.mkdir()
    with pytest.raises(GovernanceError) as raised:
        promote_proposal(root, proposal.proposal_id, session_id="parent", source_root=source_root)
    assert raised.value.code == "gate.corrupt"
