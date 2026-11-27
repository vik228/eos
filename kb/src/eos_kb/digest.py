"""Layer 2 synthesis and triage digest for EOS knowledge bases."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .freshness import load_freshness

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_OPEN_ITEM_RE = re.compile(r"^- \[ \]\s*")
_ANY_ITEM_RE = re.compile(r"^- \[[ xX]\]\s*")
_SECTION_RE = re.compile(r"^##\s+")
_TARGET_PATH_RE = re.compile(r"`([A-Za-z0-9_./-]+\.md)`")


@dataclass(frozen=True)
class LogEntry:
    path: str
    title: str
    date: str
    kind: str
    project: str
    source: str
    revisit_after: str | None
    preview: str


@dataclass(frozen=True)
class PendingProposal:
    queue: str
    summary: str
    target_path: str | None
    normalized_key: str
    raw_block: str


@dataclass(frozen=True)
class FreshnessAlert:
    resource: str
    state: str
    reason: str


@dataclass(frozen=True)
class DigestReport:
    kb_root: str
    as_of: str
    since_days: int
    recent_logs: tuple[LogEntry, ...] = ()
    logs_by_project: dict[str, list[LogEntry]] = field(default_factory=dict)
    pending_by_queue: dict[str, list[PendingProposal]] = field(default_factory=dict)
    duplicate_proposals: tuple[str, ...] = ()
    multi_proposal_targets: dict[str, int] = field(default_factory=dict)
    due_reviews: tuple[LogEntry, ...] = ()
    freshness_alerts: tuple[FreshnessAlert, ...] = ()

    @property
    def total_pending(self) -> int:
        return sum(len(items) for items in self.pending_by_queue.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "kb_root": self.kb_root,
            "as_of": self.as_of,
            "since_days": self.since_days,
            "summary": {
                "recent_logs": len(self.recent_logs),
                "total_pending": self.total_pending,
                "non_empty_queues": len(self.pending_by_queue),
                "duplicate_proposals": len(self.duplicate_proposals),
                "multi_proposal_targets": len(self.multi_proposal_targets),
                "due_reviews": len(self.due_reviews),
                "freshness_alerts": len(self.freshness_alerts),
            },
            "logs_by_project": {
                proj: [entry.__dict__ for entry in entries]
                for proj, entries in self.logs_by_project.items()
            },
            "pending_by_queue": {
                queue: [
                    {"summary": p.summary, "target_path": p.target_path}
                    for p in items
                ]
                for queue, items in self.pending_by_queue.items()
            },
            "multi_proposal_targets": dict(self.multi_proposal_targets),
            "due_reviews": [entry.__dict__ for entry in self.due_reviews],
            "freshness_alerts": [alert.__dict__ for alert in self.freshness_alerts],
        }

    def render_markdown(self) -> str:
        lines: list[str] = [
            f"# EOS KB Digest ({self.as_of}, last {self.since_days} days)",
            "",
            "## Summary",
            f"- Recent logs: {len(self.recent_logs)} across {len(self.logs_by_project)} project/group(s)",
            f"- Open proposals: {self.total_pending} across {len(self.pending_by_queue)} queue(s)",
            f"- Due decision/log revisits: {len(self.due_reviews)}",
            f"- Freshness alerts (stale/drifted/contradicted): {len(self.freshness_alerts)}",
            "",
        ]

        if self.due_reviews:
            lines.append("## Due for Revisit")
            for item in self.due_reviews:
                proj = f" | {item.project}" if item.project != "unassigned" else ""
                lines.append(f"- **{item.title}** (`{item.path}` | {item.kind}{proj} | due {item.revisit_after})")
            lines.append("")

        if self.freshness_alerts:
            lines.append("## Freshness Alerts")
            for alert in self.freshness_alerts:
                reason = f" - {alert.reason}" if alert.reason else ""
                lines.append(f"- `{alert.resource}`: **{alert.state}**{reason}")
            lines.append("")

        lines.append("## Pending Proposal Queues")
        if not self.pending_by_queue:
            lines.append("- All pending queues are clear.")
        else:
            for queue, items in sorted(self.pending_by_queue.items()):
                lines.append(f"### `{queue}` ({len(items)})")
                for item in items:
                    target = f" -> `{item.target_path}`" if item.target_path else ""
                    lines.append(f"- {item.summary}{target}")
        if self.multi_proposal_targets:
            lines.append("")
            lines.append("### Consolidation Candidates (multiple open proposals for same target)")
            for target, count in sorted(self.multi_proposal_targets.items(), key=lambda kv: (-kv[1], kv[0])):
                lines.append(f"- `{target}`: {count} open proposals")
        if self.duplicate_proposals:
            lines.append("")
            lines.append(f"- Note: {len(self.duplicate_proposals)} exact duplicate open proposal(s) detected (run `scripts/dedupe-pending-kb-queues`).")
        lines.append("")

        lines.append(f"## Recent Logs (last {self.since_days} days)")
        if not self.logs_by_project:
            lines.append("- No new logs in this window.")
        else:
            for project, entries in sorted(self.logs_by_project.items()):
                lines.append(f"### {project} ({len(entries)})")
                for entry in entries:
                    preview = f" - {entry.preview}" if entry.preview else ""
                    lines.append(f"- `{entry.date}` [{entry.kind}] **{entry.title}** (`{entry.path}`){preview}")
        lines.append("")
        return "\n".join(lines).strip() + "\n"


def _parse_frontmatter_and_body(raw: str) -> tuple[dict[str, Any], str]:
    if not raw.startswith("---"):
        return {}, raw
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}, raw
    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return {}, parts[2]
    return (fm if isinstance(fm, dict) else {}), parts[2]


def _extract_preview(body: str, max_len: int = 140) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("---"):
            continue
        cleaned = re.sub(r"\s+", " ", stripped.lstrip("-* "))
        if len(cleaned) > max_len:
            return cleaned[: max_len - 3].rstrip() + "..."
        return cleaned
    return ""


def _parse_date(value: Any, fallback_name: str) -> str | None:
    if value:
        match = _DATE_RE.search(str(value))
        if match:
            return match.group(1)
    match = _DATE_RE.search(fallback_name)
    return match.group(1) if match else None


def _scan_logs(kb_root: Path, *, as_of: dt.date, since_days: int) -> tuple[list[LogEntry], list[LogEntry]]:
    root = kb_root.resolve()
    logs_dir = root / "logs"
    if not logs_dir.is_dir():
        return [], []
    cutoff_start = as_of - dt.timedelta(days=since_days)
    recent: list[LogEntry] = []
    due: list[LogEntry] = []

    for md in sorted(logs_dir.rglob("*.md")):
        if md.name == "index.md" or md.name.startswith("."):
            continue
        try:
            raw = md.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, body = _parse_frontmatter_and_body(raw)
        rel = md.relative_to(root).as_posix()
        date_str = _parse_date(fm.get("date"), md.name)
        revisit_str = _parse_date(fm.get("revisit_after"), "") if fm.get("revisit_after") else None
        entry = LogEntry(
            path=rel,
            title=str(fm.get("title") or md.stem),
            date=date_str or "unknown",
            kind=str(fm.get("kind") or "log"),
            project=str(fm.get("project") or "unassigned"),
            source=str(fm.get("source") or "local"),
            revisit_after=revisit_str,
            preview=_extract_preview(body),
        )
        if date_str:
            try:
                parsed = dt.date.fromisoformat(date_str)
                if cutoff_start <= parsed <= as_of:
                    recent.append(entry)
            except ValueError:
                pass
        if revisit_str:
            try:
                if dt.date.fromisoformat(revisit_str) <= as_of:
                    due.append(entry)
            except ValueError:
                pass

    recent.sort(key=lambda e: (e.date, e.path), reverse=True)
    due.sort(key=lambda e: (e.revisit_after or "", e.path))
    return recent, due


def _scan_pending_queues(kb_root: Path) -> tuple[dict[str, list[PendingProposal]], list[str], dict[str, int]]:
    root = kb_root.resolve()
    queues: dict[str, list[PendingProposal]] = {}
    duplicates: list[str] = []
    target_counts: dict[str, int] = defaultdict(int)

    for queue_path in sorted(root.rglob("_pending-kb-updates.md")):
        if ".git" in queue_path.parts or ".eos" in queue_path.parts:
            continue
        try:
            lines = queue_path.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError:
            continue
        rel_queue = queue_path.relative_to(root).as_posix()
        seen_keys: set[str] = set()
        items: list[PendingProposal] = []
        idx = 0
        while idx < len(lines):
            if not _OPEN_ITEM_RE.match(lines[idx]):
                idx += 1
                continue
            end = idx + 1
            while end < len(lines) and not (_ANY_ITEM_RE.match(lines[end]) or _SECTION_RE.match(lines[end])):
                end += 1
            block = lines[idx:end]
            first_line = _OPEN_ITEM_RE.sub("", block[0], count=1).strip()
            raw_block = "".join(block).strip()
            norm_key = " ".join((first_line + " " + "".join(block[1:])).split()).casefold()
            target_match = _TARGET_PATH_RE.search(raw_block)
            target_path = target_match.group(1) if target_match else None

            if norm_key in seen_keys:
                duplicates.append(f"{rel_queue}: {first_line[:80]}")
            else:
                seen_keys.add(norm_key)
                items.append(
                    PendingProposal(
                        queue=rel_queue,
                        summary=first_line[:160],
                        target_path=target_path,
                        normalized_key=norm_key,
                        raw_block=raw_block,
                    )
                )
                if target_path:
                    target_counts[target_path] += 1
            idx = end
        if items:
            queues[rel_queue] = items

    multi_targets = {t: c for t, c in target_counts.items() if c >= 2}
    return queues, duplicates, multi_targets


def _scan_freshness_alerts(kb_root: Path) -> list[FreshnessAlert]:
    try:
        report = load_freshness(kb_root)
    except Exception:
        return []
    if not isinstance(report, dict):
        return []
    alerts: list[FreshnessAlert] = []
    concepts = report.get("concepts") or report.get("entries") or []
    if isinstance(concepts, dict):
        items = list(concepts.values())
    elif isinstance(concepts, list):
        items = concepts
    else:
        items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or item.get("freshness") or "").lower()
        if state in {"stale", "drifted", "contradicted", "expired"}:
            resource = str(item.get("resource") or item.get("relative_file") or "unknown")
            reasons = item.get("reasons") or item.get("warnings") or []
            reason_text = "; ".join(str(r) for r in reasons[:2]) if isinstance(reasons, list) else str(reasons)
            alerts.append(FreshnessAlert(resource=resource, state=state, reason=reason_text))
    return alerts


def generate_digest(
    kb_root: Path,
    *,
    since_days: int = 7,
    as_of: dt.date | None = None,
) -> DigestReport:
    today = as_of or dt.date.today()
    recent_logs, due_reviews = _scan_logs(kb_root, as_of=today, since_days=since_days)
    logs_by_project: dict[str, list[LogEntry]] = defaultdict(list)
    for entry in recent_logs:
        logs_by_project[entry.project].append(entry)

    pending_by_queue, duplicates, multi_targets = _scan_pending_queues(kb_root)
    freshness_alerts = _scan_freshness_alerts(kb_root)

    return DigestReport(
        kb_root=str(kb_root.resolve()),
        as_of=today.isoformat(),
        since_days=since_days,
        recent_logs=tuple(recent_logs),
        logs_by_project=dict(logs_by_project),
        pending_by_queue=pending_by_queue,
        duplicate_proposals=tuple(duplicates),
        multi_proposal_targets=multi_targets,
        due_reviews=tuple(due_reviews),
        freshness_alerts=tuple(freshness_alerts),
    )


def write_digest_log(kb_root: Path, report: DigestReport) -> Path:
    root = kb_root.resolve()
    date_obj = dt.date.fromisoformat(report.as_of)
    year_dir = root / "logs" / str(date_obj.year)
    year_dir.mkdir(parents=True, exist_ok=True)
    target = year_dir / f"{report.as_of}-kb-digest.md"
    suffix = 2
    while target.exists():
        target = year_dir / f"{report.as_of}-kb-digest-{suffix}.md"
        suffix += 1
    fm = {
        "title": f"{report.as_of} - EOS KB Digest",
        "type": "Log",
        "date": report.as_of,
        "status": "stable",
        "freshness": "historical",
        "kind": "digest",
        "source": "eos-kb-digest",
    }
    fm_yaml = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
    target.write_text(f"---\n{fm_yaml}\n---\n\n{report.render_markdown()}", encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a synthesis and triage digest for an EOS KB.")
    parser.add_argument("--kb", type=Path, default=Path.home() / "personal/knowledge", help="Path to KB root.")
    parser.add_argument("--since-days", type=int, default=7, help="Lookback window for recent logs (default: 7).")
    parser.add_argument("--as-of", type=str, default=None, help="Override date in YYYY-MM-DD format.")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit structured JSON output.")
    parser.add_argument("--write", action="store_true", help="Write digest Markdown log under logs/<year>/.")
    args = parser.parse_args(argv)

    as_of_date = dt.date.fromisoformat(args.as_of) if args.as_of else None
    report = generate_digest(args.kb, since_days=max(1, args.since_days), as_of=as_of_date)
    if args.write:
        written = write_digest_log(args.kb, report)
        print(f"Wrote digest log: {written}", file=sys.stderr)
    if args.as_json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(report.render_markdown(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
