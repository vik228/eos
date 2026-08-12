from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

import pytest

from eos_kb.cli import COMMAND_OWNERSHIP, ExitCode, build_parser, main
from eos_kb.config import WorkspaceRoute
from eos_kb.freshness import CoverageRule, FreshnessValidationError


PUBLIC_COMMANDS = (
    "init",
    "index",
    "validate",
    "search",
    "show",
    "related",
    "context",
    "status",
    "stale",
    "audit",
    "checkpoint",
    "propose",
    "review",
    "promote",
    "deprecate",
    "session",
    "bug",
    "migrate",
)

NESTED_COMMANDS = {
    "session": ("start", "resume", "checkpoint", "end", "recover"),
    "bug": ("start", "record", "status", "block", "resume", "complete"),
    "migrate": ("inventory", "plan", "verify-plan", "apply", "rollback"),
}


@pytest.fixture(autouse=True)
def isolated_kb_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))

VALID_LEAF_INVOCATIONS = (
    ("init", ("init", "--kb", "/tmp/kb", "--project", "eos", "--json")),
    ("index", ("index", "--kb", "/tmp/kb", "--rebuild", "--json")),
    ("validate", ("validate", "--kb", "/tmp/kb", "--strict", "--json")),
    (
        "search",
        (
            "search",
            "knowledge query",
            "--kb",
            "/tmp/kb",
            "--project",
            "eos",
            "--type",
            "concept",
            "--type",
            "decision",
            "--status",
            "stable",
            "--freshness",
            "fresh",
            "--include-draft",
            "--include-deprecated",
            "--limit",
            "25",
            "--json",
        ),
    ),
    ("show", ("show", "concept", "--kb", "/tmp/kb", "--section", "Usage", "--json")),
    ("related", ("related", "concept", "--kb", "/tmp/kb", "--limit", "5", "--json")),
    ("context", ("context", "query", "--kb", "/tmp/kb", "--budget", "100", "--json")),
    ("status", ("status", "--kb", "/tmp/kb", "--json")),
    ("stale", ("stale", "--kb", "/tmp/kb", "--json")),
    ("audit", ("audit", "--kb", "/tmp/kb", "--source-root", "/tmp/source", "--now", "2026-01-01T00:00:00+00:00", "--json")),
    ("checkpoint", ("checkpoint", "--kb", "/tmp/kb", "--session", "s1", "--json")),
    (
        "propose",
        (
            "propose",
            "--kb",
            "/tmp/kb",
            "--target",
            "concepts/example.md",
            "--proposal-file",
            "/tmp/proposal.yaml",
            "--session",
            "s1",
            "--json",
        ),
    ),
    (
        "review",
        (
            "review",
            "direct-change",
            "--kb",
            "/tmp/kb",
            "--actor",
            "vikas",
            "--session",
            "s1",
            "--decision",
            "accepted",
            "--json",
        ),
    ),
    ("promote", ("promote", "p1", "--kb", "/tmp/kb", "--session", "s1", "--json")),
    (
        "deprecate",
        (
            "deprecate",
            "concept",
            "--kb",
            "/tmp/kb",
            "--session",
            "s1",
            "--proposal",
            "p1",
            "--json",
        ),
    ),
    (
        "session start",
        (
            "session",
            "start",
            "--cwd",
            "/tmp/project",
            "--kb",
            "/tmp/kb",
            "--agent",
            "codex",
            "--profile",
            "personal",
            "--native-id",
            "native-1",
            "--parent-session",
            "parent-1",
            "--json",
        ),
    ),
    (
        "session resume",
        (
            "session",
            "resume",
            "s1",
            "--native-id",
            "native-1",
            "--kb",
            "/tmp/kb",
            "--json",
        ),
    ),
    ("session checkpoint", ("session", "checkpoint", "s1", "--kb", "/tmp/kb", "--json")),
    ("session end", ("session", "end", "s1", "--kb", "/tmp/kb", "--exit-code", "0", "--json")),
    (
        "session recover",
        (
            "session",
            "recover",
            "--kb",
            "/tmp/kb",
            "--lease-seconds",
            "600",
            "--json",
        ),
    ),
    (
        "bug start",
        (
            "bug",
            "start",
            "--session",
            "s1",
            "--symptom",
            "broken",
            "--kb",
            "/tmp/kb",
            "--json",
        ),
    ),
    (
        "bug record",
        (
            "bug",
            "record",
            "i1",
            "--kind",
            "note",
            "--value",
            "details",
            "--kb",
            "/tmp/kb",
            "--json",
        ),
    ),
    ("bug status", ("bug", "status", "i1", "--session", "s1", "--kb", "/tmp/kb", "--json")),
    ("bug block", ("bug", "block", "i1", "--reason", "waiting", "--kb", "/tmp/kb", "--json")),
    ("bug resume", ("bug", "resume", "i1", "--resolution", "fixed", "--kb", "/tmp/kb", "--json")),
    ("bug complete", ("bug", "complete", "i1", "--kb", "/tmp/kb", "--json")),
    (
        "migrate inventory",
        (
            "migrate",
            "inventory",
            "--kb",
            "/tmp/kb",
            "--output",
            "/tmp/inventory.json",
            "--json",
        ),
    ),
    (
        "migrate plan",
        (
            "migrate",
            "plan",
            "--kb",
            "/tmp/kb",
            "--scope",
            "personal",
            "--output",
            "/tmp/plan.json",
            "--json",
        ),
    ),
    (
        "migrate verify-plan",
        (
            "migrate",
            "verify-plan",
            "/tmp/manifest.json",
            "--print-hash",
            "--json",
        ),
    ),
    (
        "migrate apply",
        (
            "migrate",
            "apply",
            "--kb",
            "/tmp/kb",
            "--manifest",
            "/tmp/manifest.json",
            "--manifest-hash",
            "sha256:abc",
            "--approved-by",
            "vikas",
            "--approval-session",
            "s1",
            "--receipt-out",
            "/tmp/receipt.json",
            "--json",
        ),
    ),
    (
        "migrate approve",
        (
            "migrate",
            "approve",
            "--kb",
            "/tmp/kb",
            "--manifest",
            "/tmp/manifest.json",
            "--manifest-hash",
            "a" * 64,
            "--approved-by",
            "vikas",
            "--approval-session",
            "s1",
            "--json",
        ),
    ),
    (
        "migrate rollback",
        (
            "migrate",
            "rollback",
            "--kb",
            "/tmp/kb",
            "--manifest",
            "/tmp/manifest.json",
            "--manifest-hash",
            "sha256:abc",
            "--receipt",
            "/tmp/receipt.json",
            "--json",
        ),
    ),
)


def test_help_lists_every_public_command(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--help"])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.SUCCESS
    assert captured.err == ""
    for command in PUBLIC_COMMANDS:
        assert command in captured.out


@pytest.mark.parametrize(("command", "subcommands"), NESTED_COMMANDS.items())
def test_nested_help_lists_every_subcommand(
    command: str,
    subcommands: tuple[str, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([command, "--help"])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.SUCCESS
    assert captured.err == ""
    for subcommand in subcommands:
        assert subcommand in captured.out


def test_main_returns_usage_code_without_exiting(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.USAGE
    assert "usage:" in captured.err


@pytest.mark.parametrize(
    "argv",
    (
        ("--j", "status"),
        ("status", "--j"),
        ("session", "--j", "recover"),
        ("session", "recover", "--lease-s", "1"),
    ),
)
def test_abbreviated_options_are_usage_errors(
    argv: tuple[str, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(argv)

    captured = capsys.readouterr()
    assert exit_code == ExitCode.USAGE
    assert captured.out == ""
    assert "unrecognized arguments:" in captured.err


def test_status_missing_root_has_typed_validation_text_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["status"])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.VALIDATION
    assert captured.out == ""
    assert captured.err.startswith("error[registry.workspace_not_found]:")


def test_status_missing_root_has_typed_validation_json_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--json", "status"])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.VALIDATION
    result = json.loads(captured.err)
    assert result["command"] == "status"
    assert result["error"]["code"] == "registry.workspace_not_found"
    assert result["status"] == "validation_failure"
    assert captured.out == ""


@pytest.mark.parametrize(
    "argv",
    (
        ("status", "--json"),
        (
            "session",
            "--json",
            "start",
            "--cwd",
            "/tmp",
            "--agent",
            "codex",
            "--profile",
            "personal",
        ),
        (
            "session",
            "start",
            "--cwd",
            "/tmp",
            "--agent",
            "codex",
            "--profile",
            "personal",
            "--json",
        ),
    ),
)
def test_json_flag_is_accepted_at_the_command_that_owns_the_output(
    argv: tuple[str, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(argv)

    captured = capsys.readouterr()
    if argv[0] == "status":
        assert exit_code == ExitCode.VALIDATION
        assert json.loads(captured.err)["status"] == "validation_failure"
        assert captured.out == ""
    else:
        assert exit_code in (ExitCode.SUCCESS, ExitCode.VALIDATION, ExitCode.BLOCKED_LIFECYCLE)
        rendered = captured.out if exit_code == ExitCode.SUCCESS else captured.err
        assert json.loads(rendered)["command"] == "session start"


def test_exit_code_contract_is_reserved() -> None:
    assert {member.name: member.value for member in ExitCode} == {
        "SUCCESS": 0,
        "USAGE": 2,
        "VALIDATION": 3,
        "CONFLICT": 4,
        "BLOCKED_LIFECYCLE": 5,
        "RECOVERY_REQUIRED": 6,
    }


def test_command_ownership_covers_the_public_surface() -> None:
    assert tuple(COMMAND_OWNERSHIP) == PUBLIC_COMMANDS


@pytest.mark.parametrize(
    ("command_path", "argv"),
    VALID_LEAF_INVOCATIONS,
    ids=[item[0].replace(" ", "-") for item in VALID_LEAF_INVOCATIONS],
)
def test_every_leaf_accepts_its_frozen_grammar_before_placeholder_handler(
    command_path: str,
    argv: tuple[str, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(argv)

    captured = capsys.readouterr()
    if command_path == "init":
        assert exit_code == ExitCode.SUCCESS
        assert json.loads(captured.out) == {
            "command": "init",
            "exit_code": ExitCode.SUCCESS,
            "message": "initialized /tmp/kb (eos)",
            "status": "initialized",
        }
        assert captured.err == ""
        return
    if command_path == "index":
        assert exit_code in (ExitCode.SUCCESS, ExitCode.VALIDATION)
        rendered = captured.out if exit_code == ExitCode.SUCCESS else captured.err
        assert json.loads(rendered)["command"] == "index"
        return
    if command_path == "validate":
        assert exit_code in (ExitCode.SUCCESS, ExitCode.VALIDATION)
        if exit_code == ExitCode.SUCCESS:
            assert captured.err == ""
        return
    if command_path in {"search", "show", "related", "context", "status", "stale", "audit"}:
        assert exit_code in (ExitCode.SUCCESS, ExitCode.VALIDATION)
        rendered = captured.out if exit_code == ExitCode.SUCCESS else captured.err
        assert json.loads(rendered)["command"] == command_path
    else:
        assert exit_code in (
            ExitCode.SUCCESS,
            ExitCode.VALIDATION,
            ExitCode.CONFLICT,
            ExitCode.BLOCKED_LIFECYCLE,
            ExitCode.RECOVERY_REQUIRED,
        )
        rendered = captured.out if exit_code == ExitCode.SUCCESS else captured.err
        assert json.loads(rendered)["command"] == command_path


def test_parser_preserves_stable_types_defaults_and_repeatable_filters() -> None:
    parser = build_parser()

    search = parser.parse_args(
        [
            "search",
            "query",
            "--kb",
            "/tmp/kb",
            "--type",
            "concept",
            "--type",
            "decision",
        ]
    )
    related = parser.parse_args(["related", "concept"])
    recover = parser.parse_args(["session", "recover"])
    session_end = parser.parse_args(
        ["session", "end", "s1", "--exit-code", "-9"]
    )

    assert search.kb == Path("/tmp/kb")
    assert search.types == ["concept", "decision"]
    assert search.limit == 10
    assert related.limit == 10
    assert recover.lease_seconds == 300
    assert session_end.exit_code == -9


@pytest.mark.parametrize(
    ("argv", "persistence"),
    (
        (("checkpoint", "--kb", "{kb}", "--session", "s1", "--json"), "checkpoint"),
        (("session", "checkpoint", "s1", "--kb", "{kb}", "--json"), "checkpoint"),
        (("session", "end", "s1", "--kb", "{kb}", "--exit-code", "0", "--json"), "end"),
    ),
)
def test_lifecycle_commands_audit_declared_route_before_persistence(
    argv: tuple[str, ...],
    persistence: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    kb = tmp_path / "knowledge"
    workspace.mkdir()
    kb.mkdir()
    coverage = (CoverageRule(paths=("src/*.py",), concepts=("kb:demo/example",)),)
    route = WorkspaceRoute(workspace, kb, "demo", coverage=coverage)
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr("eos_kb.cli._resolve_retrieval_route", lambda args: route)

    def audit(root: Path, source_root: Path, *, coverage_rules: object = ()) -> SimpleNamespace:
        calls.append(("audit", (root, source_root, coverage_rules)))
        return SimpleNamespace(overall="fresh", warnings=(), contradictions=())

    def checkpoint(root: Path, session_id: str) -> dict[str, str]:
        calls.append(("checkpoint", (root, session_id)))
        return {"session_id": session_id, "state": "active"}

    def end(root: Path, session_id: str, *, exit_code: int) -> dict[str, object]:
        calls.append(("end", (root, session_id, exit_code)))
        return {"session_id": session_id, "state": "ended", "exit_code": exit_code}

    monkeypatch.setattr("eos_kb.cli.audit_freshness", audit)
    monkeypatch.setattr("eos_kb.cli.checkpoint_session", checkpoint)
    monkeypatch.setattr("eos_kb.cli.end_session", end)

    exit_code = main([item.replace("{kb}", str(kb)) for item in argv])

    assert exit_code == ExitCode.SUCCESS
    assert [kind for kind, _ in calls] == ["audit", persistence]
    assert calls[0][1] == (kb, workspace, coverage)
    assert json.loads(capsys.readouterr().out)["exit_code"] == ExitCode.SUCCESS


@pytest.mark.parametrize(
    ("argv", "audit_result"),
    (
        (
            ("checkpoint", "--kb", "{kb}", "--session", "s1", "--json"),
            SimpleNamespace(overall="stale", warnings=("source drift",), contradictions=()),
        ),
        (
            ("session", "checkpoint", "s1", "--kb", "{kb}", "--json"),
            SimpleNamespace(overall="fresh", warnings=("contradiction",), contradictions=("claim-1",)),
        ),
        (
            ("session", "end", "s1", "--kb", "{kb}", "--exit-code", "0", "--json"),
            FreshnessValidationError("freshness.index_missing", "$.index", "run kb index"),
        ),
    ),
)
def test_lifecycle_commands_block_before_persistence_for_invalid_audit(
    argv: tuple[str, ...],
    audit_result: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    kb = tmp_path / "knowledge"
    workspace.mkdir()
    kb.mkdir()
    route = WorkspaceRoute(workspace, kb, "demo")
    persisted = False

    monkeypatch.setattr("eos_kb.cli._resolve_retrieval_route", lambda args: route)

    def audit(*args: object, **kwargs: object) -> object:
        if isinstance(audit_result, Exception):
            raise audit_result
        return audit_result

    def must_not_persist(*args: object, **kwargs: object) -> None:
        nonlocal persisted
        persisted = True

    monkeypatch.setattr("eos_kb.cli.audit_freshness", audit)
    monkeypatch.setattr("eos_kb.cli.checkpoint_session", must_not_persist)
    monkeypatch.setattr("eos_kb.cli.end_session", must_not_persist)

    exit_code = main([item.replace("{kb}", str(kb)) for item in argv])

    result = json.loads(capsys.readouterr().err)
    assert exit_code == ExitCode.BLOCKED_LIFECYCLE
    assert result["exit_code"] == ExitCode.BLOCKED_LIFECYCLE
    assert result["error"]["code"] in {
        "freshness.lifecycle_blocked",
        "freshness.index_missing",
    }
    assert persisted is False


@pytest.mark.parametrize("command", ("checkpoint", "end"))
def test_lifecycle_allows_unknown_freshness_as_advisory(
    command: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    kb = tmp_path / "knowledge"
    workspace.mkdir()
    kb.mkdir()
    route = WorkspaceRoute(workspace, kb, "demo")
    persisted: list[str] = []
    report = SimpleNamespace(
        overall="unknown",
        warnings=("freshness unknown: kb:demo/index",),
        contradictions=(),
    )

    monkeypatch.setattr("eos_kb.cli._resolve_retrieval_route", lambda args: route)
    monkeypatch.setattr("eos_kb.cli.audit_freshness", lambda *args, **kwargs: report)
    monkeypatch.setattr(
        "eos_kb.cli.checkpoint_session",
        lambda *args, **kwargs: persisted.append("checkpoint") or {"state": "active"},
    )
    monkeypatch.setattr(
        "eos_kb.cli.end_session",
        lambda *args, **kwargs: persisted.append("end") or {"state": "ended"},
    )

    args = ["session", command, "s1", "--kb", str(kb), "--json"]
    if command == "end":
        args.extend(("--exit-code", "0"))

    assert main(args) == ExitCode.SUCCESS
    assert persisted == [command]


@pytest.mark.parametrize(
    "argv",
    (
        ("search",),
        ("context", "query"),
        ("propose", "--target", "resource"),
        ("review", "--actor", "vikas", "--session", "s1"),
        ("promote", "p1"),
        ("deprecate", "concept", "--session", "s1"),
        ("session", "start", "--cwd", "/tmp"),
        ("session", "checkpoint"),
        ("session", "end", "s1"),
        ("bug", "start", "--session", "s1"),
        ("bug", "block", "i1"),
        ("bug", "resume", "i1"),
        ("migrate", "inventory", "--output", "/tmp/out.json"),
        ("migrate", "plan", "--kb", "/tmp/kb"),
        ("migrate", "apply", "--kb", "/tmp/kb"),
        ("migrate", "rollback", "--kb", "/tmp/kb"),
    ),
)
def test_missing_required_grammar_is_rejected_by_parser(
    argv: tuple[str, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(argv)

    captured = capsys.readouterr()
    assert exit_code == ExitCode.USAGE
    assert captured.out == ""
    assert "error:" in captured.err
    assert "not_implemented" not in captured.err


@pytest.mark.parametrize(
    "argv",
    (
        ("search", "query", "--limit", "0"),
        ("search", "query", "--limit", "-1"),
        ("related", "concept", "--limit", "zero"),
        ("context", "query", "--budget", "0"),
        ("session", "recover", "--lease-seconds", "-5"),
        ("search", "query", "--status", "unknown"),
        ("search", "query", "--freshness", "old"),
        (
            "review",
            "p1",
            "--actor",
            "vikas",
            "--session",
            "s1",
            "--decision",
            "pending",
        ),
        ("session", "end", "s1", "--exit-code", "not-an-int"),
    ),
)
def test_invalid_typed_or_choice_arguments_are_rejected(
    argv: tuple[str, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(argv)

    captured = capsys.readouterr()
    assert exit_code == ExitCode.USAGE
    assert captured.out == ""
    assert "error:" in captured.err


@pytest.mark.parametrize(
    "value_args",
    (
        (),
        ("--value", "details", "--file", "/tmp/details.txt"),
    ),
)
def test_bug_record_requires_exactly_one_value_source(
    value_args: tuple[str, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(("bug", "record", "i1", "--kind", "note", *value_args))

    captured = capsys.readouterr()
    assert exit_code == ExitCode.USAGE
    assert captured.out == ""
    assert "error:" in captured.err


def test_bug_record_accepts_file_value_source(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        ("bug", "record", "i1", "--kind", "note", "--file", "/tmp/note.txt")
    )

    captured = capsys.readouterr()
    assert exit_code in (ExitCode.VALIDATION, ExitCode.BLOCKED_LIFECYCLE)
    assert captured.out == ""
    assert "registry.workspace_not_found" in captured.err
