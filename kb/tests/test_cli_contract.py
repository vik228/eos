from __future__ import annotations

import argparse
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from eos_kb.cli import (
    COMMAND_OWNERSHIP,
    NESTED_COMMANDS,
    ExitCode,
    ParserExit,
    build_parser,
    main,
)
from eos_kb.indexer import index_bundle
from eos_kb.freshness import audit_freshness


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cli"
CASE_NAMES = {"success", "validation_failure", "recovery", "output_shape"}
LIVE_CONTRACT_OWNERS = {"Task 7", "Task 8", "Task 9", "Task 13"}
GOLDEN_FIELDS = {"argv", "exit_code", "stdout", "stderr"}
TOP_LEVEL_FIELDS = {
    "schema_version",
    "command",
    "command_path",
    "owner",
    "argv",
    "cases",
}


@dataclass(frozen=True)
class Contract:
    path: Path
    command: str
    command_path: tuple[str, ...]
    owner: str
    argv: tuple[str, ...]
    cases: dict[str, dict[str, Any]]


def parse_contract(path: Path, payload: Any) -> Contract:
    if not isinstance(payload, dict) or set(payload) != TOP_LEVEL_FIELDS:
        raise ValueError(f"{path}: malformed top-level contract fields")
    if payload["schema_version"] != 1:
        raise ValueError(f"{path}: unsupported schema_version")

    command = payload["command"]
    command_path = payload["command_path"]
    argv = payload["argv"]
    if not isinstance(command, str):
        raise ValueError(f"{path}: command must be a string")
    if not (
        isinstance(command_path, list)
        and command_path
        and all(isinstance(item, str) for item in command_path)
    ):
        raise ValueError(f"{path}: command_path must be a non-empty string list")
    if command_path[0] != command:
        raise ValueError(f"{path}: command_path must start with command")
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        raise ValueError(f"{path}: argv must be a string list")
    if argv[: len(command_path)] != command_path:
        raise ValueError(f"{path}: argv must start with command_path")
    if not isinstance(payload["owner"], str) or not isinstance(payload["cases"], dict):
        raise ValueError(f"{path}: owner and cases have invalid types")

    return Contract(
        path=path,
        command=command,
        command_path=tuple(command_path),
        owner=payload["owner"],
        argv=tuple(argv),
        cases=payload["cases"],
    )


def load_contracts() -> tuple[Contract, ...]:
    contracts = []
    for path in sorted(FIXTURE_DIR.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text())
        contracts.append(parse_contract(path, payload))
    command_paths = [contract.command_path for contract in contracts]
    if len(command_paths) != len(set(command_paths)):
        raise ValueError("duplicate executable command_path in CLI contracts")
    return tuple(contracts)


CONTRACTS = load_contracts()


@pytest.fixture(autouse=True)
def isolated_task4_cli_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))


def materialize_temp_paths(value: Any, tmp_path: Path) -> Any:
    if isinstance(value, str):
        return value.replace("${TMP}", str(tmp_path))
    if isinstance(value, list):
        return [materialize_temp_paths(item, tmp_path) for item in value]
    if isinstance(value, dict):
        return {
            key: materialize_temp_paths(item, tmp_path)
            for key, item in value.items()
        }
    return value


def prepare_task4_success(golden: dict[str, Any]) -> None:
    if golden["exit_code"] != ExitCode.SUCCESS:
        return
    argv = golden["argv"]
    command = next((item for item in argv if item in {"index", "validate"}), None)
    if command is None:
        return
    kb_index = argv.index("--kb") + 1
    root = Path(argv[kb_index])
    root.mkdir(parents=True, exist_ok=True)
    if command == "validate":
        report = index_bundle(root)
        if report.connection is not None:
            report.connection.close()
        assert report.errors == []


def prepare_task5_success(golden: dict[str, Any]) -> None:
    argv = golden["argv"]
    command = next((item for item in argv if item in {"search", "show", "related", "context", "status"}), None)
    if command is None or "--kb" not in argv:
        return
    root = Path(argv[argv.index("--kb") + 1])
    if root.name != "index":
        return
    root.mkdir(parents=True, exist_ok=True)
    concept = root / "concept.md"
    concept.write_text(
        "---\ntype: Decision\ntitle: Concept\nresource: kb:test/concept\n---\n# Usage\nA bounded retrieval fixture.\n",
        encoding="utf-8",
    )
    index_bundle(root)


def prepare_task6_success(golden: dict[str, Any]) -> None:
    if golden["exit_code"] != ExitCode.SUCCESS:
        return
    argv = golden["argv"]
    command = next((item for item in argv if item in {"audit", "stale"}), None)
    if command is None or "--kb" not in argv:
        return
    root = Path(argv[argv.index("--kb") + 1])
    if root.name != "index":
        return
    root.mkdir(parents=True, exist_ok=True)
    report = index_bundle(root)
    if report.connection is not None:
        report.connection.close()
    source_root = (
        Path(argv[argv.index("--source-root") + 1])
        if "--source-root" in argv
        else root.parent / "source"
    )
    source_root.mkdir(parents=True, exist_ok=True)
    now = datetime.fromisoformat(
        argv[argv.index("--now") + 1]
        if "--now" in argv
        else "2026-01-01T00:00:00+00:00"
    )
    audit_freshness(root, source_root, now=now)


def is_complete_golden(
    case: Any,
    *,
    extra_fields: set[str] | None = None,
) -> bool:
    if not isinstance(case, dict):
        return False
    expected_fields = GOLDEN_FIELDS | (extra_fields or set())
    return (
        set(case) == expected_fields
        and isinstance(case["argv"], list)
        and all(isinstance(item, str) for item in case["argv"])
        and isinstance(case["exit_code"], int)
        and isinstance(case["stdout"], str)
        and isinstance(case["stderr"], str)
    )


def assert_golden_command_path(
    contract: Contract,
    golden: dict[str, Any],
) -> argparse.Namespace:
    try:
        args = build_parser().parse_args(golden["argv"])
    except ParserExit as exc:
        raise AssertionError(
            f"{contract.path}: golden argv must satisfy the public parser"
        ) from exc

    resolved = tuple(args.command_path.split())
    assert resolved == contract.command_path, (
        f"{contract.path}: golden argv resolved command_path {resolved}, "
        f"expected {contract.command_path}"
    )
    return args


def assert_valid_recovery_case(
    contract: Contract,
    recovery_case: dict[str, Any],
) -> None:
    error = (
        "recovery case must be a complete golden or declare "
        "recovery: not_applicable"
    )
    if recovery_case.get("recovery") == "not_applicable":
        assert set(recovery_case) in (
            {"recovery"},
            {"placeholder", "recovery"},
        ), error
        return

    assert "recovery" not in recovery_case, error
    assert not recovery_case.get("placeholder", False), error
    assert is_complete_golden(recovery_case), error
    assert recovery_case["exit_code"] in (
        ExitCode.SUCCESS,
        ExitCode.RECOVERY_REQUIRED,
    ), error
    assert_golden_command_path(contract, recovery_case)


def assert_placeholder_case(case_name: str, case: dict[str, Any]) -> None:
    if case_name == "recovery":
        assert case == {"placeholder": True, "recovery": "not_applicable"}
    elif case_name == "output_shape":
        assert case == {"placeholder": True, "formats": ["text", "json"]}
    else:
        assert case == {"placeholder": True}


def assert_output_shape_case(contract: Contract, case: dict[str, Any]) -> None:
    assert set(case) == {"variants"}
    variants = case["variants"]
    assert isinstance(variants, list) and len(variants) == 2
    assert all(
        is_complete_golden(variant, extra_fields={"format"})
        for variant in variants
    )
    by_format = {variant["format"]: variant for variant in variants}
    assert set(by_format) == {"text", "json"}
    text_args = assert_golden_command_path(contract, by_format["text"])
    json_args = assert_golden_command_path(contract, by_format["json"])
    assert text_args.json is False, (
        "text output_shape must parse without --json enabled"
    )
    assert json_args.json is True, (
        "json output_shape must parse with --json enabled"
    )
    json.loads(by_format["json"]["stdout"])


def assert_valid_contract_fixture(contract: Contract) -> None:
    assert set(contract.cases) == CASE_NAMES
    assert contract.owner == COMMAND_OWNERSHIP[contract.command]
    for case_name, case in contract.cases.items():
        assert isinstance(case, dict)
        if case.get("placeholder", False):
            assert_placeholder_case(case_name, case)
        elif case_name == "success":
            assert is_complete_golden(case)
            assert case["exit_code"] == ExitCode.SUCCESS
            assert_golden_command_path(contract, case)
        elif case_name == "validation_failure":
            assert is_complete_golden(case)
            assert case["exit_code"] == ExitCode.VALIDATION
            assert_golden_command_path(contract, case)
        elif case_name == "recovery":
            assert_valid_recovery_case(contract, case)
        else:
            assert_output_shape_case(contract, case)


def contract_with_recovery_case(recovery_case: dict[str, Any]) -> Contract:
    return Contract(
        path=Path("session-recover.yaml"),
        command="session",
        command_path=("session", "recover"),
        owner="Task 8",
        argv=("session", "recover"),
        cases={
            "success": {"placeholder": True},
            "validation_failure": {"placeholder": True},
            "recovery": recovery_case,
            "output_shape": {
                "placeholder": True,
                "formats": ["text", "json"],
            },
        },
    )


@pytest.mark.parametrize(
    "recovery_case",
    (
        {"recovery": "not_applicable"},
        {
            "argv": ["session", "recover"],
            "exit_code": ExitCode.RECOVERY_REQUIRED,
            "stdout": "recovery required\n",
            "stderr": "",
        },
    ),
)
def test_recovery_schema_accepts_supported_alternatives(
    recovery_case: dict[str, Any],
) -> None:
    assert_valid_contract_fixture(contract_with_recovery_case(recovery_case))


@pytest.mark.parametrize(
    "recovery_case",
    (
        {},
        {"placeholder": True},
        {"recovery": "supported"},
        {"recovery": None},
        {"argv": ["session", "recover"], "exit_code": ExitCode.SUCCESS},
        {
            "recovery": "not_applicable",
            "argv": ["session", "recover"],
            "exit_code": ExitCode.SUCCESS,
            "stdout": "recovered\n",
            "stderr": "",
        },
    ),
)
def test_recovery_schema_rejects_missing_incomplete_or_invalid_metadata(
    recovery_case: dict[str, Any],
) -> None:
    with pytest.raises(AssertionError):
        assert_valid_contract_fixture(contract_with_recovery_case(recovery_case))


def complete_golden_contract() -> Contract:
    return Contract(
        path=Path("status.yaml"),
        command="status",
        command_path=("status",),
        owner="Task 5",
        argv=("status",),
        cases={
            "success": {
                "argv": ["status"],
                "exit_code": ExitCode.SUCCESS,
                "stdout": "ok\n",
                "stderr": "",
            },
            "validation_failure": {
                "argv": ["status", "--kb", "missing"],
                "exit_code": ExitCode.VALIDATION,
                "stdout": "",
                "stderr": "invalid knowledge base\n",
            },
            "recovery": {"recovery": "not_applicable"},
            "output_shape": {
                "variants": [
                    {
                        "format": "text",
                        "argv": ["status"],
                        "exit_code": ExitCode.SUCCESS,
                        "stdout": "ok\n",
                        "stderr": "",
                    },
                    {
                        "format": "json",
                        "argv": ["status", "--json"],
                        "exit_code": ExitCode.SUCCESS,
                        "stdout": '{"status": "ok"}\n',
                        "stderr": "",
                    },
                ]
            },
        },
    )


def test_complete_golden_semantics_accept_contract_required_shapes() -> None:
    assert_valid_contract_fixture(complete_golden_contract())


def test_complete_golden_rejects_argv_for_another_command() -> None:
    contract = complete_golden_contract()
    cases = deepcopy(contract.cases)
    cases["success"]["argv"] = ["stale"]
    malformed = Contract(
        path=contract.path,
        command=contract.command,
        command_path=contract.command_path,
        owner=contract.owner,
        argv=contract.argv,
        cases=cases,
    )

    with pytest.raises(AssertionError, match="command_path"):
        assert_valid_contract_fixture(malformed)


@pytest.mark.parametrize(
    ("variant_index", "argv"),
    (
        (0, ["status", "--json"]),
        (1, ["status"]),
    ),
)
def test_output_shape_rejects_argv_that_contradicts_format(
    variant_index: int,
    argv: list[str],
) -> None:
    contract = complete_golden_contract()
    cases = deepcopy(contract.cases)
    cases["output_shape"]["variants"][variant_index]["argv"] = argv
    malformed = Contract(
        path=contract.path,
        command=contract.command,
        command_path=contract.command_path,
        owner=contract.owner,
        argv=contract.argv,
        cases=cases,
    )

    with pytest.raises(AssertionError, match="--json"):
        assert_valid_contract_fixture(malformed)


def test_text_output_shape_rejects_abbreviated_json_flag() -> None:
    contract = complete_golden_contract()
    cases = deepcopy(contract.cases)
    cases["output_shape"]["variants"][0]["argv"] = ["status", "--j"]
    malformed = Contract(
        path=contract.path,
        command=contract.command,
        command_path=contract.command_path,
        owner=contract.owner,
        argv=contract.argv,
        cases=cases,
    )

    with pytest.raises(AssertionError, match="public parser"):
        assert_valid_contract_fixture(malformed)


@pytest.mark.parametrize(
    ("case_name", "replacement"),
    (
        (
            "success",
            {
                "argv": ["status"],
                "exit_code": ExitCode.USAGE,
                "stdout": "not implemented\n",
                "stderr": "",
            },
        ),
        (
            "validation_failure",
            {
                "argv": ["status"],
                "exit_code": ExitCode.USAGE,
                "stdout": "",
                "stderr": "usage\n",
            },
        ),
        (
            "recovery",
            {
                "argv": ["status"],
                "exit_code": ExitCode.USAGE,
                "stdout": "pending\n",
                "stderr": "",
            },
        ),
        (
            "output_shape",
            {
                "variants": [
                    {
                        "format": "text",
                        "argv": ["status"],
                        "exit_code": ExitCode.SUCCESS,
                        "stdout": "ok\n",
                        "stderr": "",
                    }
                ]
            },
        ),
        (
            "output_shape",
            {
                "variants": [
                    {
                        "format": "text",
                        "argv": ["status"],
                        "exit_code": ExitCode.SUCCESS,
                        "stdout": "ok\n",
                        "stderr": "",
                    },
                    {
                        "format": "json",
                        "argv": ["status", "--json"],
                        "exit_code": ExitCode.SUCCESS,
                        "stdout": "not-json\n",
                        "stderr": "",
                    },
                ]
            },
        ),
        (
            "success",
            {
                "placeholder": True,
                "argv": ["status"],
                "exit_code": ExitCode.SUCCESS,
                "stdout": "ok\n",
                "stderr": "",
            },
        ),
    ),
)
def test_golden_semantics_reject_contradictory_or_malformed_cases(
    case_name: str,
    replacement: dict[str, Any],
) -> None:
    contract = complete_golden_contract()
    cases = deepcopy(contract.cases)
    cases[case_name] = replacement
    malformed = Contract(
        path=contract.path,
        command=contract.command,
        command_path=contract.command_path,
        owner=contract.owner,
        argv=contract.argv,
        cases=cases,
    )

    with pytest.raises((AssertionError, ValueError)):
        assert_valid_contract_fixture(malformed)


def test_contract_fixtures_cover_every_executable_leaf_path() -> None:
    expected = {
        (command,)
        for command in COMMAND_OWNERSHIP
        if command not in NESTED_COMMANDS
    }
    expected.update(
        (command, nested)
        for command, nested_commands in NESTED_COMMANDS.items()
        for nested in nested_commands
    )
    actual = set()
    for fixture_path in FIXTURE_DIR.glob("*.yaml"):
        payload = yaml.safe_load(fixture_path.read_text())
        actual.add(tuple(payload.get("command_path", [payload["command"]])))

    assert actual == expected


def valid_fixture_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "command": "status",
        "command_path": ["status"],
        "owner": "Task 5",
        "argv": ["status"],
        "cases": {
            "success": {"placeholder": True},
            "validation_failure": {"placeholder": True},
            "recovery": {
                "placeholder": True,
                "recovery": "not_applicable",
            },
            "output_shape": {
                "placeholder": True,
                "formats": ["text", "json"],
            },
        },
    }


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload.pop("schema_version"),
        lambda payload: payload.update(schema_version=2),
        lambda payload: payload.update(unexpected=True),
        lambda payload: payload.pop("owner"),
    ),
)
def test_loader_rejects_invalid_schema_version_or_top_level_fields(
    mutation: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = valid_fixture_payload()
    mutation(payload)
    (tmp_path / "status.yaml").write_text(yaml.safe_dump(payload))
    monkeypatch.setattr("test_cli_contract.FIXTURE_DIR", tmp_path)

    with pytest.raises(ValueError):
        load_contracts()


@pytest.mark.parametrize(
    "contract",
    CONTRACTS,
    ids=lambda item: "-".join(item.command_path),
)
def test_contract_fixture_has_all_four_cases(contract: Contract) -> None:
    assert_valid_contract_fixture(contract)


def assert_checked_in_golden(
    golden: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    golden = materialize_temp_paths(golden, tmp_path)
    prepare_task4_success(golden)
    prepare_task5_success(golden)
    prepare_task6_success(golden)
    exit_code = main(golden["argv"])
    captured = capsys.readouterr()

    assert exit_code == golden["exit_code"]
    assert captured.out == golden["stdout"]
    assert captured.err == golden["stderr"]


@pytest.mark.parametrize(
    "contract",
    CONTRACTS,
    ids=lambda item: "-".join(item.command_path),
)
@pytest.mark.parametrize("case_name", sorted(CASE_NAMES))
def test_placeholder_golden_case(
    contract: Contract,
    case_name: str,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    case = contract.cases[case_name]
    if contract.owner in LIVE_CONTRACT_OWNERS and case.get("placeholder", False):
        if case_name == "recovery" and case.get("recovery") == "not_applicable":
            return
        exit_code = main(["--json", *contract.argv])
        captured = capsys.readouterr()
        rendered = captured.out or captured.err
        result = json.loads(rendered)
        assert result["command"] == " ".join(contract.command_path)
        assert exit_code in {
            ExitCode.SUCCESS,
            ExitCode.VALIDATION,
            ExitCode.CONFLICT,
            ExitCode.BLOCKED_LIFECYCLE,
            ExitCode.RECOVERY_REQUIRED,
        }
        assert result["status"] != "not_implemented"
        return
    if not case.get("placeholder", False):
        if case_name == "recovery" and case.get("recovery") == "not_applicable":
            return
        variants = case.get("variants", [case])
        for golden in variants:
            assert_checked_in_golden(golden, capsys, tmp_path)
        return

    exit_code = main(list(contract.argv))
    captured = capsys.readouterr()

    assert exit_code == ExitCode.USAGE
    assert captured.out == (
        f"error[not_implemented]: command '{' '.join(contract.command_path)}' "
        f"is owned by {contract.owner}\n"
    )
    assert captured.err == ""


@pytest.mark.parametrize(
    "contract",
    CONTRACTS,
    ids=lambda item: "-".join(item.command_path),
)
def test_placeholder_output_shape_has_text_and_json(
    contract: Contract,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = contract.cases["output_shape"]
    if contract.owner in LIVE_CONTRACT_OWNERS and case.get("placeholder", False):
        text_exit_code = main(list(contract.argv))
        text_output = capsys.readouterr()
        json_exit_code = main(["--json", *contract.argv])
        json_output = capsys.readouterr()
        assert text_exit_code == json_exit_code
        assert (text_output.out or text_output.err).strip()
        result = json.loads(json_output.out or json_output.err)
        assert result["command"] == " ".join(contract.command_path)
        assert result["status"] != "not_implemented"
        return
    if not case.get("placeholder", False):
        pytest.skip("implemented output golden is exercised by its owning task")

    text_exit_code = main(list(contract.argv))
    text_output = capsys.readouterr()
    json_exit_code = main(["--json", *contract.argv])
    json_output = capsys.readouterr()

    command_path = " ".join(contract.command_path)
    assert text_exit_code == json_exit_code == ExitCode.USAGE
    assert text_output.out.startswith("error[not_implemented]:")
    assert text_output.err == json_output.err == ""
    assert json.loads(json_output.out) == {
        "command": command_path,
        "exit_code": ExitCode.USAGE,
        "message": f"command '{command_path}' is owned by {contract.owner}",
        "status": "not_implemented",
    }


@pytest.mark.parametrize(
    "contract",
    CONTRACTS,
    ids=lambda item: "-".join(item.command_path),
)
def test_implemented_command_cannot_keep_placeholder_goldens(
    contract: Contract,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    if contract.owner in LIVE_CONTRACT_OWNERS:
        return
    argv = materialize_temp_paths(list(contract.argv), tmp_path)
    invocation = {"argv": argv, "exit_code": ExitCode.SUCCESS}
    prepare_task4_success(invocation)
    prepare_task5_success(invocation)
    prepare_task6_success(invocation)
    main(["--json", *argv])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    if result.get("status") != "not_implemented":
        placeholders = [
            name
            for name, case in contract.cases.items()
            if case.get("placeholder", False)
        ]
        assert placeholders == [], (
            f"{' '.join(contract.command_path)} is implemented but still owns "
            "placeholder cases: "
            f"{', '.join(placeholders)}"
        )


def test_contracts_cover_every_owned_command_family() -> None:
    assert {contract.command for contract in CONTRACTS} == set(COMMAND_OWNERSHIP)
