"""Public command-line contract for the EOS knowledge base."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Any, Final, Sequence, TextIO

from .config import InitializationError, RegistryError, WorkspaceRoute, initialize_bundle, resolve_workspace
from .freshness import audit_freshness, load_freshness
from .governance import GovernanceError, capture_proposal, deprecate_proposal, promote_proposal, review_direct_change, review_proposal
from .indexer import index_bundle, validate_bundle
from .investigations import InvestigationError, block_investigation, complete_investigation, record_evidence, resume_investigation, start_investigation, status_investigation
from .migration import MigrationError, apply as apply_migration, inventory as migration_inventory, manifest_hash, plan as plan_migration, record_migration_approval, rollback as rollback_migration, verify_plan
from .retrieval import context as retrieve_context, related as retrieve_related, search as retrieve_search, show as retrieve_show, status as retrieve_status
from .sessions import SessionError, checkpoint_session, end_session, recover_sessions, resume_session, start_session
from .storage import StorageError, atomic_write


class ExitCode(IntEnum):
    """Stable process exit codes for all public commands."""

    SUCCESS = 0
    USAGE = 2
    VALIDATION = 3
    CONFLICT = 4
    BLOCKED_LIFECYCLE = 5
    RECOVERY_REQUIRED = 6


class ResultStatus(StrEnum):
    NOT_IMPLEMENTED = "not_implemented"
    INITIALIZED = "initialized"
    VALIDATION_FAILURE = "validation_failure"
    CONFLICT = "conflict"
    INDEXED = "indexed"
    VALIDATED = "validated"
    SEARCHED = "searched"
    SHOWN = "shown"
    RELATED = "related"
    CONTEXT = "context"
    READY = "ready"
    DEGRADED = "degraded"
    AUDITED = "audited"
    STALE = "stale"
    PROPOSED = "proposed"
    REVIEWED = "reviewed"
    PROMOTED = "promoted"
    DEPRECATED = "deprecated"
    SESSION = "session"
    INVESTIGATION = "investigation"
    MIGRATED = "migrated"


@dataclass(frozen=True)
class CommandResult:
    command: str
    status: ResultStatus
    message: str
    exit_code: ExitCode
    error: bool = False
    error_code: str | None = None
    error_field: str | None = None
    data: Any = None


COMMAND_OWNERSHIP: Final[dict[str, str]] = {
    "init": "Task 3",
    "index": "Task 4",
    "validate": "Task 4",
    "search": "Task 5",
    "show": "Task 5",
    "related": "Task 5",
    "context": "Task 5",
    "status": "Task 5",
    "stale": "Task 6",
    "audit": "Task 6",
    "checkpoint": "Task 8",
    "propose": "Task 7",
    "review": "Task 7",
    "promote": "Task 7",
    "deprecate": "Task 7",
    "session": "Task 8",
    "bug": "Task 9",
    "migrate": "Task 13",
}

NESTED_COMMANDS: Final[dict[str, tuple[str, ...]]] = {
    "session": ("start", "resume", "checkpoint", "end", "recover"),
    "bug": ("start", "record", "status", "block", "resume", "complete"),
    "migrate": ("inventory", "plan", "verify-plan", "approve", "apply", "rollback"),
}


class ParserExit(Exception):
    """Convert argparse exits into return values from main()."""

    def __init__(self, status: int, message: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class KbArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["allow_abbrev"] = False
        super().__init__(*args, **kwargs)

    def exit(self, status: int = 0, message: str | None = None) -> None:
        raise ParserExit(status, message)

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(ExitCode.USAGE, f"{self.prog}: error: {message}\n")


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _not_implemented(args: argparse.Namespace) -> CommandResult:
    command = args.command_path
    owner = args.owner
    return CommandResult(
        command=command,
        status=ResultStatus.NOT_IMPLEMENTED,
        message=f"command '{command}' is owned by {owner}",
        exit_code=ExitCode.USAGE,
    )


def _init(args: argparse.Namespace) -> CommandResult:
    try:
        route = resolve_workspace(Path.cwd(), kb=args.kb, project=args.project)
        initialize_bundle(route.kb, route.project)
    except RegistryError as exc:
        return CommandResult(
            command="init",
            status=ResultStatus.VALIDATION_FAILURE,
            message=exc.remediation,
            exit_code=ExitCode.VALIDATION,
            error=True,
            error_code=exc.code,
            error_field=exc.field_path,
        )
    except InitializationError as exc:
        return CommandResult(
            command="init",
            status=ResultStatus.CONFLICT,
            message=exc.remediation,
            exit_code=ExitCode.CONFLICT,
            error=True,
            error_code=exc.code,
            error_field=exc.field_path,
        )
    except OSError:
        return CommandResult(
            command="init",
            status=ResultStatus.CONFLICT,
            message="Unable to initialize knowledge bundle.",
            exit_code=ExitCode.CONFLICT,
            error=True,
            error_code="init.io_error",
            error_field="$.layout",
        )
    display_kb = args.kb.expanduser() if args.kb is not None else route.kb
    return CommandResult(
        command="init",
        status=ResultStatus.INITIALIZED,
        message=f"initialized {display_kb} ({route.project})",
        exit_code=ExitCode.SUCCESS,
    )


def _index(args: argparse.Namespace) -> CommandResult:
    try:
        route = resolve_workspace(Path.cwd(), kb=args.kb)
        report = index_bundle(
            route.kb,
            rebuild=args.rebuild,
            source_root=route.workspace,
            coverage_rules=route.coverage,
        )
    except RegistryError as exc:
        return CommandResult("index", ResultStatus.VALIDATION_FAILURE, exc.remediation, ExitCode.VALIDATION, True, exc.code, exc.field_path)
    except StorageError as exc:
        return CommandResult("index", ResultStatus.VALIDATION_FAILURE, exc.message, ExitCode.VALIDATION, True, exc.code, "$.recovery")
    except Exception as exc:
        return CommandResult("index", ResultStatus.VALIDATION_FAILURE, str(exc), ExitCode.VALIDATION, True, "index.failure", "$.kb")
    if report.errors:
        return CommandResult("index", ResultStatus.VALIDATION_FAILURE, f"indexed with {len(report.errors)} validation error(s)", ExitCode.VALIDATION, True, report.errors[0].code, report.errors[0].relative_file)
    display_kb = args.kb.expanduser() if args.kb is not None else route.kb
    return CommandResult("index", ResultStatus.INDEXED, f"indexed {display_kb}", ExitCode.SUCCESS)


def _validate(args: argparse.Namespace) -> CommandResult:
    try:
        route = resolve_workspace(Path.cwd(), kb=args.kb)
        report = validate_bundle(
            route.kb,
            strict=args.strict,
            source_root=route.workspace,
            coverage_rules=route.coverage,
        )
    except RegistryError as exc:
        return CommandResult("validate", ResultStatus.VALIDATION_FAILURE, exc.remediation, ExitCode.VALIDATION, True, exc.code, exc.field_path)
    except StorageError as exc:
        return CommandResult("validate", ResultStatus.VALIDATION_FAILURE, exc.message, ExitCode.VALIDATION, True, exc.code, "$.recovery")
    except Exception as exc:
        return CommandResult("validate", ResultStatus.VALIDATION_FAILURE, str(exc), ExitCode.VALIDATION, True, "validate.failure", "$.kb")
    if report.errors:
        return CommandResult("validate", ResultStatus.VALIDATION_FAILURE, f"validation failed with {len(report.errors)} error(s)", ExitCode.VALIDATION, True, report.errors[0].code, report.errors[0].relative_file)
    display_kb = args.kb.expanduser() if args.kb is not None else route.kb
    return CommandResult("validate", ResultStatus.VALIDATED, f"validated {display_kb}", ExitCode.SUCCESS)


def _resolve_retrieval_route(args: argparse.Namespace) -> WorkspaceRoute:
    return resolve_workspace(Path.cwd(), kb=args.kb)


def _search(args: argparse.Namespace) -> CommandResult:
    try:
        route = _resolve_retrieval_route(args)
        project = args.project or (route.project if route.registered else None)
        cards = retrieve_search(route.kb, args.query, project=project, types=args.types, components=args.components, status=args.status, freshness=args.freshness, include_draft=args.include_draft, include_deprecated=args.include_deprecated, limit=args.limit)
    except (RegistryError, ValueError) as exc:
        message = exc.remediation if isinstance(exc, RegistryError) else str(exc)
        return CommandResult("search", ResultStatus.VALIDATION_FAILURE, message, ExitCode.VALIDATION, True, getattr(exc, "code", "search.validation"), getattr(exc, "field_path", "$.query"))
    return CommandResult("search", ResultStatus.SEARCHED, f"found {len(cards)} result(s)", ExitCode.SUCCESS, data=[card.as_dict() for card in cards])


def _show(args: argparse.Namespace) -> CommandResult:
    try:
        card = retrieve_show(_resolve_retrieval_route(args).kb, args.concept, section=args.section)
    except (RegistryError, ValueError) as exc:
        message = exc.remediation if isinstance(exc, RegistryError) else str(exc)
        return CommandResult("show", ResultStatus.VALIDATION_FAILURE, message, ExitCode.VALIDATION, True, getattr(exc, "code", "show.validation"), getattr(exc, "field_path", "$.concept"))
    return CommandResult("show", ResultStatus.SHOWN, f"showing {card.resource}", ExitCode.SUCCESS, data=card.as_dict())


def _related(args: argparse.Namespace) -> CommandResult:
    try:
        cards = retrieve_related(_resolve_retrieval_route(args).kb, args.concept, limit=args.limit)
    except (RegistryError, ValueError) as exc:
        message = exc.remediation if isinstance(exc, RegistryError) else str(exc)
        return CommandResult("related", ResultStatus.VALIDATION_FAILURE, message, ExitCode.VALIDATION, True, getattr(exc, "code", "related.validation"), getattr(exc, "field_path", "$.concept"))
    return CommandResult("related", ResultStatus.RELATED, f"found {len(cards)} related concept(s)", ExitCode.SUCCESS, data=[card.as_dict() for card in cards])


def _context(args: argparse.Namespace) -> CommandResult:
    try:
        route = _resolve_retrieval_route(args)
        project = args.project or (route.project if route.registered else None)
        result = retrieve_context(route.kb, args.query, budget=args.budget, project=project, components=args.components)
    except (RegistryError, ValueError) as exc:
        message = exc.remediation if isinstance(exc, RegistryError) else str(exc)
        return CommandResult("context", ResultStatus.VALIDATION_FAILURE, message, ExitCode.VALIDATION, True, getattr(exc, "code", "context.validation"), getattr(exc, "field_path", "$.query"))
    return CommandResult("context", ResultStatus.CONTEXT, f"assembled {len(result.cards)} result card(s) at {result.estimated_units} units", ExitCode.SUCCESS, data=result.as_dict())


def _status(args: argparse.Namespace) -> CommandResult:
    try:
        if args.kb is not None and not args.kb.expanduser().is_dir():
            raise ValueError("knowledge root is missing or not a directory")
        result = retrieve_status(_resolve_retrieval_route(args).kb)
    except (RegistryError, ValueError) as exc:
        message = exc.remediation if isinstance(exc, RegistryError) else str(exc)
        return CommandResult("status", ResultStatus.VALIDATION_FAILURE, message, ExitCode.VALIDATION, True, getattr(exc, "code", "status.validation"), "$.kb")
    missing = result["state"]["missing"]
    corrupt = result["state"]["corrupt"]
    if missing or corrupt:
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if corrupt:
            details.append(f"corrupt {', '.join(corrupt)}")
        return CommandResult(
            "status", ResultStatus.DEGRADED,
            f"knowledge index degraded: {'; '.join(details)}",
            ExitCode.VALIDATION, True, "status.degraded", "$.state", result,
        )
    return CommandResult("status", ResultStatus.READY, "knowledge index status", ExitCode.SUCCESS, data=result)


def _audit(args: argparse.Namespace) -> CommandResult:
    try:
        route = _resolve_retrieval_route(args)
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else None
        report = audit_freshness(
            route.kb,
            args.source_root.expanduser().resolve() if args.source_root else route.workspace,
            now=now,
            coverage_rules=route.coverage,
        )
    except (RegistryError, ValueError) as exc:
        message = exc.remediation if isinstance(exc, RegistryError) else str(exc)
        return CommandResult(
            "audit", ResultStatus.VALIDATION_FAILURE, message,
            ExitCode.VALIDATION, True,
            getattr(exc, "code", "freshness.audit_failed"),
            getattr(exc, "field_path", "$.freshness"),
        )
    return CommandResult(
        "audit", ResultStatus.AUDITED,
        f"knowledge freshness is {report.overall}",
        ExitCode.SUCCESS,
        data=report.as_dict(),
    )


def _stale(args: argparse.Namespace) -> CommandResult:
    try:
        route = _resolve_retrieval_route(args)
        report = load_freshness(route.kb)
    except (RegistryError, ValueError) as exc:
        message = exc.remediation if isinstance(exc, RegistryError) else str(exc)
        return CommandResult(
            "stale", ResultStatus.VALIDATION_FAILURE, message,
            ExitCode.VALIDATION, True,
            getattr(exc, "code", "freshness.state_unavailable"),
            getattr(exc, "field_path", "$.freshness"),
        )
    return CommandResult(
        "stale", ResultStatus.STALE,
        f"found {len(report.warnings)} freshness warning(s)",
        ExitCode.SUCCESS,
        data=report.as_dict(),
    )


def _governance_error(command: str, exc: GovernanceError) -> CommandResult:
    blocked = exc.code == "governance.child_session_forbidden"
    return CommandResult(
        command,
        ResultStatus.VALIDATION_FAILURE,
        exc.message,
        ExitCode.BLOCKED_LIFECYCLE if blocked else ExitCode.VALIDATION,
        True,
        exc.code,
        "$.governance",
    )


def _propose(args: argparse.Namespace) -> CommandResult:
    try:
        route = _resolve_retrieval_route(args)
        proposal = capture_proposal(route.kb, target=args.target, proposal_file=args.proposal_file, session_id=args.session)
    except (RegistryError, GovernanceError) as exc:
        if isinstance(exc, GovernanceError):
            return _governance_error("propose", exc)
        return CommandResult("propose", ResultStatus.VALIDATION_FAILURE, exc.remediation, ExitCode.VALIDATION, True, exc.code, exc.field_path)
    return CommandResult("propose", ResultStatus.PROPOSED, f"captured {proposal.proposal_id}", ExitCode.SUCCESS, data=proposal.payload() | {"proposal_hash": proposal.proposal_hash})


def _review(args: argparse.Namespace) -> CommandResult:
    try:
        route = _resolve_retrieval_route(args)
        if args.subject == "direct-change":
            if not args.target:
                raise GovernanceError("governance.target_required", "Direct-change review requires --target.")
            data = review_direct_change(route.kb, args.target, actor=args.actor, session_id=args.session, decision=args.decision)
        else:
            proposal = review_proposal(route.kb, args.subject, actor=args.actor, session_id=args.session, decision=args.decision)
            data = proposal.payload() | {"proposal_hash": proposal.proposal_hash}
    except GovernanceError as exc:
        return _governance_error("review", exc)
    except RegistryError as exc:
        return CommandResult("review", ResultStatus.VALIDATION_FAILURE, exc.remediation, ExitCode.VALIDATION, True, exc.code, exc.field_path)
    return CommandResult("review", ResultStatus.REVIEWED, "review recorded", ExitCode.SUCCESS, data=data)


def _promote(args: argparse.Namespace) -> CommandResult:
    try:
        route = _resolve_retrieval_route(args)
        proposal = promote_proposal(
            route.kb,
            args.proposal,
            session_id=args.session,
            source_root=route.workspace,
            coverage_rules=route.coverage,
        )
    except GovernanceError as exc:
        return _governance_error("promote", exc)
    except RegistryError as exc:
        return CommandResult("promote", ResultStatus.VALIDATION_FAILURE, exc.remediation, ExitCode.VALIDATION, True, exc.code, exc.field_path)
    return CommandResult("promote", ResultStatus.PROMOTED, f"promoted {proposal.proposal_id}", ExitCode.SUCCESS, data=proposal.payload())


def _deprecate(args: argparse.Namespace) -> CommandResult:
    try:
        route = _resolve_retrieval_route(args)
        proposal = deprecate_proposal(route.kb, args.concept, proposal_id=args.proposal, session_id=args.session)
    except GovernanceError as exc:
        return _governance_error("deprecate", exc)
    except RegistryError as exc:
        return CommandResult("deprecate", ResultStatus.VALIDATION_FAILURE, exc.remediation, ExitCode.VALIDATION, True, exc.code, exc.field_path)
    return CommandResult("deprecate", ResultStatus.DEPRECATED, f"deprecated {args.concept}", ExitCode.SUCCESS, data=proposal.payload())


def _lifecycle_audit(route: WorkspaceRoute, command: str) -> CommandResult | None:
    """Audit the declared workspace before a lifecycle mutation is persisted."""
    try:
        report = audit_freshness(
            route.kb,
            route.workspace,
            coverage_rules=route.coverage,
        )
    except (RegistryError, ValueError) as exc:
        message = exc.remediation if isinstance(exc, RegistryError) else str(exc)
        return CommandResult(
            command,
            ResultStatus.VALIDATION_FAILURE,
            f"freshness audit blocked lifecycle: {message}",
            ExitCode.BLOCKED_LIFECYCLE,
            True,
            getattr(exc, "code", "freshness.audit_failed"),
            getattr(exc, "field_path", "$.freshness"),
        )

    warnings = tuple(getattr(report, "warnings", ()))
    contradictions = tuple(getattr(report, "contradictions", ()))
    # Unknown means that a concept has no freshness contract or that its
    # evidence cannot currently be evaluated. Keep it visible in audit and
    # retrieval output, but do not deadlock an otherwise valid agent session.
    # Confirmed stale evidence and contradictions remain lifecycle blockers.
    if report.overall != "stale" and not contradictions:
        return None

    reasons = list(warnings)
    if contradictions and not any("contradiction" in reason for reason in reasons):
        reasons.append(f"{len(contradictions)} contradiction(s) detected")
    if not reasons:
        reasons.append(f"freshness is {report.overall}")
    report_data = report.as_dict() if hasattr(report, "as_dict") else None
    return CommandResult(
        command,
        ResultStatus.VALIDATION_FAILURE,
        f"freshness audit blocked lifecycle: {'; '.join(reasons)}",
        ExitCode.BLOCKED_LIFECYCLE,
        True,
        "freshness.lifecycle_blocked",
        "$.freshness",
        report_data,
    )


def _session_command(args: argparse.Namespace) -> CommandResult:
    try:
        route = _resolve_retrieval_route(args)
        command = args.command_path.split()[1]
        if command in {"checkpoint", "end"}:
            blocked = _lifecycle_audit(route, args.command_path)
            if blocked is not None:
                return blocked
        if command == "start":
            data = start_session(route.kb, cwd=args.cwd, agent=args.agent, profile=args.profile, native_id=args.native_id, parent_session_id=args.parent_session)
        elif command == "resume":
            data = resume_session(route.kb, args.session_id, native_id=args.native_id)
        elif command == "checkpoint":
            data = checkpoint_session(route.kb, args.session_id)
        elif command == "end":
            data = end_session(route.kb, args.session_id, exit_code=args.exit_code)
        else:
            data = recover_sessions(route.kb, lease_seconds=args.lease_seconds)
    except (RegistryError, SessionError) as exc:
        message = exc.remediation if isinstance(exc, RegistryError) else str(exc)
        return CommandResult(args.command_path, ResultStatus.VALIDATION_FAILURE, message, ExitCode.BLOCKED_LIFECYCLE, True, getattr(exc, "code", "session.lifecycle"), "$.session")
    return CommandResult(args.command_path, ResultStatus.SESSION, f"session {command} complete", ExitCode.SUCCESS, data=data)


def _checkpoint(args: argparse.Namespace) -> CommandResult:
    if not args.session:
        return CommandResult("checkpoint", ResultStatus.VALIDATION_FAILURE, "--session is required", ExitCode.VALIDATION, True, "session.required", "$.session")
    values = vars(args).copy()
    values.update(session_id=args.session, command_path="session checkpoint")
    namespace = argparse.Namespace(**values)
    result = _session_command(namespace)
    return CommandResult(
        "checkpoint", result.status, result.message, result.exit_code,
        result.error, result.error_code, result.error_field, result.data,
    )


def _bug_command(args: argparse.Namespace) -> CommandResult:
    try:
        route = _resolve_retrieval_route(args)
        command = args.command_path.split()[1]
        if command == "start":
            data = start_investigation(route.kb, session_id=args.session, symptom=args.symptom)
        elif command == "record":
            value: Any = args.value
            if args.file:
                text = args.file.read_text(encoding="utf-8")
                try:
                    value = json.loads(text)
                except json.JSONDecodeError:
                    value = text
            data = record_evidence(route.kb, args.investigation_id, args.kind, value)
        elif command == "status":
            data = status_investigation(route.kb, args.investigation_id, session_id=args.session)
        elif command == "block":
            data = block_investigation(route.kb, args.investigation_id, reason=args.reason)
        elif command == "resume":
            data = resume_investigation(route.kb, args.investigation_id, resolution=args.resolution)
        else:
            data = complete_investigation(route.kb, args.investigation_id)
    except (RegistryError, InvestigationError, OSError) as exc:
        message = exc.remediation if isinstance(exc, RegistryError) else str(exc)
        return CommandResult(args.command_path, ResultStatus.VALIDATION_FAILURE, message, ExitCode.BLOCKED_LIFECYCLE, True, getattr(exc, "code", "investigation.lifecycle"), "$.investigation")
    return CommandResult(args.command_path, ResultStatus.INVESTIGATION, f"investigation {command} complete", ExitCode.SUCCESS, data=data)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MigrationError("migration.manifest_invalid", "$", "manifest must be an object")
    return value


def _migrate_command(args: argparse.Namespace) -> CommandResult:
    command = args.command_path.split()[1]
    try:
        if command == "inventory":
            data: Any = {"schema_version": 1, "entries": list(migration_inventory(args.kb))}
            atomic_write(args.output, json.dumps(data, indent=2, sort_keys=True).encode("utf-8"))
        elif command == "plan":
            data = plan_migration(args.kb, scope=args.scope)
            atomic_write(args.output, json.dumps(data, indent=2, sort_keys=True).encode("utf-8"))
        elif command == "verify-plan":
            value = _load_json(args.manifest)
            result = verify_plan(value)
            data = {"manifest_hash": result.manifest_hash, "counts": result.counts, "print_hash": args.print_hash}
        elif command == "approve":
            value = _load_json(args.manifest)
            result = verify_plan(value)
            if result.manifest_hash != args.manifest_hash:
                raise MigrationError("migration.hash_mismatch", "$.manifest_hash", "manifest hash changed")
            data = record_migration_approval(
                args.kb,
                manifest_hash=result.manifest_hash,
                approved_by=args.approved_by,
                session_id=args.approval_session,
            )
        elif command == "apply":
            value = _load_json(args.manifest)
            data = apply_migration(args.kb, value, expected_hash=args.manifest_hash, approved_by=args.approved_by, approval_session=args.approval_session, receipt_out=args.receipt_out)
        else:
            value = _load_json(args.manifest)
            data = rollback_migration(args.kb, value, expected_hash=args.manifest_hash, receipt=args.receipt)
    except (MigrationError, OSError, json.JSONDecodeError) as exc:
        return CommandResult(args.command_path, ResultStatus.VALIDATION_FAILURE, str(exc), ExitCode.VALIDATION, True, getattr(exc, "code", "migration.failure"), getattr(exc, "field_path", "$.migration"))
    message = data["manifest_hash"] if command == "verify-plan" and args.print_hash else f"migration {command} complete"
    return CommandResult(args.command_path, ResultStatus.MIGRATED, message, ExitCode.SUCCESS, data=data)


def _configure_leaf(
    parser: argparse.ArgumentParser,
    *,
    command_path: str,
    owner: str,
) -> None:
    handler = {"init": _init, "index": _index, "validate": _validate, "search": _search, "show": _show, "related": _related, "context": _context, "status": _status, "audit": _audit, "stale": _stale, "checkpoint": _checkpoint, "propose": _propose, "review": _review, "promote": _promote, "deprecate": _deprecate}.get(command_path)
    if handler is None and command_path.startswith("session "):
        handler = _session_command
    if handler is None and command_path.startswith("bug "):
        handler = _bug_command
    if handler is None and command_path.startswith("migrate "):
        handler = _migrate_command
    if handler is None:
        handler = _not_implemented
    parser.set_defaults(
        handler=handler,
        command_path=command_path,
        owner=owner,
    )


def _add_json_argument(
    parser: argparse.ArgumentParser,
    *,
    include_default: bool = False,
) -> None:
    default = False if include_default else argparse.SUPPRESS
    parser.add_argument(
        "--json",
        action="store_true",
        default=default,
        help="emit a machine-readable JSON result",
    )


def _add_kb_argument(
    parser: argparse.ArgumentParser,
    *,
    required: bool = False,
) -> None:
    parser.add_argument("--kb", type=Path, required=required)


def _configure_top_level_grammar(
    command: str,
    parser: argparse.ArgumentParser,
) -> None:
    if command == "init":
        _add_kb_argument(parser)
        parser.add_argument("--project")
    elif command == "index":
        _add_kb_argument(parser)
        parser.add_argument("--rebuild", action="store_true")
    elif command == "validate":
        _add_kb_argument(parser)
        parser.add_argument("--strict", action="store_true")
    elif command == "search":
        parser.add_argument("query")
        _add_kb_argument(parser)
        parser.add_argument("--project")
        parser.add_argument("--type", dest="types", action="append")
        parser.add_argument("--component", dest="components", action="append")
        parser.add_argument(
            "--status",
            choices=("draft", "stable", "deprecated"),
        )
        parser.add_argument(
            "--freshness",
            choices=("fresh", "stale", "unknown"),
        )
        parser.add_argument("--include-draft", action="store_true")
        parser.add_argument("--include-deprecated", action="store_true")
        parser.add_argument("--limit", type=positive_int, default=10)
    elif command == "show":
        parser.add_argument("concept")
        _add_kb_argument(parser)
        parser.add_argument("--section", metavar="HEADING")
    elif command == "related":
        parser.add_argument("concept")
        _add_kb_argument(parser)
        parser.add_argument("--limit", type=positive_int, default=10)
    elif command == "context":
        parser.add_argument("query")
        _add_kb_argument(parser)
        parser.add_argument("--project")
        parser.add_argument("--component", dest="components", action="append")
        parser.add_argument("--budget", type=positive_int, required=True)
    elif command in {"status", "stale"}:
        _add_kb_argument(parser)
    elif command == "audit":
        _add_kb_argument(parser)
        parser.add_argument("--source-root", type=Path)
        parser.add_argument("--now")
    elif command == "checkpoint":
        _add_kb_argument(parser)
        parser.add_argument("--session")
    elif command == "propose":
        _add_kb_argument(parser)
        parser.add_argument("--target", required=True)
        parser.add_argument("--proposal-file", type=Path, required=True)
        parser.add_argument("--session", required=True)
    elif command == "review":
        parser.add_argument("subject")
        _add_kb_argument(parser)
        parser.add_argument("--target")
        parser.add_argument("--actor", required=True)
        parser.add_argument("--session", required=True)
        parser.add_argument(
            "--decision",
            choices=("accepted", "rejected", "superseded"),
            required=True,
        )
    elif command == "promote":
        parser.add_argument("proposal")
        _add_kb_argument(parser)
        parser.add_argument("--session", required=True)
    elif command == "deprecate":
        parser.add_argument("concept")
        _add_kb_argument(parser)
        parser.add_argument("--session", required=True)
        parser.add_argument("--proposal", required=True)


def _configure_session_grammar(
    command: str,
    parser: argparse.ArgumentParser,
) -> None:
    if command == "start":
        parser.add_argument("--cwd", type=Path, required=True)
        _add_kb_argument(parser)
        parser.add_argument("--agent", required=True)
        parser.add_argument("--profile", required=True)
        parser.add_argument("--native-id")
        parser.add_argument("--parent-session")
    elif command == "resume":
        parser.add_argument("session_id", nargs="?")
        parser.add_argument("--native-id")
        _add_kb_argument(parser)
    elif command == "checkpoint":
        parser.add_argument("session_id")
        _add_kb_argument(parser)
    elif command == "end":
        parser.add_argument("session_id")
        _add_kb_argument(parser)
        parser.add_argument("--exit-code", type=int, required=True)
    elif command == "recover":
        _add_kb_argument(parser)
        parser.add_argument("--lease-seconds", type=positive_int, default=300)


def _configure_bug_grammar(
    command: str,
    parser: argparse.ArgumentParser,
) -> None:
    if command == "start":
        parser.add_argument("--session", required=True)
        parser.add_argument("--symptom", required=True)
        _add_kb_argument(parser)
    elif command == "record":
        parser.add_argument("investigation_id")
        parser.add_argument("--kind", required=True)
        value_source = parser.add_mutually_exclusive_group(required=True)
        value_source.add_argument("--value")
        value_source.add_argument("--file", type=Path)
        _add_kb_argument(parser)
    elif command == "status":
        parser.add_argument("investigation_id", nargs="?")
        parser.add_argument("--session")
        _add_kb_argument(parser)
    elif command == "block":
        parser.add_argument("investigation_id")
        parser.add_argument("--reason", required=True)
        _add_kb_argument(parser)
    elif command == "resume":
        parser.add_argument("investigation_id")
        parser.add_argument("--resolution", required=True)
        _add_kb_argument(parser)
    elif command == "complete":
        parser.add_argument("investigation_id")
        _add_kb_argument(parser)


def _configure_migrate_grammar(
    command: str,
    parser: argparse.ArgumentParser,
) -> None:
    if command == "inventory":
        _add_kb_argument(parser, required=True)
        parser.add_argument("--output", type=Path, required=True)
    elif command == "plan":
        _add_kb_argument(parser, required=True)
        parser.add_argument("--scope")
        parser.add_argument("--output", type=Path, required=True)
    elif command == "verify-plan":
        parser.add_argument("manifest", type=Path)
        parser.add_argument("--print-hash", action="store_true")
    elif command == "approve":
        _add_kb_argument(parser, required=True)
        parser.add_argument("--manifest", type=Path, required=True)
        parser.add_argument("--manifest-hash", required=True)
        parser.add_argument("--approved-by", required=True)
        parser.add_argument("--approval-session", required=True)
    elif command == "apply":
        _add_kb_argument(parser, required=True)
        parser.add_argument("--manifest", type=Path, required=True)
        parser.add_argument("--manifest-hash", required=True)
        parser.add_argument("--approved-by", required=True)
        parser.add_argument("--approval-session", required=True)
        parser.add_argument("--receipt-out", type=Path, required=True)
    elif command == "rollback":
        _add_kb_argument(parser, required=True)
        parser.add_argument("--manifest", type=Path, required=True)
        parser.add_argument("--manifest-hash", required=True)
        parser.add_argument("--receipt", type=Path, required=True)


def _configure_nested_grammar(
    family: str,
    command: str,
    parser: argparse.ArgumentParser,
) -> None:
    if family == "session":
        _configure_session_grammar(command, parser)
    elif family == "bug":
        _configure_bug_grammar(command, parser)
    elif family == "migrate":
        _configure_migrate_grammar(command, parser)


def build_parser() -> KbArgumentParser:
    parser = KbArgumentParser(prog="kb", description="EOS knowledge base CLI")
    _add_json_argument(parser, include_default=True)
    commands = parser.add_subparsers(dest="command", required=True)

    for command, owner in COMMAND_OWNERSHIP.items():
        command_parser = commands.add_parser(command, help=f"{command} knowledge data")
        _add_json_argument(command_parser)
        nested = NESTED_COMMANDS.get(command)
        if nested is None:
            _configure_top_level_grammar(command, command_parser)
            _configure_leaf(
                command_parser,
                command_path=command,
                owner=owner,
            )
            continue

        nested_commands = command_parser.add_subparsers(
            dest=f"{command}_command",
            required=True,
        )
        for nested_command in nested:
            nested_parser = nested_commands.add_parser(nested_command)
            _add_json_argument(nested_parser)
            _configure_nested_grammar(command, nested_command, nested_parser)
            _configure_leaf(
                nested_parser,
                command_path=f"{command} {nested_command}",
                owner=owner,
            )

    return parser


def _render(result: CommandResult, *, as_json: bool, stream: TextIO) -> None:
    if as_json:
        payload = {
            "command": result.command,
            "exit_code": result.exit_code,
            "message": result.message,
            "status": result.status,
        }
        if result.error_code is not None:
            payload["error"] = {
                "code": result.error_code,
                "field_path": result.error_field,
            }
        if result.data is not None:
            payload["data"] = result.data
        print(json.dumps(payload, sort_keys=True), file=stream)
        return

    if result.status in {ResultStatus.INITIALIZED, ResultStatus.INDEXED, ResultStatus.VALIDATED}:
        print(result.message, file=stream)
    elif result.data is not None and not result.error:
        print(result.message, file=stream)
        if isinstance(result.data, list):
            for item in result.data:
                print(f"- {item.get('resource', item.get('relative_file'))}: {item.get('title', '')}", file=stream)
    elif result.error_code is not None:
        print(f"error[{result.error_code}]: {result.message}", file=stream)
    else:
        print(f"error[{result.status}]: {result.message}", file=stream)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a stable exit code without terminating Python."""

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except ParserExit as exc:
        if exc.message:
            stream = sys.stdout if exc.status == ExitCode.SUCCESS else sys.stderr
            print(exc.message, end="", file=stream)
        return int(exc.status)

    result = args.handler(args)
    stream = sys.stderr if result.error else sys.stdout
    _render(result, as_json=args.json, stream=stream)
    return int(result.exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
