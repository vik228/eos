"""Bug-investigation workflow regression tests.

Covers the `kb bug record --kind advance --file` phase path prescribed by
the bug-investigation skill, keeps the skill's kind list in sync with the
implementation, and pins the clean `durable_learning` shape error.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from eos_kb.cli import ExitCode, main
from eos_kb.investigations import _EVIDENCE


@pytest.fixture(autouse=True)
def isolated_neutral_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Isolate KB state, cwd, and registry so `--kb` resolves unregistered."""
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))
    registry = tmp_path / "workspaces.yaml"
    registry.write_text(
        yaml.safe_dump(
            {"workspaces": {"/nonexistent-eos-workspace": {"kb": "/nonexistent-kb", "project": "demo"}}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EOS_KB_REGISTRY", str(registry))
    monkeypatch.chdir(tmp_path)
    kb = tmp_path / "knowledge"
    kb.mkdir()
    return kb


def _start(capsys: pytest.CaptureFixture[str], kb: Path) -> str:
    exit_code = main(
        ("bug", "start", "--session", "s1", "--symptom", "save loses data", "--kb", str(kb), "--json")
    )
    assert exit_code == ExitCode.SUCCESS
    return json.loads(capsys.readouterr().out)["data"]["investigation_id"]


def test_bug_record_advance_file_moves_new_to_reproducing(
    capsys: pytest.CaptureFixture[str], isolated_neutral_workspace: Path
) -> None:
    kb = isolated_neutral_workspace
    investigation_id = _start(capsys, kb)
    phase_file = kb.parent / "phase.json"
    phase_file.write_text(json.dumps({"phase": "reproducing"}), encoding="utf-8")

    exit_code = main(
        ("bug", "record", investigation_id, "--kind", "advance", "--file", str(phase_file), "--kb", str(kb), "--json")
    )

    assert exit_code == ExitCode.SUCCESS
    assert json.loads(capsys.readouterr().out)["data"]["phase"] == "reproducing"


def test_skill_kind_list_matches_implementation() -> None:
    skill = Path(__file__).resolve().parents[2] / "configs" / "agents" / "skills" / "bug-investigation" / "SKILL.md"
    assert skill.is_file(), f"bug-investigation skill missing at {skill}"
    line = next(
        (entry for entry in skill.read_text(encoding="utf-8").splitlines() if "kb bug record --kind" in entry),
        None,
    )
    assert line is not None, "SKILL.md no longer documents the `kb bug record --kind` list; restore it or update this test"
    skill_kinds = re.findall(r"`([a-z_]+)`", line)
    expected = [*_EVIDENCE, "advance"]
    assert sorted(skill_kinds) == sorted(expected), (
        f"skill/implementation kind drift: skill={sorted(skill_kinds)} implementation={sorted(expected)}"
    )


def test_bug_complete_rejects_string_durable_learning_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], isolated_neutral_workspace: Path
) -> None:
    kb = isolated_neutral_workspace
    investigation_id = _start(capsys, kb)
    evidence: tuple[tuple[str, object], ...] = (
        ("classification", {"impact": "data loss"}),
        ("retrieval", {"resources": ["kb:failure-mode"]}),
        ("reproduction", {"command": "pytest", "actual": "fail"}),
        ("system_map", {"entrypoint": "save"}),
        ("blast_radius", {"cases": ["save"]}),
        ("hypothesis", {"id": "h1", "text": "bad write"}),
        ("supporting", {"hypothesis_id": "h1", "evidence": "trace"}),
        ("contradicting", {"hypothesis_id": "h1", "evidence": "none"}),
        ("disconfirmation", {"hypothesis_id": "h1", "result": "supported"}),
        ("alternative_disposition", {"decision": "no alternative"}),
        ("root_cause", {"causal_chain": "input -> bad write -> loss"}),
        ("failing_test", {"reference": "tests/test_save.py::test_loss"}),
        ("affected_cases", {"cases": ["single"]}),
        ("verification", {"command": "pytest", "result": "pass"}),
        ("uncertainty", {"remaining": "none"}),
    )
    for kind, value in evidence:
        payload = tmp_path / f"{kind}.json"
        payload.write_text(json.dumps(value), encoding="utf-8")
        assert main(("bug", "record", investigation_id, "--kind", kind, "--file", str(payload), "--kb", str(kb), "--json")) == ExitCode.SUCCESS
        capsys.readouterr()
    assert main(("bug", "record", investigation_id, "--kind", "durable_learning", "--value", "none needed", "--kb", str(kb), "--json")) == ExitCode.SUCCESS
    capsys.readouterr()
    for phase in ("reproducing", "investigating", "root-caused", "fixing", "verifying"):
        payload = tmp_path / f"{phase}.json"
        payload.write_text(json.dumps({"phase": phase}), encoding="utf-8")
        assert main(("bug", "record", investigation_id, "--kind", "advance", "--file", str(payload), "--kb", str(kb), "--json")) == ExitCode.SUCCESS
        capsys.readouterr()

    exit_code = main(("bug", "complete", investigation_id, "--kb", str(kb), "--json"))

    captured = capsys.readouterr()
    assert exit_code == ExitCode.BLOCKED_LIFECYCLE
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out
    assert captured.out == ""
    result = json.loads(captured.err)
    assert result["exit_code"] == ExitCode.BLOCKED_LIFECYCLE
    assert "JSON object" in result["message"]
    assert '{"required": false}' in result["message"]
