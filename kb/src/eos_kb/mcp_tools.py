"""Scoped EOS KB tool implementations for the remote MCP server (Option A governance)."""

from __future__ import annotations

import datetime as dt
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

from .brief import generate_brief
from .digest import generate_digest
from .jev_retrieval import jev_context
from .remote_agents import (
    RemoteAgentError,
    followup_remote_agent,
    list_remote_agents,
    logs_remote_agent,
    start_remote_agent,
    status_remote_agent,
    stop_remote_agent,
)
from .retrieval import RetrievalValidationError, context as kb_context_fn, search as kb_search_fn

ALLOWED_LOG_KINDS = frozenset({"thought", "meeting", "chat-summary", "decision"})
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_OPEN_ITEM_RE = re.compile(r"^- \[ \]\s*")
_ANY_ITEM_RE = re.compile(r"^- \[[ xX]\]\s*")
_SECTION_RE = re.compile(r"^##\s+")
_BLOCKED_TOP_DIRS = frozenset({".git", ".eos"})


class McpToolError(ValueError):
    """User-facing validation or safety error raised by an MCP KB tool."""


def _safe_resolve(kb_root: Path, relative_path: str) -> Path:
    if not relative_path or relative_path.strip() == "":
        raise McpToolError("path must be a non-empty relative path inside the KB.")
    rel = Path(relative_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise McpToolError("path must stay relative to the KB root (no absolute paths or '..').")
    if rel.parts and rel.parts[0] in _BLOCKED_TOP_DIRS:
        raise McpToolError(f"access to '{rel.parts[0]}' is not permitted.")
    root_resolved = kb_root.resolve()
    candidate = (root_resolved / rel).resolve()
    if candidate != root_resolved and not candidate.is_relative_to(root_resolved):
        raise McpToolError("path escapes the KB root.")
    return candidate


def _slugify(text: str) -> str:
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return slug[:60] or "entry"


def _validate_date(value: str | None, field_name: str) -> str | None:
    if value is None or value == "":
        return None
    if not _DATE_RE.match(value):
        raise McpToolError(f"{field_name} must be in YYYY-MM-DD format.")
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise McpToolError(f"{field_name} is not a valid calendar date.") from exc
    return value


def _format_cards(cards: list[dict[str, Any]], warnings: list[str] | None = None) -> str:
    lines: list[str] = []
    actionable = [
        w for w in (warnings or []) if not w.startswith(("freshness unknown:", "coverage unknown:"))
    ]
    if actionable:
        lines.append("Warnings:")
        for w in actionable:
            lines.append(f"- {w}")
        lines.append("")
    if not cards:
        lines.append("No matching KB entries found.")
        return "\n".join(lines)
    for idx, card in enumerate(cards, 1):
        title = card.get("title") or card.get("relative_file")
        rel = card.get("relative_file", "")
        kind = card.get("type", "")
        fresh = card.get("freshness", "")
        excerpt = (card.get("excerpt") or "").strip()
        lines.append(f"{idx}. **{title}** (`{rel}` | {kind} | freshness: {fresh})")
        if excerpt:
            lines.append(excerpt)
        lines.append("")
    return "\n".join(lines).strip()


def tool_kb_context(
    kb_root: Path,
    profile: str,
    *,
    query: str,
    project: str | None = None,
    budget: int = 2500,
    use_jev: bool = False,
) -> dict[str, Any]:
    if not query or not query.strip():
        raise McpToolError("query must be non-empty.")
    budget = max(500, min(int(budget), 10000))
    try:
        if use_jev:
            res = jev_context(kb_root, query.strip(), budget=budget, profile=profile, project=project or None)
            cards = [c.as_dict() for c in res.cards]
            warnings = list(res.warnings)
            meta = {"jev_used": res.jev_used, "estimated_units": res.estimated_units}
        else:
            res = kb_context_fn(kb_root, query.strip(), budget=budget, project=project or None)
            cards = [c.as_dict() for c in res.cards]
            warnings = list(res.warnings)
            meta = {"jev_used": False, "estimated_units": res.estimated_units}
    except (ValueError, RetrievalValidationError) as exc:
        raise McpToolError(str(exc)) from exc
    return {"text": _format_cards(cards, warnings), "cards": cards, "warnings": warnings, **meta}


def tool_kb_search(
    kb_root: Path,
    profile: str,
    *,
    query: str,
    project: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    if not query or not query.strip():
        raise McpToolError("query must be non-empty.")
    limit = max(1, min(int(limit), 25))
    try:
        cards = [c.as_dict() for c in kb_search_fn(kb_root, query.strip(), project=project or None, limit=limit)]
    except (ValueError, RetrievalValidationError) as exc:
        raise McpToolError(str(exc)) from exc
    return {"text": _format_cards(cards), "cards": cards}


def tool_kb_read(kb_root: Path, profile: str, *, path: str, max_chars: int = 12000) -> dict[str, Any]:
    target = _safe_resolve(kb_root, path)
    if not target.is_file():
        raise McpToolError(f"File not found in {profile} KB: {path}")
    content = target.read_text(encoding="utf-8")
    max_chars = max(500, min(int(max_chars), 40000))
    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars] + "\n\n[...truncated]"
    rel = target.relative_to(kb_root.resolve()).as_posix()
    return {"text": f"# {rel}\n\n{content}", "path": rel, "truncated": truncated}


def tool_kb_list_projects(kb_root: Path, profile: str) -> dict[str, Any]:
    root = kb_root.resolve()
    projects: list[str] = []
    areas: list[str] = []
    projects_dir = root / "projects"
    if projects_dir.is_dir():
        for entry in sorted(projects_dir.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                projects.append(entry.name)
    areas_dir = root / "areas"
    if areas_dir.is_dir():
        for entry in sorted(areas_dir.iterdir()):
            if entry.name.startswith("."):
                continue
            areas.append(entry.stem if entry.is_file() else entry.name)
    index_path = root / "00-index.md"
    index_preview = ""
    if index_path.is_file():
        index_preview = index_path.read_text(encoding="utf-8")[:4000]
    lines = [
        f"Profile: {profile}",
        f"Projects: {', '.join(projects) if projects else '(none)'}",
        f"Areas: {', '.join(areas) if areas else '(none)'}",
    ]
    if index_preview:
        lines.extend(["", "--- 00-index.md ---", index_preview])
    return {"text": "\n".join(lines), "projects": projects, "areas": areas}


def tool_kb_log(
    kb_root: Path,
    profile: str,
    *,
    kind: str,
    title: str,
    body: str,
    project: str | None = None,
    tags: list[str] | None = None,
    revisit_after: str | None = None,
    today: dt.date | None = None,
) -> dict[str, Any]:
    kind_clean = (kind or "").strip().lower()
    if kind_clean not in ALLOWED_LOG_KINDS:
        raise McpToolError(f"kind must be one of: {', '.join(sorted(ALLOWED_LOG_KINDS))}.")
    title_clean = (title or "").strip()
    body_clean = (body or "").strip()
    if not title_clean:
        raise McpToolError("title must be non-empty.")
    if not body_clean:
        raise McpToolError("body must be non-empty.")
    revisit_clean = _validate_date(revisit_after, "revisit_after")

    date_obj = today or dt.date.today()
    date_str = date_obj.isoformat()
    year_dir = kb_root.resolve() / "logs" / str(date_obj.year)
    year_dir.mkdir(parents=True, exist_ok=True)

    slug = _slugify(title_clean)
    base_name = f"{date_str}-{slug}"
    candidate = year_dir / f"{base_name}.md"
    suffix = 2
    while candidate.exists():
        candidate = year_dir / f"{base_name}-{suffix}.md"
        suffix += 1

    frontmatter: dict[str, Any] = {
        "title": f"{date_str} - {title_clean}",
        "type": "Log",
        "date": date_str,
        "status": "stable",
        "freshness": "historical",
        "kind": kind_clean,
        "source": "mcp-remote",
    }
    if project and project.strip():
        frontmatter["project"] = project.strip()
    if tags:
        clean_tags = [str(t).strip() for t in tags if str(t).strip()]
        if clean_tags:
            frontmatter["tags"] = clean_tags
    if revisit_clean:
        frontmatter["revisit_after"] = revisit_clean

    fm_yaml = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    content = f"---\n{fm_yaml}\n---\n\n# {title_clean}\n\n{body_clean}\n"
    candidate.write_text(content, encoding="utf-8")

    rel = candidate.relative_to(kb_root.resolve()).as_posix()
    return {"text": f"Logged {kind_clean} entry to `{rel}`.", "path": rel, "kind": kind_clean}


def _resolve_pending_queue(kb_root: Path, target_path: str) -> Path:
    root = kb_root.resolve()
    rel = Path(target_path)
    parts = rel.parts
    if len(parts) >= 2 and parts[0] in ("projects", "areas"):
        candidate = root / parts[0] / parts[1] / "_pending-kb-updates.md"
        if candidate.is_file():
            return candidate
    return root / "_pending-kb-updates.md"


def _open_proposal_keys(queue_path: Path) -> set[str]:
    if not queue_path.is_file():
        return set()
    lines = queue_path.read_text(encoding="utf-8").splitlines(keepends=True)
    keys: set[str] = set()
    idx = 0
    while idx < len(lines):
        if not _OPEN_ITEM_RE.match(lines[idx]):
            idx += 1
            continue
        end = idx + 1
        while end < len(lines) and not (_ANY_ITEM_RE.match(lines[end]) or _SECTION_RE.match(lines[end])):
            end += 1
        block = lines[idx:end]
        text = _OPEN_ITEM_RE.sub("", block[0], count=1) + "".join(block[1:])
        key = " ".join(text.split()).casefold()
        if key:
            keys.add(key)
        idx = end
    return keys


def tool_kb_propose(
    kb_root: Path,
    profile: str,
    *,
    target_path: str,
    summary: str,
    proposed_change: str,
    rationale: str | None = None,
    today: dt.date | None = None,
) -> dict[str, Any]:
    resolved_target = _safe_resolve(kb_root, target_path)
    rel_target = resolved_target.relative_to(kb_root.resolve()).as_posix()
    summary_clean = (summary or "").strip()
    change_clean = (proposed_change or "").strip()
    if not summary_clean or not change_clean:
        raise McpToolError("summary and proposed_change must be non-empty.")

    queue_path = _resolve_pending_queue(kb_root, rel_target)
    date_str = (today or dt.date.today()).isoformat()
    block_lines = [f"- [ ] **{summary_clean}** (`{rel_target}`, proposed via remote MCP on {date_str})"]
    block_lines.append(f"  - Change: {change_clean}")
    if rationale and rationale.strip():
        block_lines.append(f"  - Rationale: {rationale.strip()}")
    block_text = "\n".join(block_lines) + "\n"

    key = " ".join(_OPEN_ITEM_RE.sub("", block_text, count=1).split()).casefold()
    existing_keys = _open_proposal_keys(queue_path)
    rel_queue = queue_path.relative_to(kb_root.resolve()).as_posix()
    if key in existing_keys:
        return {"text": f"Proposal already open in `{rel_queue}` (deduplicated).", "queue": rel_queue, "deduplicated": True}

    existing = (
        queue_path.read_text(encoding="utf-8")
        if queue_path.is_file()
        else "---\ntitle: Pending KB Updates\ntype: Knowledge Proposal\n---\n\n# Pending KB Updates\n\n"
    )
    if existing and not existing.endswith("\n"):
        existing += "\n"
    new_content = existing + block_text

    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=queue_path.parent, delete=False) as tmp:
        tmp.write(new_content)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, queue_path)

    return {
        "text": f"Queued proposal for `{rel_target}` in `{rel_queue}` (stable KB unchanged; awaiting review/promote).",
        "queue": rel_queue,
        "target_path": rel_target,
        "deduplicated": False,
    }


def tool_kb_due_reviews(
    kb_root: Path,
    profile: str,
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    cutoff_str = _validate_date(as_of, "as_of") or dt.date.today().isoformat()
    cutoff = dt.date.fromisoformat(cutoff_str)
    logs_dir = kb_root.resolve() / "logs"
    due: list[dict[str, Any]] = []
    if logs_dir.is_dir():
        for md in sorted(logs_dir.rglob("*.md")):
            try:
                raw = md.read_text(encoding="utf-8")
            except OSError:
                continue
            if not raw.startswith("---"):
                continue
            parts = raw.split("---", 2)
            if len(parts) < 3:
                continue
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                continue
            if not isinstance(fm, dict):
                continue
            revisit_val = fm.get("revisit_after")
            if not revisit_val:
                continue
            revisit_str = str(revisit_val).strip()
            if not _DATE_RE.match(revisit_str):
                continue
            try:
                revisit_date = dt.date.fromisoformat(revisit_str)
            except ValueError:
                continue
            if revisit_date <= cutoff:
                due.append(
                    {
                        "path": md.relative_to(kb_root.resolve()).as_posix(),
                        "title": str(fm.get("title") or md.stem),
                        "kind": str(fm.get("kind") or "log"),
                        "project": fm.get("project"),
                        "revisit_after": revisit_str,
                    }
                )
    if not due:
        return {"text": f"No log/decision entries due for review as of {cutoff_str}.", "due": []}
    lines = [f"Entries due for review as of {cutoff_str}:"]
    for item in due:
        proj = f" | project: {item['project']}" if item.get("project") else ""
        lines.append(f"- **{item['title']}** (`{item['path']}` | {item['kind']}{proj} | revisit: {item['revisit_after']})")
    return {"text": "\n".join(lines), "due": due}


def tool_kb_digest(
    kb_root: Path,
    profile: str,
    *,
    since_days: int = 7,
    as_of: str | None = None,
) -> dict[str, Any]:
    since = max(1, min(int(since_days), 90))
    cutoff_str = _validate_date(as_of, "as_of")
    cutoff_date = dt.date.fromisoformat(cutoff_str) if cutoff_str else None
    report = generate_digest(kb_root, since_days=since, as_of=cutoff_date)
    return {"text": report.render_markdown().strip(), "digest": report.as_dict()}


def tool_kb_brief(
    kb_root: Path,
    profile: str,
    *,
    topic: str = "",
    project: str | None = None,
    since_days: int = 30,
    budget: int = 2000,
    as_of: str | None = None,
) -> dict[str, Any]:
    cutoff_str = _validate_date(as_of, "as_of")
    cutoff_date = dt.date.fromisoformat(cutoff_str) if cutoff_str else None
    try:
        brief = generate_brief(
            kb_root,
            topic=topic,
            project=project or None,
            since_days=max(1, min(int(since_days), 180)),
            budget=max(500, min(int(budget), 8000)),
            as_of=cutoff_date,
        )
    except ValueError as exc:
        raise McpToolError(str(exc)) from exc
    return {"text": brief.render_markdown().strip(), "brief": brief.as_dict()}


def tool_agent_start(
    kb_root: Path,
    profile: str,
    *,
    name: str,
    prompt: str,
    cwd: str,
    agent: str = "claude",
    permission_mode: str | None = None,
    tmux_profile: str | None = None,
) -> dict[str, Any]:
    try:
        meta = start_remote_agent(
            profile,
            name=name,
            prompt=prompt,
            cwd=cwd,
            agent=agent,
            permission_mode=permission_mode,
            tmux_profile=tmux_profile,
        )
    except RemoteAgentError as exc:
        raise McpToolError(str(exc)) from exc
    tmux_line = (
        f"- tmux window: `{meta['tmux_window']}` in session `{meta['tmux_session']}` (socket `-L {meta['tmux_socket']}`)\n"
        if meta.get("tmux_window")
        else ""
    )
    text = (
        f"Started {meta['agent']} session **{meta['name']}** (`{meta['run_id']}`)\n"
        f"- Profile: `{profile}` | CWD: `{meta['cwd']}`\n"
        f"{tmux_line}"
        f"- Session ID: `{meta['session_id']}`\n"
        f"- Resume locally later: `{meta['resume_command']}`\n"
        f"Use `agent_status` or `agent_logs` with `run_id='{meta['run_id']}'` to monitor progress."
    )
    return {"text": text, "run": meta}


def tool_agent_list(kb_root: Path, profile: str, *, limit: int = 10) -> dict[str, Any]:
    runs = list_remote_agents(profile, limit=limit)
    if not runs:
        return {"text": f"No remote agent sessions found for profile '{profile}'.", "runs": []}
    lines = [f"Remote agent sessions ({profile}):"]
    for r in runs:
        lines.append(
            f"- `{r['run_id']}` [{r['status']}] **{r['name']}** ({r['agent']} @ `{r['cwd']}`, started {r['started_at']})"
        )
    return {"text": "\n".join(lines), "runs": runs}


def tool_agent_status(kb_root: Path, profile: str, *, run_id: str | None = None) -> dict[str, Any]:
    try:
        st = status_remote_agent(profile, run_id=run_id)
    except RemoteAgentError as exc:
        raise McpToolError(str(exc)) from exc
    lines = [
        f"**{st['name']}** (`{st['run_id']}`)",
        f"- Status: **{st['status']}** | Agent: `{st['agent']}` | Turns: {st.get('turns', 1)}",
        f"- CWD: `{st['cwd']}` | Started: {st['started_at']}",
        f"- Resume locally: `{st['resume_command']}`",
    ]
    handoff = st.get("handoff") or {}
    if handoff:
        if handoff.get("summary"):
            lines.extend(["", f"Summary: {handoff['summary']}"])
        questions = handoff.get("questions") or []
        if questions:
            lines.append("")
            lines.append("**Needs Your Input (reply via `agent_followup`):**")
            for idx, q in enumerate(questions, 1):
                lines.append(f"{idx}. {q}")
        if handoff.get("next_step"):
            lines.append(f"Next step once you reply: {handoff['next_step']}")
    elif st.get("final_result"):
        lines.extend(["", "Final Result:", st["final_result"][:3000]])
    elif st.get("recent_events"):
        lines.extend(["", "Recent Activity:"] + [f"- {e}" for e in st["recent_events"][-8:]])
    return {"text": "\n".join(lines), "status": st}


def tool_agent_logs(kb_root: Path, profile: str, *, run_id: str | None = None, tail_lines: int = 40) -> dict[str, Any]:
    try:
        res = logs_remote_agent(profile, run_id=run_id, tail_lines=tail_lines)
    except RemoteAgentError as exc:
        raise McpToolError(str(exc)) from exc
    return {
        "text": f"Logs for **{res['name']}** (`{res['run_id']}` | {res['status']}):\n\n{res['text']}",
        "logs": res,
    }


def tool_agent_followup(kb_root: Path, profile: str, *, run_id: str | None = None, prompt: str) -> dict[str, Any]:
    try:
        meta = followup_remote_agent(profile, run_id=run_id, prompt=prompt)
    except RemoteAgentError as exc:
        raise McpToolError(str(exc)) from exc
    return {
        "text": f"Resumed **{meta['name']}** (`{meta['run_id']}`, turn {meta['turns']}). Monitor with `agent_status`.",
        "run": meta,
    }


def tool_agent_stop(kb_root: Path, profile: str, *, run_id: str | None = None) -> dict[str, Any]:
    try:
        meta = stop_remote_agent(profile, run_id=run_id)
    except RemoteAgentError as exc:
        raise McpToolError(str(exc)) from exc
    return {"text": f"Stopped **{meta['name']}** (`{meta['run_id']}`).", "run": meta}


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "kb_context",
        "description": (
            "Retrieve budgeted, ranked context cards from the EOS knowledge base for a topic or question. "
            "Use this first when grounding a discussion in existing KB knowledge."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language question or topic."},
                "project": {"type": "string", "description": "Optional project slug to narrow scope."},
                "budget": {"type": "integer", "description": "Approximate character/unit budget (default 2500).", "default": 2500},
                "use_jev": {"type": "boolean", "description": "Set true only if plain BM25 results were weak.", "default": False},
            },
            "required": ["query"],
        },
    },
    {
        "name": "kb_search",
        "description": "Search the EOS knowledge base for exact identifiers, decisions, or specific terms.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query or exact identifier."},
                "project": {"type": "string", "description": "Optional project slug."},
                "limit": {"type": "integer", "description": "Max results (1-25, default 10).", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "kb_read",
        "description": "Read a specific Markdown file from the KB by its relative path (e.g. '00-index.md' or 'projects/eos/00-index.md').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path inside the KB root."},
                "max_chars": {"type": "integer", "description": "Maximum characters to return (default 12000).", "default": 12000},
            },
            "required": ["path"],
        },
    },
    {
        "name": "kb_list_projects",
        "description": "List registered projects, areas, and the root 00-index.md router for this KB.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "kb_log",
        "description": (
            "Write a dated entry directly to logs/ (allowed working register). "
            "Use for quick thoughts, offline meeting notes, chat summaries, or decisions with an optional revisit_after date."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["thought", "meeting", "chat-summary", "decision"],
                    "description": "Type of log entry.",
                },
                "title": {"type": "string", "description": "Short human-readable title."},
                "body": {"type": "string", "description": "Markdown body of the note, meeting summary, or decision."},
                "project": {"type": "string", "description": "Optional project or area slug."},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags."},
                "revisit_after": {"type": "string", "description": "Optional YYYY-MM-DD date to revisit this decision or note."},
            },
            "required": ["kind", "title", "body"],
        },
    },
    {
        "name": "kb_propose",
        "description": (
            "Queue a proposed update to a stable KB document in its matching _pending-kb-updates.md queue. "
            "Never edits stable KB Markdown directly; changes are reviewed and promoted later."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_path": {"type": "string", "description": "Relative path of the stable KB doc to update."},
                "summary": {"type": "string", "description": "Short one-line summary of the proposed update."},
                "proposed_change": {"type": "string", "description": "Concrete change to apply."},
                "rationale": {"type": "string", "description": "Optional reason or context from the discussion."},
            },
            "required": ["target_path", "summary", "proposed_change"],
        },
    },
    {
        "name": "kb_due_reviews",
        "description": "List decisions or log entries whose revisit_after date is due on or before today.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "as_of": {"type": "string", "description": "Optional YYYY-MM-DD cutoff date (defaults to today)."},
            },
        },
    },
    {
        "name": "kb_digest",
        "description": (
            "Generate a synthesis and triage digest covering recent logs (clustered by project), "
            "open pending proposals (highlighting consolidation candidates), due decision revisits, and freshness alerts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "since_days": {"type": "integer", "description": "Lookback window in days (1-90, default 7).", "default": 7},
                "as_of": {"type": "string", "description": "Optional YYYY-MM-DD cutoff date (defaults to today)."},
            },
        },
    },
    {
        "name": "kb_brief",
        "description": (
            "Generate a one-shot pre-meeting or topic context brief combining curated KB cards, "
            "recent meeting notes/logs, open and due decisions, and pending proposals for that topic or project."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Meeting subject or topic to brief on."},
                "project": {"type": "string", "description": "Optional project or area slug."},
                "since_days": {"type": "integer", "description": "Lookback window for logs/meetings (default 30).", "default": 30},
                "budget": {"type": "integer", "description": "Context card budget (default 2000).", "default": 2000},
                "as_of": {"type": "string", "description": "Optional YYYY-MM-DD cutoff date (defaults to today)."},
            },
        },
    },
    {
        "name": "agent_start",
        "description": (
            "Launch a real, named coding agent session on the host machine under the active EOS profile "
            "(work: claude only; personal: claude, codex, gemini, opencode). "
            "Claude sessions persist with the given display name so you can resume them locally later."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Human-readable session name (shown in Claude /resume)."},
                "prompt": {"type": "string", "description": "Task or debugging prompt for the coding agent."},
                "cwd": {"type": "string", "description": "Workspace directory (relative to profile root or absolute path inside it)."},
                "agent": {
                    "type": "string",
                    "enum": ["claude", "codex", "gemini", "opencode"],
                    "description": "Agent to launch (default: claude; work profile allows claude only).",
                    "default": "claude",
                },
                "permission_mode": {"type": "string", "description": "Optional Claude permission mode override (e.g. plan, auto)."},
                "tmux_profile": {"type": "string", "description": "Optional EOS tmux workspace profile name (defaults to 'backend' for work, 'research' for personal)."},
            },
            "required": ["name", "prompt", "cwd"],
        },
    },
    {
        "name": "agent_list",
        "description": "List recent remote coding agent sessions and their live states for this profile.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max sessions to return (default 10).", "default": 10},
            },
        },
    },
    {
        "name": "agent_status",
        "description": "Check live status, questions/doubts, final result, and local resume command. Defaults to the profile's active session if run_id is omitted.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Optional run ID (defaults to the active session for this profile)."},
            },
        },
    },
    {
        "name": "agent_logs",
        "description": "Read formatted recent progress logs from a remote coding agent session. Defaults to the active session if run_id is omitted.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Optional run ID (defaults to the active session)."},
                "tail_lines": {"type": "integer", "description": "Number of recent events/lines (default 40).", "default": 40},
            },
        },
    },
    {
        "name": "agent_followup",
        "description": "Send a follow-up prompt or answer a doubt to resume the active (or specified) remote Claude Code session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Optional run ID (defaults to the active session)."},
                "prompt": {"type": "string", "description": "Follow-up instruction or answer to the agent's question."},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "agent_stop",
        "description": "Stop the active (or specified) running remote coding agent session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Optional run ID (defaults to the active session)."},
            },
        },
    },
]


def dispatch_tool(kb_root: Path, profile: str, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    args = arguments or {}
    if name == "kb_context":
        return tool_kb_context(
            kb_root,
            profile,
            query=str(args.get("query") or ""),
            project=args.get("project"),
            budget=int(args.get("budget", 2500)),
            use_jev=bool(args.get("use_jev", False)),
        )
    if name == "kb_search":
        return tool_kb_search(
            kb_root,
            profile,
            query=str(args.get("query") or ""),
            project=args.get("project"),
            limit=int(args.get("limit", 10)),
        )
    if name == "kb_read":
        return tool_kb_read(
            kb_root,
            profile,
            path=str(args.get("path") or ""),
            max_chars=int(args.get("max_chars", 12000)),
        )
    if name == "kb_list_projects":
        return tool_kb_list_projects(kb_root, profile)
    if name == "kb_log":
        return tool_kb_log(
            kb_root,
            profile,
            kind=str(args.get("kind") or ""),
            title=str(args.get("title") or ""),
            body=str(args.get("body") or ""),
            project=args.get("project"),
            tags=args.get("tags"),
            revisit_after=args.get("revisit_after"),
        )
    if name == "kb_propose":
        return tool_kb_propose(
            kb_root,
            profile,
            target_path=str(args.get("target_path") or ""),
            summary=str(args.get("summary") or ""),
            proposed_change=str(args.get("proposed_change") or ""),
            rationale=args.get("rationale"),
        )
    if name == "kb_due_reviews":
        return tool_kb_due_reviews(kb_root, profile, as_of=args.get("as_of"))
    if name == "kb_digest":
        return tool_kb_digest(
            kb_root,
            profile,
            since_days=int(args.get("since_days", 7)),
            as_of=args.get("as_of"),
        )
    if name == "kb_brief":
        return tool_kb_brief(
            kb_root,
            profile,
            topic=str(args.get("topic") or ""),
            project=args.get("project"),
            since_days=int(args.get("since_days", 30)),
            budget=int(args.get("budget", 2000)),
            as_of=args.get("as_of"),
        )
    if name == "agent_start":
        return tool_agent_start(
            kb_root,
            profile,
            name=str(args.get("name") or ""),
            prompt=str(args.get("prompt") or ""),
            cwd=str(args.get("cwd") or ""),
            agent=str(args.get("agent") or "claude"),
            permission_mode=args.get("permission_mode"),
            tmux_profile=args.get("tmux_profile"),
        )
    if name == "agent_list":
        return tool_agent_list(kb_root, profile, limit=int(args.get("limit", 10)))
    if name == "agent_status":
        return tool_agent_status(kb_root, profile, run_id=args.get("run_id"))
    if name == "agent_logs":
        return tool_agent_logs(
            kb_root,
            profile,
            run_id=args.get("run_id"),
            tail_lines=int(args.get("tail_lines", 40)),
        )
    if name == "agent_followup":
        return tool_agent_followup(
            kb_root,
            profile,
            run_id=args.get("run_id"),
            prompt=str(args.get("prompt") or ""),
        )
    if name == "agent_stop":
        return tool_agent_stop(kb_root, profile, run_id=args.get("run_id"))
    raise McpToolError(f"Unknown tool: {name}")
