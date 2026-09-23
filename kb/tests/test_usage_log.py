from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from eos_kb.cli import ExitCode, main
from eos_kb.indexer import index_bundle
from eos_kb.usage_log import read_usage, record_usage, summarize_usage, usage_path


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EOS_KB_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("EOS_AGENT_SESSION_ID", "session-1")
    monkeypatch.setenv("EOS_AGENT_PROFILE", "work")
    monkeypatch.delenv("EOS_KB_USAGE_LOG", raising=False)
    for key in ("TYPESAFE_API_KEY_WORK", "TYPESAFE_API_KEY_PERSONAL", "TYPESAFE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    root = tmp_path / "knowledge"
    concept = root / "areas" / "note.md"
    concept.parent.mkdir(parents=True)
    concept.write_text(
        "---\ntype: Note\ntitle: Note\nresource: kb:test/note\n---\n# Note\nsharedterm\n",
        encoding="utf-8",
    )
    index_bundle(root)
    registry = tmp_path / "workspaces.yaml"
    registry.write_text(
        f"workspaces:\n  {tmp_path / 'elsewhere'}:\n    kb: {tmp_path / 'other'}\n    project: other\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EOS_KB_REGISTRY", str(registry))
    monkeypatch.chdir(tmp_path)
    return root


def test_search_and_context_append_one_entry_each(
    bundle: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["search", "sharedterm", "--kb", str(bundle), "--json"]) == ExitCode.SUCCESS
    assert main(["context", "sharedterm", "--kb", str(bundle), "--budget", "2500", "--jev", "--json"]) == ExitCode.SUCCESS
    capsys.readouterr()

    search, context = read_usage(bundle)
    assert search["command"] == "search"
    assert search["query"] == "sharedterm"
    assert search["session_id"] == "session-1"
    assert search["profile"] == "work"
    assert search["cards"] == ["kb:test/note"]
    assert search["jev_requested"] is False
    assert context["command"] == "context"
    assert context["budget"] == 2500
    assert context["jev_requested"] is True
    assert context["jev_used"] is False, "no key configured, so Jev falls back"
    assert context["jev_tokens"] == 0


def test_failed_retrieval_is_not_logged(bundle: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["context", "sharedterm", "--kb", str(bundle), "--budget", "1", "--json"]) != ExitCode.SUCCESS
    capsys.readouterr()
    assert read_usage(bundle) == []


def test_logging_can_be_disabled(
    bundle: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("EOS_KB_USAGE_LOG", "0")
    assert main(["search", "sharedterm", "--kb", str(bundle), "--json"]) == ExitCode.SUCCESS
    capsys.readouterr()
    assert not usage_path(bundle).exists()


def test_unwritable_log_never_fails_retrieval(
    bundle: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    usage_path(bundle).mkdir()
    assert main(["search", "sharedterm", "--kb", str(bundle), "--json"]) == ExitCode.SUCCESS
    assert json.loads(capsys.readouterr().out)["data"]


def test_read_usage_skips_malformed_lines(bundle: Path) -> None:
    record_usage(bundle, command="search", query="q", project=None, jev_requested=False,
                 jev_used=False, jev_tokens=0, cards=[])
    with usage_path(bundle).open("a", encoding="utf-8") as handle:
        handle.write("not json\n{\"ts\": \"bad\"}\n[]\n")
    assert [entry["query"] for entry in read_usage(bundle)] == ["q"]


def _entry(ts: datetime, *, session: str | None = "s1", jev: bool = False,
           command: str = "context", query: str = "q", tokens: int = 0) -> dict:
    return {
        "ts": ts.isoformat(), "session_id": session, "command": command, "query": query,
        "jev_requested": jev, "jev_used": jev and tokens > 0, "jev_tokens": tokens,
        "cards": [f"kb:{query}"],
    }


def test_summary_counts_escalation_within_same_session_and_window() -> None:
    t0 = datetime(2026, 9, 23, tzinfo=timezone.utc)
    entries = [
        _entry(t0, query="plain question"),
        _entry(t0 + timedelta(minutes=2), jev=True, query="plain question", tokens=5000),
        # Jev without a preceding plain call is a direct use, not an escalation.
        _entry(t0 + timedelta(minutes=3), jev=True, tokens=4000),
        # Different session and stale window do not count.
        _entry(t0 + timedelta(minutes=4), session="s2"),
        _entry(t0 + timedelta(minutes=5), session="s3", jev=True, tokens=100),
        _entry(t0 + timedelta(minutes=6), session="s4"),
        _entry(t0 + timedelta(minutes=30), session="s4", jev=True, tokens=100),
        # Different command does not pair.
        _entry(t0 + timedelta(minutes=40), session="s5", command="search"),
        _entry(t0 + timedelta(minutes=41), session="s5", jev=True, tokens=100),
    ]

    summary = summarize_usage(entries)

    assert summary["calls"] == 9
    assert summary["plain_calls"] == 4
    assert summary["jev_calls"] == 5
    assert summary["jev_fallbacks"] == 0
    assert summary["jev_tokens"] == 9300
    assert summary["escalations"] == 1
    escalation = summary["recent_escalations"][0]
    assert escalation["plain_query"] == "plain question"
    assert escalation["jev_tokens"] == 5000


def test_summary_since_filters_old_entries() -> None:
    t0 = datetime(2026, 9, 23, tzinfo=timezone.utc)
    entries = [_entry(t0 - timedelta(days=10)), _entry(t0)]
    assert summarize_usage(entries, since=t0 - timedelta(days=1))["calls"] == 1
