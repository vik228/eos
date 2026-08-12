from __future__ import annotations

from pathlib import Path

import pytest

from eos_kb.investigations import (
    InvestigationError,
    block_investigation,
    complete_investigation,
    record_evidence,
    resume_investigation,
    start_investigation,
    status_investigation,
)


@pytest.fixture
def kb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))
    root = tmp_path / "knowledge"
    root.mkdir()
    return root


def test_investigation_requires_e2e_reproduction_and_durable_learning_decision(kb: Path) -> None:
    investigation = start_investigation(kb, session_id="s1", symptom="save loses data")
    investigation_id = investigation["investigation_id"]
    assert investigation["phase"] == "new"
    record_evidence(kb, investigation_id, "classification", {"impact": "data loss"})
    record_evidence(kb, investigation_id, "reproduction", {"command": "pytest", "actual": "fail"})
    record_evidence(kb, investigation_id, "retrieval", {"resources": ["kb:failure-mode"]})
    record_evidence(kb, investigation_id, "system_map", {"entrypoint": "save", "readers": ["x"]})
    record_evidence(kb, investigation_id, "blast_radius", {"cases": ["save", "retry"]})
    record_evidence(kb, investigation_id, "hypothesis", {"id": "h1", "text": "bad write"})
    record_evidence(kb, investigation_id, "supporting", {"hypothesis_id": "h1", "evidence": "trace"})
    record_evidence(kb, investigation_id, "contradicting", {"hypothesis_id": "h1", "evidence": "none"})
    record_evidence(kb, investigation_id, "disconfirmation", {"hypothesis_id": "h1", "result": "supported"})
    record_evidence(kb, investigation_id, "alternative_disposition", {"decision": "no alternative"})
    record_evidence(kb, investigation_id, "root_cause", {"causal_chain": "input -> bad write -> loss"})
    record_evidence(kb, investigation_id, "failing_test", {"reference": "tests/test_save.py::test_loss"})
    record_evidence(kb, investigation_id, "affected_cases", {"cases": ["single", "retry"]})
    record_evidence(kb, investigation_id, "verification", {"command": "pytest", "result": "pass"})
    record_evidence(kb, investigation_id, "uncertainty", {"remaining": "none"})
    record_evidence(kb, investigation_id, "durable_learning", {"required": True, "proposal_id": "p1"})

    assert status_investigation(kb, investigation_id)["evidence"]["reproduction"] is True
    with pytest.raises(InvestigationError, match="verifying"):
        complete_investigation(kb, investigation_id)
    record_evidence(kb, investigation_id, "advance", {"phase": "reproducing"})
    record_evidence(kb, investigation_id, "advance", {"phase": "investigating"})
    record_evidence(kb, investigation_id, "advance", {"phase": "root-caused"})
    record_evidence(kb, investigation_id, "advance", {"phase": "fixing"})
    record_evidence(kb, investigation_id, "advance", {"phase": "verifying"})
    assert complete_investigation(kb, investigation_id)["phase"] == "complete"


def test_fix_transition_requires_root_cause_and_failing_test(kb: Path) -> None:
    item = start_investigation(kb, session_id="s1", symptom="broken")
    investigation_id = item["investigation_id"]
    for phase in ("reproducing", "investigating"):
        record_evidence(kb, investigation_id, "advance", {"phase": phase})
    with pytest.raises(InvestigationError, match="root cause"):
        record_evidence(kb, investigation_id, "advance", {"phase": "root-caused"})


def test_block_and_resume_return_to_recorded_phase(kb: Path) -> None:
    item = start_investigation(kb, session_id="s1", symptom="broken")
    blocked = block_investigation(kb, item["investigation_id"], reason="fixture unavailable")
    assert blocked["phase"] == "blocked"
    assert resume_investigation(kb, item["investigation_id"], resolution="fixture added")["phase"] == "new"
