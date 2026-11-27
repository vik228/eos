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

Run any array loop that feeds `kb promote` under `bash` explicitly
(shebang `#!/usr/bin/env bash` or a `bash -c` wrapper). `zsh` arrays are
1-indexed, so a 0-based loop run under `zsh` shifted proposal targets by
one during a past promote. When `zsh` is unavoidable, use 1-based indexing
and note it in a comment.

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

## KB CLI gotchas

- `kb propose` needs a session record first (`kb session start --cwd
  <workspace> --agent <agent> --profile <profile> --native-id <id>`).
  Propose itself never checks lease or state (`kb/src/eos_kb/governance.py`,
  `_session`), so an expired lease does not block `kb propose`. The lease
  (`lease_seconds` defaults to 300 in `kb/src/eos_kb/sessions.py`) is read
  only by `kb session recover`, which marks sessions whose owner is no longer
  live as `abandoned`. `kb checkpoint` only records `updated_at`; it does not
  renew the lease. `kb session resume <id>` on an active session fails with
  "session is already active"; resuming an `abandoned` session needs the
  matching `--native-id`. Before a long flow, run `kb session recover`,
  resume if needed, and retry.
- The proposal file is a YAML mapping with required keys `summary`,
  `evidence`, `source_paths`, `confidence`, `known_gaps`,
  `suggested_freshness`, `conflicts`, and `result_content` holding the full
  target file (schema: `kb/src/eos_kb/governance.py`, `capture_proposal`).
  Prose-only Markdown parses as a YAML string and fails as "Proposal input
  must be a mapping" (`governance.py`, `capture_proposal`); only some
  malformed shapes raise YAML errors. An unreadable path fails as
  "Proposal input is not readable: <os error>", and a wrong shape fails as
  "Proposal input is missing required fields" without naming which keys are
  missing. Paths resolve against the invoker's working directory; stage the
  file where the command runs (for example under `<kb>/.eos/tmp/`, which the
  indexer excludes) and pass the path accordingly.
- Promotion order matters: `kb promote` rebuilds the index from the
  candidate result and fails with `governance.result_invalid` on a broken
  link, so promote a linked-to file before the file that links to it.
- `kb context` has a mandatory base package (query envelope plus warnings,
  zero cards) that must fit the budget. Small `--budget` values fail with
  `context.budget_too_small` on `$.budget`, naming the required units; the
  floor rises with the warning count.
- The PreToolUse hook allows `logs/` at the KB root and any
  `_pending-kb-updates.md` by filename
  (`configs/agents/claude/hooks/eos-agent-hook:223`). Per-project `logs/`
  directories (for example `projects/<slug>/logs/`) stay blocked by that
  check; whether they should also be exempt is still an OPEN decision.

## Lifecycle and Stop hook behavior

- The Stop hook runs `kb checkpoint --session "$EOS_AGENT_SESSION_ID"`: the
  EOS session id carried by the wrapper, not the Claude session id (which is
  used only for `kb session resume --native-id`). If the checkpoint fails,
  the hook attempts `kb session resume` on the wrapper session and retries
  the checkpoint once. Resume on an active session fails with "session is
  already active" (ignored; the retry then proceeds), and resuming an
  `abandoned` session needs the matching `--native-id`. Direct
  launches with no EOS session only audit; they never checkpoint.
- Only confirmed stale evidence and contradictions block `kb checkpoint` and
  `kb session end`; `unknown` findings stay visible in audit output but never
  block (`kb/src/eos_kb/cli.py`, `_lifecycle_audit`). A concept past its
  `stale_after` blocks even when no proposal is open for it: pending queues
  are indexed like any other concept, and the time check does not consider
  checkbox state.
- `kb index` keeps the old index when validation fails: a YAML error (for
  example an unquoted `: ` in a title) returns the current database
  untouched, so a fixed `stale_after` date is not seen until the YAML error
  is fixed and the KB is reindexed (`kb/src/eos_kb/indexer.py`,
  `index_bundle`). Freshness reads `stale_after` from the index database, not
  from the files.

## Global discussion contract

The global discussion contract is rendered for every supported agent and is
independent of repository identity. Claude refreshes it through SessionStart
and PostCompact hooks; other transports retain it through their generated
instruction surface.

## Hook transports (Claude, Codex, Antigravity)

`scripts/merge-agent-settings` installs all three surfaces: Claude
`~/.claude*/settings.json`, Codex `~/.codex*/hooks.json`, Antigravity
`~/.gemini/config/hooks.json` (top-level `eos` group: SessionStart,
PreInvocation, PreToolUse, PostToolUse, Stop).

- Antigravity uses camelCase stdin (`hookEventName`, `toolCall.name` /
  `toolCall.args`, `transcriptPath`, `lastUserInput`) and omits
  `last_assistant_message` on Stop, so the hook reads the last
  `PLANNER_RESPONSE` step from `transcriptPath` (plus
  `transcript_full.jsonl` for truncated steps). Replies:
  `{"decision":"allow"}` to pass, `{"decision":"deny"}` to block
  PreToolUse, `{"decision":"continue"}` to block Stop, and
  `{"injectSteps":[{"systemMessage":{"systemMessage":"..."}}]}` on
  SessionStart / PreInvocation.
- Codex `hooks.json` must not contain `InstructionsLoaded` (schema rejects
  it). The hook never emits `"continue": false` on PreToolUse, uses
  `{"decision":"block"}` for blocks, and uses `systemMessage` (not
  `message`) on SessionStart / PostCompact / UserPromptSubmit.
- The Stop language guard covers the em dash plus Devanagari and related
  Indic scripts (`U+0900-U+0DFF`) and Arabic / Urdu ranges (`U+0600-U+06FF`,
  `U+0750-U+077F`, `U+08A0-U+08FF`, `U+FB50-U+FDFF`, `U+FE70-U+FEFF`).
- `EOS_AGENT_PROFILE=default` falls through to cwd inference, so the
  SessionStart pending-queue reminder still fires instead of being skipped.

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
