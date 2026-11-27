"""Tests for Layer 2 synthesis and triage digest (eos_kb.digest + MCP kb_digest)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from eos_kb.digest import generate_digest, main as digest_main, write_digest_log
from eos_kb.mcp_tools import dispatch_tool


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_digest_clusters_logs_queues_and_due_reviews(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    # Recent logs (within 7 days of 2026-11-27)
    _write(
        kb / "logs/2026/2026-11-26-meeting.md",
        "---\ntitle: Architecture sync\ntype: Log\ndate: 2026-11-26\nstatus: stable\nfreshness: historical\nkind: meeting\nproject: eos\n---\n\nDiscussed remote MCP rollout.\n",
    )
    _write(
        kb / "logs/2026/2026-11-24-decision.md",
        "---\ntitle: Pick Cloudflare Tunnel\ntype: Log\ndate: 2026-11-24\nstatus: stable\nfreshness: historical\nkind: decision\nproject: eos\nrevisit_after: 2026-11-27\n---\n\nEvaluate voice latency after 1 week.\n",
    )
    # Old log outside window (should not be in recent_logs, but due revisit still appears if due)
    _write(
        kb / "logs/2026/2026-10-01-old.md",
        "---\ntitle: Old note\ntype: Log\ndate: 2026-10-01\nstatus: stable\nfreshness: historical\nkind: thought\nproject: finance\n---\n\nOld thought.\n",
    )
    # Pending queues with duplicate + multi-proposal target
    _write(
        kb / "projects/eos/_pending-kb-updates.md",
        (
            "---\ntitle: EOS Pending\ntype: Knowledge Proposal\n---\n\n"
            "- [ ] **Add MCP section** (`projects/eos/arch.md`)\n  - Change: document endpoints\n"
            "- [ ] **Add MCP section** (`projects/eos/arch.md`)\n  - Change: document endpoints\n"
            "- [ ] **Add OAuth section** (`projects/eos/arch.md`)\n  - Change: document Google OAuth\n"
            "- [x] **Already done** (`projects/eos/arch.md`)\n"
        ),
    )

    report = generate_digest(kb, since_days=7, as_of=dt.date(2026, 11, 27))
    assert len(report.recent_logs) == 2
    assert list(report.logs_by_project.keys()) == ["eos"]
    assert report.total_pending == 2  # 3 open minus 1 exact duplicate
    assert len(report.duplicate_proposals) == 1
    assert report.multi_proposal_targets == {"projects/eos/arch.md": 2}
    assert len(report.due_reviews) == 1
    assert report.due_reviews[0].title == "Pick Cloudflare Tunnel"

    md = report.render_markdown()
    assert "Consolidation Candidates" in md
    assert "Pick Cloudflare Tunnel" in md
    assert "Architecture sync" in md

    # Writing digest log creates valid Log file without overwriting
    written = write_digest_log(kb, report)
    assert written.is_file()
    assert "freshness: historical" in written.read_text(encoding="utf-8")


def test_digest_cli_json_and_mcp_tool(tmp_path: Path, capsys) -> None:
    kb = tmp_path / "kb"
    _write(
        kb / "logs/2026/2026-11-27-idea.md",
        "---\ntitle: Quick thought\ntype: Log\ndate: 2026-11-27\nstatus: stable\nfreshness: historical\nkind: thought\n---\n\nTest idea.\n",
    )
    exit_code = digest_main(["--kb", str(kb), "--as-of", "2026-11-27", "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["recent_logs"] == 1

    mcp_res = dispatch_tool(kb, "personal", "kb_digest", {"since_days": 7, "as_of": "2026-11-27"})
    assert "Quick thought" in mcp_res["text"]
