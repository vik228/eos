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
        return SimpleNamespace(overall="fresh", warnings=(), contradictions=(), time=())

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
            SimpleNamespace(overall="stale", warnings=("source drift",), contradictions=(), time=()),
        ),
        (
            ("session", "checkpoint", "s1", "--kb", "{kb}", "--json"),
            SimpleNamespace(overall="fresh", warnings=("contradiction",), contradictions=("claim-1",), time=()),
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


def test_lifecycle_expiry_blocks_only_the_session_that_used_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from eos_kb.freshness import TimeFinding

    workspace = tmp_path / "workspace"
    kb = tmp_path / "knowledge"
    workspace.mkdir()
    kb.mkdir()
    route = WorkspaceRoute(workspace, kb, "demo")
    report = SimpleNamespace(
        overall="stale",
        warnings=(
            "freshness unknown: kb:demo/b",
            "time stale: kb:demo/a (2026-01-01T00:00:00+00:00)",
        ),
        contradictions=(),
        time=(TimeFinding("kb:demo/a", "2026-01-01T00:00:00+00:00", "stale"),),
    )

    monkeypatch.setattr("eos_kb.cli._resolve_retrieval_route", lambda args: route)
    monkeypatch.setattr("eos_kb.cli.audit_freshness", lambda *args, **kwargs: report)
    monkeypatch.setattr(
        "eos_kb.cli.session_used_resources", lambda root, session_id: {"kb:demo/a"} if session_id == "s-user" else set()
    )
    monkeypatch.setattr(
        "eos_kb.cli.checkpoint_session", lambda root, session_id: {"session_id": session_id, "state": "active"}
    )

    # The session that used the expired doc is blocked and sees no advisories.
    assert main(["session", "checkpoint", "s-user", "--kb", str(kb), "--json"]) == ExitCode.BLOCKED_LIFECYCLE
    result = json.loads(capsys.readouterr().err)
    assert result["error"]["code"] == "freshness.lifecycle_blocked"
    assert "time stale: kb:demo/a (2026-01-01T00:00:00+00:00)" in result["message"]
    assert "freshness unknown" not in result["message"]

    # A session that never used the doc passes: expiry is a warning, not a block.
    assert main(["session", "checkpoint", "s-other", "--kb", str(kb), "--json"]) == ExitCode.SUCCESS


def test_drift_on_unknown_named_path_still_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Kind-based matching: a drifted source blocks even when its path merely
    # contains the word "unknown".
    workspace = tmp_path / "workspace"
    kb = tmp_path / "knowledge"
    workspace.mkdir()
    kb.mkdir()
    route = WorkspaceRoute(workspace, kb, "demo")
    report = SimpleNamespace(
        overall="stale",
        warnings=("source drift: kb:demo/a (areas/unknown-hosts.md)",),
        contradictions=(),
        time=(),
    )

    monkeypatch.setattr("eos_kb.cli._resolve_retrieval_route", lambda args: route)
    monkeypatch.setattr("eos_kb.cli.audit_freshness", lambda *args, **kwargs: report)

    assert main(["session", "checkpoint", "s1", "--kb", str(kb), "--json"]) == ExitCode.BLOCKED_LIFECYCLE
    result = json.loads(capsys.readouterr().err)
    assert result["error"]["code"] == "freshness.lifecycle_blocked"
    assert "source drift: kb:demo/a (areas/unknown-hosts.md)" in result["message"]


def test_validate_text_output_includes_offending_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing"

    exit_code = main(["validate", "--kb", str(missing)])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.VALIDATION
    assert captured.out == ""
    assert "[freshness-gate.json]" in captured.err


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
        time=(),
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


def _write_gate_doc(kb: Path, relative: str, resource: str, **fields: object) -> None:
    merged: dict[str, object] = {"type": "Decision", "title": relative, "resource": resource}
    merged.update(fields)
    lines = ["---"]
    lines.extend(f"{key}: {json.dumps(value)}" for key, value in merged.items())
    lines.extend(["---", f"# {relative}", "Body text."])
    path = kb / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _gate_route(workspace: Path, kb: Path, monkeypatch: pytest.MonkeyPatch) -> WorkspaceRoute:
    route = WorkspaceRoute(workspace, kb, "demo")
    monkeypatch.setattr("eos_kb.cli._resolve_retrieval_route", lambda args: route)
    return route


def _content_hash(kb: Path, relative: str) -> str:
    from eos_kb.storage import state_directory

    manifest = json.loads((state_directory(kb) / "manifest.json").read_text(encoding="utf-8"))
    return next(item["content_hash"] for item in manifest["concepts"] if item["path"] == relative)


def _record_linked_review(kb: Path, target: str, content_hash: str, reviewed_at: str) -> None:
    from eos_kb.gate import record_review_event

    approvals = kb / ".eos" / "approvals.jsonl"
    approvals.parent.mkdir(parents=True, exist_ok=True)
    with approvals.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps({
                "schema_version": 1,
                "proposal_id": "p1",
                "actor": "test",
                "timestamp": reviewed_at,
                "proposal_hash": "sha256:" + "0" * 64,
                "base_target_hash": content_hash,
                "proposed_result_hash": content_hash,
                "decision": "accepted",
                "session_id": "s",
            })
            + "\n"
        )
    record_review_event(
        kb, target=target, content_hash=content_hash,
        proposal_id="p1", session_id="s", reviewed_at=reviewed_at,
    )


def _expired_tracked_kb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, body_suffix: str = "") -> tuple[Path, Path]:
    """KB with one expired tracked doc reviewed 2026-01-01, window 30d."""
    from eos_kb.indexer import index_bundle

    workspace = tmp_path / "workspace"
    kb = tmp_path / "knowledge"
    workspace.mkdir()
    kb.mkdir()
    _gate_route(workspace, kb, monkeypatch)
    _write_gate_doc(kb, "old.md", "kb:demo/old", freshness="tracked", review_every="30d")
    if body_suffix:
        with (kb / "old.md").open("a", encoding="utf-8") as stream:
            stream.write(body_suffix)
    index_bundle(kb)
    _record_linked_review(kb, "old.md", _content_hash(kb, "old.md"), "2026-01-01T00:00:00+00:00")
    return workspace, kb


def test_expired_tracked_blocks_only_the_session_that_used_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from eos_kb.sessions import start_session

    workspace, kb = _expired_tracked_kb(tmp_path, monkeypatch, body_suffix="\nuniquetoken\n")
    user = start_session(kb, cwd=workspace, agent="codex", profile="demo", session_id="s-user")
    other = start_session(kb, cwd=workspace, agent="codex", profile="demo", session_id="s-other")
    assert user["session_id"] == "s-user" and other["session_id"] == "s-other"

    # The using session retrieves the doc through kb search ...
    monkeypatch.setenv("EOS_AGENT_SESSION_ID", "s-user")
    assert main(["search", "uniquetoken", "--kb", str(kb), "--json"]) == ExitCode.SUCCESS
    capsys.readouterr()
    # ... so its checkpoint is blocked by the expiry it saw.
    assert main(["session", "checkpoint", "s-user", "--kb", str(kb), "--json"]) == ExitCode.BLOCKED_LIFECYCLE
    blocked = json.loads(capsys.readouterr().err)
    assert blocked["error"]["code"] == "freshness.lifecycle_blocked"
    assert "time stale: kb:demo/old" in blocked["message"]
    # The other session never used the doc: warning only, checkpoint passes.
    assert main(["session", "checkpoint", "s-other", "--kb", str(kb), "--json"]) == ExitCode.SUCCESS


def test_direct_read_blocks_using_session_via_used_resource(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from eos_kb.sessions import start_session

    workspace, kb = _expired_tracked_kb(tmp_path, monkeypatch)
    start_session(kb, cwd=workspace, agent="codex", profile="demo", session_id="s-user")

    exit_code = main([
        "session", "checkpoint", "s-user", "--kb", str(kb),
        "--used-resource", "kb:demo/old", "--json",
    ])
    assert exit_code == ExitCode.BLOCKED_LIFECYCLE
    blocked = json.loads(capsys.readouterr().err)
    assert blocked["error"]["code"] == "freshness.lifecycle_blocked"
    assert "time stale: kb:demo/old" in blocked["message"]


def test_contradiction_and_drift_block_every_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from types import SimpleNamespace as Namespace

    from eos_kb.freshness import Contradiction, TimeFinding

    workspace = tmp_path / "workspace"
    kb = tmp_path / "knowledge"
    workspace.mkdir()
    kb.mkdir()
    _gate_route(workspace, kb, monkeypatch)

    drift = Namespace(
        overall="stale",
        warnings=("source drift: kb:demo/a (src/a.py)",),
        contradictions=(),
        time=(),
    )
    monkeypatch.setattr("eos_kb.cli.audit_freshness", lambda *args, **kwargs: drift)
    assert main(["session", "checkpoint", "s-unused", "--kb", str(kb), "--json"]) == ExitCode.BLOCKED_LIFECYCLE
    assert "source drift" in json.loads(capsys.readouterr().err)["message"]

    contradiction = Namespace(
        overall="stale",
        warnings=("contradiction: demo:mode",),
        contradictions=(Contradiction("demo", "mode", ("kb:demo/a", "kb:demo/b"), ('"one"', '"two"')),),
        time=(TimeFinding("kb:demo/old", "2026-01-31T00:00:00+00:00", "stale"),),
    )
    monkeypatch.setattr("eos_kb.cli.audit_freshness", lambda *args, **kwargs: contradiction)
    assert main(["session", "checkpoint", "s-unused", "--kb", str(kb), "--json"]) == ExitCode.BLOCKED_LIFECYCLE
    assert "contradiction" in json.loads(capsys.readouterr().err)["message"]


def test_usage_log_disabled_retrieval_still_blocks_via_session_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from eos_kb.sessions import session_used_resources, start_session

    workspace, kb = _expired_tracked_kb(tmp_path, monkeypatch, body_suffix="\nuniquetoken\n")
    start_session(kb, cwd=workspace, agent="codex", profile="demo", session_id="s-user")
    monkeypatch.setenv("EOS_AGENT_SESSION_ID", "s-user")
    monkeypatch.setenv("EOS_KB_USAGE_LOG", "0")

    assert main(["search", "uniquetoken", "--kb", str(kb), "--json"]) == ExitCode.SUCCESS
    capsys.readouterr()
    # The usage log wrote nothing, but the session record captured the card.
    assert session_used_resources(kb, "s-user") == {"kb:demo/old"}
    assert main(["session", "checkpoint", "s-user", "--kb", str(kb), "--json"]) == ExitCode.BLOCKED_LIFECYCLE
    assert "time stale: kb:demo/old" in json.loads(capsys.readouterr().err)["message"]


def test_show_records_use_and_related_does_not(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from eos_kb.sessions import session_used_resources, start_session

    workspace, kb = _expired_tracked_kb(tmp_path, monkeypatch)
    start_session(kb, cwd=workspace, agent="codex", profile="demo", session_id="s-user")
    monkeypatch.setenv("EOS_AGENT_SESSION_ID", "s-user")

    assert main(["show", "kb:demo/old", "--kb", str(kb), "--json"]) == ExitCode.SUCCESS
    capsys.readouterr()
    assert session_used_resources(kb, "s-user") == {"kb:demo/old"}

    # Related suggestions are not reads: they must not mark the session.
    start_session(kb, cwd=workspace, agent="codex", profile="demo", session_id="s-related")
    monkeypatch.setenv("EOS_AGENT_SESSION_ID", "s-related")
    assert main(["related", "kb:demo/old", "--kb", str(kb), "--json"]) == ExitCode.SUCCESS
    capsys.readouterr()
    assert session_used_resources(kb, "s-related") == set()


def test_session_end_blocked_by_used_expiry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from eos_kb.sessions import start_session

    workspace, kb = _expired_tracked_kb(tmp_path, monkeypatch)
    start_session(kb, cwd=workspace, agent="codex", profile="demo", session_id="s-user")

    assert main([
        "session", "checkpoint", "s-user", "--kb", str(kb),
        "--used-resource", "kb:demo/old", "--json",
    ]) == ExitCode.BLOCKED_LIFECYCLE
    capsys.readouterr()
    assert main(["session", "end", "s-user", "--kb", str(kb), "--exit-code", "0", "--json"]) == ExitCode.BLOCKED_LIFECYCLE
    assert "time stale: kb:demo/old" in json.loads(capsys.readouterr().err)["message"]


def test_top_level_checkpoint_used_resource_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from eos_kb.sessions import session_used_resources, start_session

    workspace, kb = _expired_tracked_kb(tmp_path, monkeypatch)
    start_session(kb, cwd=workspace, agent="codex", profile="demo", session_id="s-user")

    # A repo-relative path maps to the card resource through the index.
    # Leading ./ segments normalize to the same entry.
    assert main([
        "checkpoint", "--kb", str(kb), "--session", "s-user",
        "--used-resource", "./old.md", "--json",
    ]) == ExitCode.BLOCKED_LIFECYCLE
    assert "time stale: kb:demo/old" in json.loads(capsys.readouterr().err)["message"]
    assert session_used_resources(kb, "s-user") == {"old.md", "kb:demo/old"}


def test_used_resource_rejects_escapes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from eos_kb.sessions import start_session

    workspace, kb = _expired_tracked_kb(tmp_path, monkeypatch)
    start_session(kb, cwd=workspace, agent="codex", profile="demo", session_id="s-user")

    for bad in ("../escape.md", "/etc/passwd", "a/../../b.md"):
        assert main([
            "session", "checkpoint", "s-user", "--kb", str(kb),
            "--used-resource", bad, "--json",
        ]) == ExitCode.VALIDATION
        result = json.loads(capsys.readouterr().err)
        assert result["error"]["code"] == "session.invalid_used_resource"


def test_real_audit_drift_and_contradiction_block_every_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from eos_kb.indexer import index_bundle
    from eos_kb.sessions import start_session

    workspace = tmp_path / "workspace"
    kb = tmp_path / "knowledge"
    workspace.mkdir()
    kb.mkdir()
    _gate_route(workspace, kb, monkeypatch)
    claims_a = {"project": "demo", "claims": [{"id": "mode", "value": "one"}]}
    claims_b = {"project": "demo", "claims": [{"id": "mode", "value": "two"}]}
    _write_gate_doc(kb, "a.md", "kb:demo/a", eos=claims_a)
    _write_gate_doc(kb, "b.md", "kb:demo/b", eos=claims_b)
    index_bundle(kb)
    start_session(kb, cwd=workspace, agent="codex", profile="demo", session_id="s-fresh")

    assert main(["session", "checkpoint", "s-fresh", "--kb", str(kb), "--json"]) == ExitCode.BLOCKED_LIFECYCLE
    assert "contradiction" in json.loads(capsys.readouterr().err)["message"]


def test_real_audit_source_drift_blocks_unused_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import subprocess

    from eos_kb.indexer import index_bundle
    from eos_kb.sessions import start_session

    # The gate audits the workspace as the source root, so the workspace
    # itself is the git repo whose revision the doc pins.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=workspace, check=True)
    (workspace / "src").mkdir()
    (workspace / "src" / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=workspace, check=True)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=workspace, check=True, capture_output=True, text=True
    ).stdout.strip()

    kb = tmp_path / "knowledge"
    kb.mkdir()
    _gate_route(workspace, kb, monkeypatch)
    _write_gate_doc(
        kb, "svc.md", "kb:demo/svc",
        eos={"project": "demo", "source_paths": ["src/a.py"], "source_revision": revision},
    )
    index_bundle(kb)
    start_session(kb, cwd=workspace, agent="codex", profile="demo", session_id="s-fresh")
    (workspace / "src" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")

    assert main(["session", "checkpoint", "s-fresh", "--kb", str(kb), "--json"]) == ExitCode.BLOCKED_LIFECYCLE
    assert "source drift" in json.loads(capsys.readouterr().err)["message"]
