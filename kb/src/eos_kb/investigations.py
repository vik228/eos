from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import atomic_write, state_directory, writer_lock


class InvestigationError(RuntimeError):
    pass


PHASES = ("new", "reproducing", "investigating", "root-caused", "fixing", "verifying", "complete", "blocked")
_FORWARD = {"new": "reproducing", "reproducing": "investigating", "investigating": "root-caused", "root-caused": "fixing", "fixing": "verifying"}
_EVIDENCE = ("classification", "retrieval", "reproduction", "system_map", "blast_radius", "hypothesis", "supporting", "contradicting", "disconfirmation", "alternative_disposition", "root_cause", "failing_test", "affected_cases", "verification", "uncertainty", "durable_learning")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _directory(root: Path) -> Path:
    path = state_directory(root) / "investigations"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(root: Path, investigation_id: str) -> Path:
    return _directory(root) / f"{investigation_id}.json"


def _read(root: Path, investigation_id: str) -> dict[str, Any]:
    try:
        return json.loads(_path(root, investigation_id).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InvestigationError(f"investigation {investigation_id!r} not found") from exc


def _write(path: Path, value: dict[str, Any]) -> None:
    atomic_write(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def start_investigation(root: Path, *, session_id: str, symptom: str, investigation_id: str | None = None) -> dict[str, Any]:
    investigation_id = investigation_id or str(uuid.uuid4())
    record = {"schema_version": 1, "investigation_id": investigation_id, "session_id": session_id, "symptom": symptom, "phase": "new", "prior_phase": None, "blocker": None, "evidence": [], "durable_learning": None, "created_at": _now(), "updated_at": _now()}
    with writer_lock(_directory(root)):
        if _path(root, investigation_id).exists():
            raise InvestigationError("investigation ID already exists")
        _write(_path(root, investigation_id), record)
    return record


def record_evidence(root: Path, investigation_id: str, kind: str, value: Any) -> dict[str, Any]:
    if kind not in (*_EVIDENCE, "advance"):
        raise InvestigationError(f"unknown evidence kind: {kind}")
    with writer_lock(_directory(root)):
        record = _read(root, investigation_id)
        if record["phase"] in ("complete", "blocked"):
            raise InvestigationError("terminal or blocked investigation cannot record evidence")
        if kind == "advance":
            target = value.get("phase") if isinstance(value, dict) else None
            if target != _FORWARD.get(record["phase"]):
                raise InvestigationError("invalid investigation phase transition")
            kinds = {item["kind"] for item in record["evidence"]}
            if target == "root-caused" and "root_cause" not in kinds:
                raise InvestigationError("root cause evidence is required")
            if target == "root-caused" and "hypothesis" in kinds and "disconfirmation" not in kinds:
                raise InvestigationError("every consistent hypothesis requires disconfirmation")
            if target == "fixing" and "root_cause" not in kinds:
                raise InvestigationError("root cause evidence is required before fixing")
            if target == "fixing" and not ({"failing_test", "reproduction"} & kinds):
                raise InvestigationError("failing test or executable reproduction is required before fixing")
            record["phase"] = target
        else:
            record["evidence"].append({"kind": kind, "value": value, "recorded_at": _now()})
            if kind == "durable_learning":
                record["durable_learning"] = value
        record["updated_at"] = _now()
        _write(_path(root, investigation_id), record)
    return record


def _summary(record: dict[str, Any]) -> dict[str, Any]:
    kinds = {item["kind"] for item in record["evidence"]}
    evidence = {kind: kind in kinds for kind in _EVIDENCE}
    evidence["causal_chain"] = evidence["root_cause"]
    evidence["fix_gate"] = evidence["failing_test"] or evidence["reproduction"]
    durable = record.get("durable_learning")
    return {**record, "phases": {phase: record["phase"] == phase for phase in PHASES}, "evidence": evidence, "durable_learning_status": "proposal_created" if durable and durable.get("proposal_id") else ("required" if durable and durable.get("required") else "not_required")}


def status_investigation(root: Path, investigation_id: str | None = None, *, session_id: str | None = None) -> dict[str, Any] | list[dict[str, Any]]:
    if investigation_id:
        return _summary(_read(root, investigation_id))
    return [_summary(json.loads(path.read_text(encoding="utf-8"))) for path in sorted(_directory(root).glob("*.json")) if session_id is None or json.loads(path.read_text(encoding="utf-8")).get("session_id") == session_id]


def block_investigation(root: Path, investigation_id: str, *, reason: str) -> dict[str, Any]:
    with writer_lock(_directory(root)):
        record = _read(root, investigation_id)
        if record["phase"] in ("complete", "blocked"):
            raise InvestigationError("investigation cannot be blocked from terminal state")
        record["prior_phase"] = record["phase"]
        record["phase"] = "blocked"
        record["blocker"] = reason
        record["updated_at"] = _now()
        _write(_path(root, investigation_id), record)
    return record


def resume_investigation(root: Path, investigation_id: str, *, resolution: str) -> dict[str, Any]:
    with writer_lock(_directory(root)):
        record = _read(root, investigation_id)
        if record["phase"] != "blocked":
            raise InvestigationError("only blocked investigations can resume")
        record["phase"] = record["prior_phase"]
        record["prior_phase"] = None
        record["blocker"] = None
        record["evidence"].append({"kind": "blocker_resolution", "value": resolution, "recorded_at": _now()})
        record["updated_at"] = _now()
        _write(_path(root, investigation_id), record)
    return record


def complete_investigation(root: Path, investigation_id: str) -> dict[str, Any]:
    with writer_lock(_directory(root)):
        record = _read(root, investigation_id)
        if record["phase"] != "verifying":
            raise InvestigationError("investigation must be verifying before completion")
        kinds = {item["kind"] for item in record["evidence"]}
        required = {"classification", "retrieval", "reproduction", "system_map", "blast_radius", "hypothesis", "supporting", "contradicting", "disconfirmation", "alternative_disposition", "root_cause", "failing_test", "affected_cases", "verification", "uncertainty"}
        missing = required - kinds
        if missing:
            raise InvestigationError("missing evidence: " + ", ".join(sorted(missing)))
        learning = record.get("durable_learning")
        if learning is None:
            raise InvestigationError("durable-learning proposal decision is required")
        if learning.get("required") and not learning.get("proposal_id"):
            raise InvestigationError("durable-learning proposal is required")
        record["phase"] = "complete"
        record["updated_at"] = _now()
        _write(_path(root, investigation_id), record)
    return _summary(record)
