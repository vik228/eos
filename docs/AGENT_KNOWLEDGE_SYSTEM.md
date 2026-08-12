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
