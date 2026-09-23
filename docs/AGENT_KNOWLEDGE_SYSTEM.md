# EOS Agent Knowledge System

EOS provides one local, OKF-compatible and Markdown-canonical knowledge system
for Claude, Codex, Gemini, and Antigravity. Open Knowledge Format concepts and
routers remain portable source files. SQLite indexes, freshness reports,
session records, approval logs, and generated routers are derived or auditable
state.

EOS uses standard OKF metadata where relevant and keeps its extensions under an
`eos` namespace. Governance adds approval and trust behavior without replacing
the portable OKF bundle with a proprietary knowledge store.

## Daily Workflow

```bash
kb context "task or symptom" --budget 2500
kb search "exact identifier"
kb audit
kb status
```

Agent wrappers run doctor, audit, session start, checkpoint, and session end.
Use the wrappers from WezTerm, tmux, and Neovim so profile and KB routing remain
consistent.

Freshness state is evidence-based. Confirmed stale evidence, source drift, and
contradictions block checkpoint and session end. Unknown freshness remains
visible in audit and retrieval warnings but is advisory, because a scaffolded
or intentionally self-contained concept may not declare a freshness contract.

## Workspace retrieval scope

Inside a registered workspace, `kb search` and `kb context` are scoped to the
workspace project. A concept belongs to the project named by its
`eos.project` tag, else to the `projects/<slug>/` directory it lives in.
Concepts outside `projects/` (areas, patterns, logs, root indexes) are shared
and stay visible under every scope. A registry route may list
`related_projects` to widen the default scope to sibling projects:

```yaml
workspaces:
  ~/work/backend:
    kb: ~/work/knowledge
    project: backend
    related_projects: [platform, data-layer]
```

`render-local-config` fills this from `EOS_WORK_RELATED_PROJECTS`. An explicit
`--project` on `kb search` is a strict override and ignores related projects.

## Optional Jev decision layer

`kb search` and `kb context` accept an opt-in `--jev` flag that asks a TypeSafe
Jev model to expand the query, route it to a KB section (applied as a component
filter with unfiltered fallback), and re-rank BM25 hits. `kb context --jev`
still honors an explicit `--budget`; adaptive budgeting is never applied on
top of a budget you typed. `--jev-profile work|personal` selects the API key;
when omitted it is derived from the KB path against `EOS_WORK_KNOWLEDGE_ROOT`.

Agents use Jev as an escalation, not a default: exact identifiers stay on
plain BM25, and natural-language queries run plain first and rerun once with
`--jev` only when the plain cards are weak (off-topic, only session logs, or
no card answers the question).

Every successful `kb search` and `kb context` appends one JSON line to
`usage.jsonl` in the KB's local state directory (query, cards, `--jev` use,
Jev tokens, agent session). The log never leaves the machine and never fails
retrieval; set `EOS_KB_USAGE_LOG=0` to disable it. `scripts/eos-kb-usage`
summarizes plain vs Jev calls, Jev tokens, and escalations (a `--jev` call
after a plain call of the same command in the same session within 10 minutes):

```bash
scripts/eos-kb-usage --since-days 7
```

Keys live in `.eos.local` as `TYPESAFE_API_KEY_WORK` and
`TYPESAFE_API_KEY_PERSONAL` (shared fallback `TYPESAFE_API_KEY`). Without a
key, or on any API failure, retrieval falls back to plain BM25. The same
pipeline is available to hooks and scripts:

```bash
scripts/eos-jev-filter status
scripts/eos-jev-filter context --kb "$HOME/personal/knowledge" --query "task" --budget 2000
kb context "task or symptom" --budget 2500 --jev
kb search "exact identifier" --jev --jev-profile work
```

## Knowledge Changes

Create a proposal rather than editing stable knowledge silently:

```bash
kb propose --target projects/example/concept.md --proposal-file proposal.yaml --session "$SESSION_ID"
kb review <proposal-id> --actor Vikas --session "$SESSION_ID" --decision accepted
kb promote <proposal-id> --session "$SESSION_ID"
```

Promotion revalidates proposal, approval, base, and result hashes. Child sessions
may capture evidence and proposals but cannot promote, deprecate, or approve a
direct stable change.

Agent instructions forbid direct stable Markdown writes, and the Claude
PreToolUse hook enforces that boundary for Write/Edit tools. Pending queues and
`logs/` are the only working-register exceptions. Personal capture routes by
the proposal target path, while the SessionStart reminder reports every
non-empty registered project and area queue.

Personal capture deduplicates unchecked proposal blocks before and after each
capture event. It keeps the first open occurrence and treats line wrapping as
non-semantic.

The global discussion contract is rendered for every supported agent and is
independent of repository identity. Claude refreshes it through SessionStart
and PostCompact hooks; other transports retain it through their generated
instruction surface.

## Bug Investigations

```bash
kb bug start --session "$SESSION_ID" --symptom "user-visible symptom"
kb bug record <id> --kind reproduction --file evidence.json
kb bug status <id>
```

Completion requires E2E reproduction, system mapping, competing hypotheses,
root cause, a failing test, affected-case verification, uncertainty, and an
explicit durable-learning decision.

## Recovery

Use `kb session recover` after an abnormal agent termination. Migration apply
writes an `in_progress` receipt before mutation; use `kb migrate rollback` with
the exact manifest, hash, and receipt to restore manifest-owned paths.

## Migration Approval

Migration approval is bound to the exact verified manifest hash and an active
session for the same KB:

```bash
kb session start --kb "$KB_ROOT" --cwd "$KB_ROOT" --agent operator --profile migration --json
kb migrate verify-plan migration.json --print-hash
kb migrate approve --kb "$KB_ROOT" --manifest migration.json --manifest-hash "$HASH" --approved-by Vikas --approval-session "$SESSION_ID"
kb migrate apply --kb "$KB_ROOT" --manifest migration.json --manifest-hash "$HASH" --approved-by Vikas --approval-session "$SESSION_ID" --receipt-out receipt.json
```

Any source, scope, symlink target, approver, session, or manifest hash change
invalidates the approval.

## Maintenance

- `eos agent doctor` checks the installed environment.
- `scripts/kb-audit-all` audits work and personal KBs independently.
- The LaunchAgent runs audits at login and every six hours.
- `tests/test_agent_adherence.sh` verifies profile policy and routing.
- `EOS_RUN_AGENT_BEHAVIOR_TESTS=1` enables live agent trials when all transports
  are installed.
