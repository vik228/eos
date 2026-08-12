# Architecture

EOS is a personal, governed knowledge and context platform with optional agent
and environment integrations.

The architecture separates the reusable knowledge core from the current macOS
engineering distribution. They live in one repository today, but they do not
have the same product boundary.

## Product Boundary

```text
Agent harnesses
terminal today; web and app surfaces later
        |
        | skills, lifecycle adapters, MCP
        v
EOS integration boundary
        |
        v
EOS knowledge and governance core
routing | retrieval | sessions | proposals | approvals | audits
        |
        v
User-controlled Markdown and derived state
local machine by default; user-owned hosting supported by design
```

EOS does not need to own or centrally host the user's knowledge. Its job is to
facilitate governed access between agents and a KB controlled by the user.

## Knowledge and Governance Core

`kb/` contains the reusable Python package and CLI. Its responsibilities are:

- canonical Markdown discovery and indexing
- project and subject routing
- budgeted context retrieval
- freshness and source-drift auditing
- session lifecycle and recovery
- structured bug-investigation evidence
- proposal, review, approval, and promotion governance
- migration planning, verification, and rollback

The core treats Markdown as canonical. State under each KB's `.eos/` directory
is derived or auditable operational state, not a replacement knowledge store.

### OKF bundle model

EOS knowledge roots are [Open Knowledge Format (OKF) v0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)-compatible
Markdown bundles. `index.md` is the canonical OKF router, with `00-index.md`
retained as a compact compatibility router during migration. Concepts use
standard OKF fields where relevant, including `type`, `title`, `description`,
`resource`, `tags`, `generated`, `verified`, `sources`, `status`, and
`stale_after`.

EOS-specific metadata is nested under the `eos` namespace so it does not
collide with current or future OKF fields. Only metadata needed by a concept is
required, and unknown OKF types remain consumable. This keeps content portable
while allowing EOS to add deterministic routing, source coverage, claims,
trust, freshness, and governance.

Generated manifests, SQLite indexes, approvals, and session records can be
rebuilt or inspected independently. None is a proprietary replacement for the
OKF-compatible Markdown bundle.

## Integration Boundary

Agent harnesses should reach the core through explicit adapters rather than
reading and mutating arbitrary files.

Current adapters include:

- shared agent instructions and installable skills
- Claude lifecycle hooks
- Claude and Codex session-capture commands
- agent launchers that select profile, workspace, and KB routes

MCP is the intended cross-harness boundary for future Claude, ChatGPT, and
similar web/app integrations. The exact remote permission, consent, and
exposure model is intentionally undecided and must be designed before a remote
adapter is considered production-ready.

## Privacy and Deployment Boundary

- The user chooses the KB directories.
- Local execution is the default deployment.
- The architecture permits deployment on infrastructure owned by the user.
- EOS-managed central knowledge hosting is not required.
- Work and personal roots are resolved from the active profile before queues or
  context are enumerated.
- Curated Markdown rejects direct agent writes. Logs and pending proposal queues
  are explicit working-register exceptions.

## Engineering Reference Integration

The current distribution proves the core in an agent-heavy macOS workflow.

### Config layer

`configs/` declares modular configuration for agents, KB routing, zsh, Git,
tmux, WezTerm, Neovim, Starship, and declarative workspaces.

### Command layer

`scripts/` contains stable user-facing launchers, installers, lifecycle
adapters, KB capture commands, and the thin `eos` command router.

### Workspace layer

tmux owns persistent processes and project state. WezTerm owns terminal
rendering and OS integration. Neovim owns editing workflows. Declarative YAML
defines profile-specific window composition without hardcoding it into launch
scripts.

### Bootstrap layer

`bootstrap/bootstrap.sh` creates directories, backs up replaced user files,
installs the KB runtime, links configuration, installs agent instructions and
skills, and runs verification.

### Test layer

`tests/` contains shell-based integration and E2E checks for workstation
behavior. `kb/tests/` tests the Python knowledge core. `bootstrap/verify.sh`
combines installed-state checks for the current reference distribution.

## Repository Map

```text
kb/             governed knowledge package and CLI
configs/kb/     schemas, templates, registries, and migration scopes
configs/agents/ shared instructions, skills, hooks, and adapters
scripts/        user commands, capture adapters, launchers, and installers
configs/        engineering reference integration
bootstrap/      idempotent installation and full verification
tests/          integration and workstation E2E checks
docs/           product, workflow, and operational documentation
adr/            architecture decisions
```

## Evolution Rule

New integrations should depend on the knowledge core through explicit,
testable contracts. Core governance must not depend on tmux, Neovim, a coding
repository, or a particular agent vendor. The current packaging may remain
combined until a standalone distribution is useful, but documentation and new
code should preserve this boundary now.
Integrations must also preserve OKF portability rather than making an
EOS-specific database the source of truth.
