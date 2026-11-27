"""Layer 3 proactive prep and decision-memory brief for EOS knowledge bases."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .digest import LogEntry, PendingProposal, _scan_logs, _scan_pending_queues
from .retrieval import RetrievalValidationError, context as kb_context_fn

_WORD_RE = re.compile(r"[a-z0-9]{3,}")


@dataclass(frozen=True)
class TopicBrief:
    kb_root: str
    topic: str
    project: str | None
    as_of: str
    since_days: int
    context_cards: tuple[dict[str, Any], ...]
    recent_logs: tuple[LogEntry, ...]
    open_decisions: tuple[LogEntry, ...]
    due_decisions: tuple[LogEntry, ...]
    pending_proposals: tuple[PendingProposal, ...]
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "kb_root": self.kb_root,
            "topic": self.topic,
            "project": self.project,
            "as_of": self.as_of,
            "since_days": self.since_days,
            "summary": {
                "context_cards": len(self.context_cards),
                "recent_logs": len(self.recent_logs),
                "open_decisions": len(self.open_decisions),
                "due_decisions": len(self.due_decisions),
                "pending_proposals": len(self.pending_proposals),
            },
            "context_cards": list(self.context_cards),
            "recent_logs": [entry.__dict__ for entry in self.recent_logs],
            "open_decisions": [entry.__dict__ for entry in self.open_decisions],
            "due_decisions": [entry.__dict__ for entry in self.due_decisions],
            "pending_proposals": [
                {"queue": p.queue, "summary": p.summary, "target_path": p.target_path}
                for p in self.pending_proposals
            ],
            "warnings": list(self.warnings),
        }

    def render_markdown(self) -> str:
        header = f"# Pre-Meeting / Topic Brief: {self.topic}"
        if self.project:
            header += f" (project: {self.project})"
        lines: list[str] = [header, f"_As of {self.as_of} | lookback: {self.since_days} days_", ""]

        actionable_warnings = [
            w for w in self.warnings if not w.startswith(("freshness unknown:", "coverage unknown:"))
        ]
        if actionable_warnings:
            lines.append("## Warnings")
            for w in actionable_warnings:
                lines.append(f"- {w}")
            lines.append("")

        if self.due_decisions:
            lines.append("## Decisions Due for Revisit")
            for item in self.due_decisions:
                lines.append(f"- **{item.title}** (`{item.path}` | due {item.revisit_after}) - {item.preview}")
            lines.append("")

        if self.open_decisions:
            lines.append("## Open Decisions")
            for item in self.open_decisions:
                rev = f" | revisit {item.revisit_after}" if item.revisit_after else ""
                lines.append(f"- **{item.title}** (`{item.path}`{rev}) - {item.preview}")
            lines.append("")

        lines.append("## Pending Proposals")
        if not self.pending_proposals:
            lines.append("- No open proposals matching this topic.")
        else:
            for p in self.pending_proposals:
                target = f" -> `{p.target_path}`" if p.target_path else ""
                lines.append(f"- [{p.queue}] {p.summary}{target}")
        lines.append("")

        lines.append(f"## Recent Notes & Meetings (last {self.since_days} days)")
        if not self.recent_logs:
            lines.append("- No matching logs in this window.")
        else:
            for entry in self.recent_logs:
                preview = f" - {entry.preview}" if entry.preview else ""
                lines.append(f"- `{entry.date}` [{entry.kind}] **{entry.title}** (`{entry.path}`){preview}")
        lines.append("")

        lines.append("## Curated KB Context")
        if not self.context_cards:
            lines.append("- No curated KB cards matched.")
        else:
            for idx, card in enumerate(self.context_cards, 1):
                title = card.get("title") or card.get("relative_file")
                rel = card.get("relative_file", "")
                excerpt = (card.get("excerpt") or "").strip()
                lines.append(f"{idx}. **{title}** (`{rel}`)")
                if excerpt:
                    lines.append(excerpt)
                lines.append("")

        return "\n".join(lines).strip() + "\n"


def _keywords(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _matches(text: str, terms: set[str], project: str | None, item_project: str | None = None) -> bool:
    if project and item_project and item_project.lower() == project.lower():
        return True
    if not terms:
        return True
    haystack = text.lower()
    return any(term in haystack for term in terms)


def generate_brief(
    kb_root: Path,
    *,
    topic: str,
    project: str | None = None,
    since_days: int = 30,
    budget: int = 2000,
    as_of: dt.date | None = None,
) -> TopicBrief:
    today = as_of or dt.date.today()
    query = (topic or "").strip() or (project or "").strip()
    if not query:
        raise ValueError("Either topic or project must be non-empty.")

    terms = _keywords(f"{query} {project or ''}")
    warnings: list[str] = []
    cards: list[dict[str, Any]] = []
    try:
        ctx = kb_context_fn(kb_root, query, budget=max(500, min(budget, 8000)), project=project or None)
        cards = [c.as_dict() for c in ctx.cards]
        warnings.extend(ctx.warnings)
    except (ValueError, RetrievalValidationError) as exc:
        warnings.append(f"KB context unavailable: {exc}")

    all_recent, all_due = _scan_logs(kb_root, as_of=today, since_days=since_days)
    matched_logs = [
        entry
        for entry in all_recent
        if _matches(f"{entry.title} {entry.path} {entry.preview}", terms, project, entry.project)
    ][:12]

    due_decisions = [
        entry
        for entry in all_due
        if _matches(f"{entry.title} {entry.path} {entry.preview}", terms, project, entry.project)
    ]
    due_paths = {d.path for d in due_decisions}
    open_decisions = [
        entry
        for entry in matched_logs
        if entry.kind == "decision" and entry.path not in due_paths
    ]

    pending_by_queue, _, _ = _scan_pending_queues(kb_root)
    matched_proposals: list[PendingProposal] = []
    for queue, items in sorted(pending_by_queue.items()):
        queue_matches_project = bool(project and (f"projects/{project}/" in queue or f"areas/{project}/" in queue))
        for item in items:
            if queue_matches_project or _matches(f"{queue} {item.summary} {item.target_path or ''}", terms, project):
                matched_proposals.append(item)

    return TopicBrief(
        kb_root=str(kb_root.resolve()),
        topic=query,
        project=project or None,
        as_of=today.isoformat(),
        since_days=since_days,
        context_cards=tuple(cards),
        recent_logs=tuple(matched_logs),
        open_decisions=tuple(open_decisions),
        due_decisions=tuple(due_decisions),
        pending_proposals=tuple(matched_proposals[:15]),
        warnings=tuple(warnings),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a one-shot pre-meeting or topic brief from an EOS KB.")
    parser.add_argument("topic", nargs="?", default="", help="Topic or meeting subject.")
    parser.add_argument("--kb", type=Path, default=Path.home() / "personal/knowledge", help="Path to KB root.")
    parser.add_argument("--project", type=str, default=None, help="Optional project or area slug.")
    parser.add_argument("--since-days", type=int, default=30, help="Log lookback window in days (default: 30).")
    parser.add_argument("--budget", type=int, default=2000, help="Context card budget (default: 2000).")
    parser.add_argument("--as-of", type=str, default=None, help="Override date in YYYY-MM-DD format.")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output.")
    args = parser.parse_args(argv)

    as_of_date = dt.date.fromisoformat(args.as_of) if args.as_of else None
    brief = generate_brief(
        args.kb,
        topic=args.topic,
        project=args.project,
        since_days=max(1, args.since_days),
        budget=args.budget,
        as_of=as_of_date,
    )
    if args.as_json:
        print(json.dumps(brief.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(brief.render_markdown(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
