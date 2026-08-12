"""Approval-gated, hash-bound knowledge-base governance."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from .model import ProposalState
from .normalize import normalized_content_hash
from .frontmatter import parse_concept, parse_concept_text
from .indexer import CoverageContract, index_bundle, valid_manifest
from .storage import (
    begin_transaction,
    state_directory,
    transactional_replace,
    write_staged,
    writer_lock,
)


class GovernanceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    target: str
    summary: str
    evidence: tuple[str, ...]
    source_paths: tuple[str, ...]
    confidence: str
    known_gaps: tuple[str, ...]
    suggested_freshness: dict[str, Any]
    conflicts: tuple[str, ...]
    result_content: str
    state: ProposalState
    base_target_hash: str | None
    proposed_result_hash: str
    proposal_hash: str
    session_id: str

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "proposal_id": self.proposal_id,
            "target": self.target,
            "summary": self.summary,
            "evidence": list(self.evidence),
            "source_paths": list(self.source_paths),
            "confidence": self.confidence,
            "known_gaps": list(self.known_gaps),
            "suggested_freshness": self.suggested_freshness,
            "conflicts": list(self.conflicts),
            "result_content": self.result_content,
            "state": self.state.value,
            "base_target_hash": self.base_target_hash,
            "proposed_result_hash": self.proposed_result_hash,
            "session_id": self.session_id,
        }


_ALLOWED = {
    (ProposalState.CAPTURED, ProposalState.READY_FOR_REVIEW),
    (ProposalState.READY_FOR_REVIEW, ProposalState.ACCEPTED),
    (ProposalState.READY_FOR_REVIEW, ProposalState.REJECTED),
    (ProposalState.READY_FOR_REVIEW, ProposalState.SUPERSEDED),
    (ProposalState.ACCEPTED, ProposalState.PROMOTED),
    (ProposalState.ACCEPTED, ProposalState.SUPERSEDED),
}


def transition(source: ProposalState, target: ProposalState) -> ProposalState:
    if (source, target) not in _ALLOWED:
        raise GovernanceError("governance.transition_invalid", f"Cannot transition {source} to {target}.")
    return target


def _hash_payload(payload: dict[str, Any]) -> str:
    content = {key: value for key, value in payload.items() if key != "state"}
    data = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(data.encode("utf-8")).hexdigest()


def _eos(root: Path) -> Path:
    path = root / ".eos"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_target(root: Path, target: str) -> Path:
    path = (root / target).resolve()
    if path != root.resolve() and root.resolve() not in path.parents:
        raise GovernanceError("governance.target_invalid", "Target must remain inside the knowledge bundle.")
    return path


def _session(root: Path, session_id: str, *, lifecycle: bool = False) -> dict[str, Any]:
    path = state_directory(root) / "sessions" / f"{session_id}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceError("governance.session_missing", "A valid session record is required.") from exc
    if not isinstance(value, dict) or value.get("session_id") != session_id:
        raise GovernanceError("governance.session_invalid", "Session record does not match the requested session.")
    if lifecycle and value.get("parent_session_id") is not None:
        raise GovernanceError("governance.child_session_forbidden", "Child sessions cannot perform lifecycle approval operations.")
    return value


def _transaction(root: Path, files: dict[Path, bytes]) -> None:
    eos = _eos(root)
    recovery = eos / "transaction.json"
    txid = "governance-" + uuid.uuid4().hex
    destinations = tuple(files)
    replacements = begin_transaction(destinations, recovery_path=recovery, transaction_id=txid, allowed_destinations=destinations)
    try:
        for destination, data in files.items():
            write_staged(replacements[destination.resolve()], data)
        transactional_replace(replacements, recovery_path=recovery, transaction_id=txid, allowed_destinations=destinations)
    except BaseException:
        recovery.unlink(missing_ok=True)
        raise


def _proposal_from_payload(payload: dict[str, Any]) -> Proposal:
    stored_hash = payload.pop("proposal_hash", None)
    try:
        proposal = Proposal(
            proposal_id=str(payload["proposal_id"]), target=str(payload["target"]), summary=str(payload["summary"]),
            evidence=tuple(payload["evidence"]), source_paths=tuple(payload["source_paths"]), confidence=str(payload["confidence"]),
            known_gaps=tuple(payload["known_gaps"]), suggested_freshness=dict(payload["suggested_freshness"]), conflicts=tuple(payload["conflicts"]),
            result_content=str(payload["result_content"]), state=ProposalState(payload["state"]), base_target_hash=payload["base_target_hash"],
            proposed_result_hash=str(payload["proposed_result_hash"]), session_id=str(payload["session_id"]), proposal_hash=str(stored_hash),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GovernanceError("governance.proposal_invalid", "Stored proposal has an invalid shape.") from exc
    if stored_hash != _hash_payload(proposal.payload()):
        raise GovernanceError("governance.proposal_hash_mismatch", "Proposal content no longer matches its recorded hash.")
    return proposal


def load_proposal(root: Path, proposal_id: str) -> Proposal:
    path = _eos(root) / "proposals" / f"{proposal_id}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceError("governance.proposal_missing", "Proposal was not found.") from exc
    if not isinstance(payload, dict):
        raise GovernanceError("governance.proposal_invalid", "Stored proposal must be an object.")
    return _proposal_from_payload(payload)


def capture_proposal(root: Path, *, target: str, proposal_file: Path, session_id: str) -> Proposal:
    _session(root, session_id)
    target_path = _safe_target(root, target)
    try:
        source = yaml.safe_load(proposal_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise GovernanceError("governance.proposal_invalid", "Proposal input is not valid YAML.") from exc
    if not isinstance(source, dict):
        raise GovernanceError("governance.proposal_invalid", "Proposal input must be a mapping.")
    required = ("summary", "evidence", "source_paths", "confidence", "known_gaps", "suggested_freshness", "conflicts", "result_content")
    if any(field not in source for field in required) or not isinstance(source["result_content"], str):
        raise GovernanceError("governance.proposal_invalid", "Proposal input is missing required fields.")
    base = normalized_content_hash(target_path.read_text(encoding="utf-8")) if target_path.is_file() else None
    proposal = Proposal(
        proposal_id=str(uuid.uuid4()), target=target, summary=str(source["summary"]), evidence=tuple(source["evidence"]),
        source_paths=tuple(source["source_paths"]), confidence=str(source["confidence"]), known_gaps=tuple(source["known_gaps"]),
        suggested_freshness=dict(source["suggested_freshness"]), conflicts=tuple(source["conflicts"]), result_content=source["result_content"],
        state=ProposalState.READY_FOR_REVIEW, base_target_hash=base, proposed_result_hash=normalized_content_hash(source["result_content"]),
        proposal_hash="", session_id=session_id,
    )
    proposal = Proposal(**{**proposal.__dict__, "proposal_hash": _hash_payload(proposal.payload()), "session_id": session_id})
    path = _eos(root) / "proposals" / f"{proposal.proposal_id}.json"
    payload = proposal.payload() | {"proposal_hash": proposal.proposal_hash}
    with writer_lock(_eos(root)):
        _transaction(root, {path: (json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")})
    return proposal


def _approval_records(root: Path) -> list[dict[str, Any]]:
    path = _eos(root) / "approvals.jsonl"
    if not path.exists():
        return []
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceError("governance.approvals_invalid", "Approval log is unreadable.") from exc


def review_proposal(root: Path, proposal_id: str, *, actor: str, session_id: str, decision: str) -> Proposal:
    _session(root, session_id)
    with writer_lock(_eos(root)):
        proposal = load_proposal(root, proposal_id)
        target_state = ProposalState(decision)
        transition(proposal.state, target_state)
        approval = {"schema_version": 1, "proposal_id": proposal.proposal_id, "actor": actor, "timestamp": datetime.now(timezone.utc).isoformat(), "proposal_hash": proposal.proposal_hash, "base_target_hash": proposal.base_target_hash, "proposed_result_hash": proposal.proposed_result_hash, "decision": decision, "session_id": session_id}
        updated = Proposal(**{**proposal.__dict__, "state": target_state})
        # Lifecycle state is deliberately excluded from proposal_hash.
        path = _eos(root) / "proposals" / f"{proposal_id}.json"
        log = _eos(root) / "approvals.jsonl"
        _transaction(root, {path: (json.dumps(updated.payload() | {"proposal_hash": updated.proposal_hash, "state": target_state.value}, sort_keys=True) + "\n").encode(), log: ((log.read_text() if log.exists() else "") + json.dumps(approval, sort_keys=True) + "\n").encode()})
        return updated


def _approved(root: Path, proposal: Proposal) -> dict[str, Any]:
    records = [r for r in _approval_records(root) if r.get("proposal_id") == proposal.proposal_id and r.get("decision") == "accepted"]
    if not records or records[-1].get("proposal_hash") != proposal.proposal_hash:
        raise GovernanceError("governance.approval_missing", "No matching accepted approval exists.")
    return records[-1]


def promote_proposal(
    root: Path,
    proposal_id: str,
    *,
    session_id: str,
    source_root: Path | None = None,
    coverage_rules: Iterable[CoverageContract] = (),
) -> Proposal:
    _session(root, session_id, lifecycle=True)
    with writer_lock(_eos(root)), writer_lock(state_directory(root)):
        proposal = load_proposal(root, proposal_id)
        if proposal.state is not ProposalState.ACCEPTED:
            raise GovernanceError("governance.proposal_not_accepted", "Only accepted proposals may be promoted.")
        _approved(root, proposal)
        target = _safe_target(root, proposal.target)
        live = normalized_content_hash(target.read_text(encoding="utf-8")) if target.is_file() else None
        if live != proposal.base_target_hash:
            raise GovernanceError("governance.base_hash_mismatch", "Target changed since proposal capture.")
        if normalized_content_hash(proposal.result_content) != proposal.proposed_result_hash:
            raise GovernanceError("governance.result_hash_mismatch", "Proposal result no longer matches its recorded hash.")
        try:
            parse_concept_text(proposal.result_content, proposal.target)
        except Exception as exc:
            raise GovernanceError("governance.result_invalid", "Promotion result is not a valid knowledge concept.") from exc
        updated = Proposal(**{**proposal.__dict__, "state": ProposalState.PROMOTED})
        proposal_path = _eos(root) / "proposals" / f"{proposal_id}.json"
        files = _promotion_files(
            root,
            target,
            proposal,
            updated,
            proposal_path,
            source_root=source_root,
            coverage_rules=tuple(coverage_rules),
        )
        _transaction(root, files)
        return updated


def _promotion_files(
    root: Path,
    target: Path,
    proposal: Proposal,
    updated: Proposal,
    proposal_path: Path,
    *,
    source_root: Path | None,
    coverage_rules: tuple[CoverageContract, ...],
) -> dict[Path, bytes]:
    """Build all derived artifacts from the candidate source before live swap."""
    with tempfile.TemporaryDirectory(prefix="eos-promotion-", dir=root.parent) as directory:
        shadow = Path(directory) / "knowledge"
        shutil.copytree(
            root,
            shadow,
            symlinks=True,
            ignore=shutil.ignore_patterns(".eos", ".git"),
        )
        shadow_target = shadow / target.relative_to(root)
        shadow_target.parent.mkdir(parents=True, exist_ok=True)
        shadow_target.write_text(proposal.result_content, encoding="utf-8")
        indexed = index_bundle(
            shadow,
            state_path=Path(directory) / "state",
            source_root=source_root,
            coverage_rules=coverage_rules,
        )
        try:
            if indexed.errors:
                details = "; ".join(
                    f"{error.code}:{error.relative_file}" for error in indexed.errors
                )
                raise GovernanceError(
                    "governance.result_invalid",
                    f"Promotion candidate does not produce a valid index: {details}",
                )
            state = indexed.database_path.parent
            manifest_path = state / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not valid_manifest(manifest):
                raise GovernanceError(
                    "governance.manifest_invalid",
                    "Promotion generated a manifest outside the manifest-v1 schema.",
                )
            files: dict[Path, bytes] = {
                target: proposal.result_content.encode("utf-8"),
                proposal_path: (
                    json.dumps(
                        updated.payload() | {"proposal_hash": proposal.proposal_hash},
                        sort_keys=True,
                        ensure_ascii=False,
                    )
                    + "\n"
                ).encode("utf-8"),
                state_directory(root) / "index.sqlite3": indexed.database_path.read_bytes(),
                state_directory(root) / "manifest.json": manifest_path.read_bytes(),
            }
            for relative in manifest["routers"]:
                router = shadow / relative
                if router.is_file():
                    files[root / relative] = router.read_bytes()
            return files
        finally:
            if indexed.connection is not None:
                indexed.connection.close()


def deprecate_proposal(root: Path, target: str, *, proposal_id: str, session_id: str) -> Proposal:
    _session(root, session_id, lifecycle=True)
    proposal = load_proposal(root, proposal_id)
    if proposal.target != target:
        raise GovernanceError("governance.target_mismatch", "Proposal target does not match the requested concept.")
    if "status: deprecated" not in proposal.result_content and "status: 'deprecated'" not in proposal.result_content and 'status: "deprecated"' not in proposal.result_content:
        raise GovernanceError("governance.deprecation_result_invalid", "Deprecation result must mark the concept deprecated.")
    return promote_proposal(root, proposal_id, session_id=session_id)


def review_direct_change(root: Path, target: str, *, actor: str, session_id: str, decision: str = "accepted") -> dict[str, Any]:
    _session(root, session_id, lifecycle=True)
    if decision != "accepted":
        raise GovernanceError("governance.direct_change_rejected", "Direct changes require explicit acceptance.")
    path = _safe_target(root, target)
    if not path.is_file():
        raise GovernanceError("governance.target_missing", "Direct-change target does not exist.")
    try:
        concept = parse_concept(path, root=root)
    except Exception as exc:
        raise GovernanceError("governance.target_invalid", "Direct-change target is not a valid stable concept.") from exc
    if concept.generated:
        raise GovernanceError("governance.generated_target", "Generated routers do not require direct-change approval.")
    current_hash = normalized_content_hash(path.read_text(encoding="utf-8"))
    record = {"schema_version": 1, "proposal_id": "direct-change:" + target, "actor": actor, "timestamp": datetime.now(timezone.utc).isoformat(), "proposal_hash": None, "base_target_hash": current_hash, "proposed_result_hash": current_hash, "decision": decision, "session_id": session_id}
    log = _eos(root) / "approvals.jsonl"
    with writer_lock(_eos(root)):
        _transaction(root, {log: ((log.read_text() if log.exists() else "") + json.dumps(record, sort_keys=True) + "\n").encode()})
    return record


direct_change_approval = review_direct_change
promote = promote_proposal
deprecate = deprecate_proposal
