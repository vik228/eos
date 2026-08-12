# EOS Personal Knowledge Route Design

## Goal

Make work in `$HOME/personal/eos` resumable across Claude, Codex,
Gemini, and Antigravity sessions without copying repository documentation into
agent-private memory.

## Design

Register `$HOME/personal/eos` in the EOS workspace registry with:

- KB root: `$HOME/personal/knowledge`
- Project: `eos`

Workspace resolution is cwd-first even when a caller supplies `--kb`. The
resolver first selects the longest registered cwd prefix, then verifies that the
explicit KB resolves to the same route KB. A mismatched explicit KB is rejected.
Only an unregistered cwd may use an explicit KB without a project scope. This
prevents EOS and research project sessions, which share the personal KB root, from
borrowing each other's project or coverage settings.

Create a lightweight project route at
`projects/eos/00-index.md` and a project proposal queue at
`projects/eos/_pending-kb-updates.md`. The project index stores durable context:
the repository purpose, authoritative documentation routes, verification
procedures, operating invariants, and the expected session-resume workflow.
Detailed implementation documentation remains authoritative inside the EOS
repository and is linked from the KB rather than duplicated.

The same project files live at
`personal-knowledge/projects/eos/00-index.md` and
`personal-knowledge/projects/eos/_pending-kb-updates.md` in the reproducible EOS
scaffold. Canonical authored routes always use `00-index.md`; directory
`index.md` files remain derived runtime artifacts. The scaffold root index links
to the EOS project, and its pending root links to the EOS proposal queue.

The installer creates missing project files but never replaces an existing live
file without `--force`. Existing files are backed up before forced replacement.
For an existing live KB, root-router and project-file changes use governed
proposal, review, and promotion. Installer tests cover first install, repeated
install, user-modified target preservation, and forced backup behavior.

## Session Flow

1. A personal agent starts with cwd inside `$HOME/personal/eos`.
2. Workspace routing resolves the personal KB and project `eos`, including when
   the wrapper supplies the shared personal `--kb` root.
3. Rendered global agent instructions explicitly require EOS sessions to read
   the personal root index and `projects/eos/00-index.md` before changing code.
4. The agent reads only relevant linked repository docs and KB concepts.
5. Session checkpoints propose durable updates for user review.
6. New sessions recover accepted knowledge through the same route.

The `codex-personal` launcher remains the supported Codex CLI entrypoint. It
provides write access to the EOS repository and personal KB while preserving the
configured permission mode, MCPs, global instructions, and lifecycle hooks. The
launcher refuses to start when either the workspace or KB root is not writable.

## Source Of Truth

The KB owns only durable collaboration context: EOS purpose, route names,
operating invariants, accepted architectural decisions, troubleshooting routes,
and pointers to authoritative repository documents. Mutable implementation
state, test counts, installed versions, Git revisions, migration receipts, and
current rollout status remain authoritative in the repository, Git, or generated
runtime state and are not copied as durable KB facts.

Every KB statement about implementation state must link to an authoritative
repository path and include either `eos.source_revision` plus `eos.source_paths`
or a dated `verified` record. Such claims become stale when their source revision
cannot be verified. The initial EOS project page therefore links to
`docs/AGENT_KNOWLEDGE_SYSTEM.md`, `docs/AGENT_KNOWLEDGE.md`,
`docs/PRODUCTIVITY.md`, and `bootstrap/verify.sh` without duplicating their
contents.

## Safety

- Do not copy EOS source code or full documentation into the KB.
- Do not let hooks directly mutate curated KB concepts.
- Do not auto-accept pending proposals.
- Preserve existing personal KB content during bootstrap.
- Keep repo-specific instructions complementary to global and KB instructions.
- Reject an explicit KB that conflicts with the cwd's registered route.
- Treat exact KB validation and workspace resolution failures as rollout
  blockers.

## Verification

- Registry tests resolve `$HOME/personal/eos` to project `eos`.
- Resolver E2E tests use EOS and research project workspaces sharing one KB and prove
  cwd-specific project selection with explicit `--kb`, longest-prefix behavior,
  and mismatch rejection.
- Personal scaffold tests require both EOS project files and root-index link.
- Installer idempotence and conflict tests preserve existing live content and
  verify forced backups.
- Live KB indexing and strict validation pass after governed promotion.
- Rendered Claude, Codex, Gemini, and Antigravity instructions contain the EOS
  route and keep checkpoint updates proposal-only.
- A fresh Codex personal E2E session resolves the EOS route and performs real
  temporary writes through the launcher to both workspace and KB roots. Negative
  cases prove launch refusal when either root is missing or not writable.
- Full bootstrap verification remains green.
