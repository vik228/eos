# EOS

EOS is a personal, governed knowledge and context platform for AI agents.

Its core promise is simple: your knowledge should follow you across agents and
interfaces without becoming private memory trapped inside one product. EOS
keeps Markdown under your control, retrieves the context an agent needs, and
puts stable knowledge changes through an explicit review and promotion flow.

Knowledge is organized as **OKF-compatible Markdown bundles**. EOS builds on
the [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
instead of inventing a proprietary content store, so durable files remain
readable, versionable, and portable without EOS.

EOS is local-first. The knowledge base and supporting services run on your
machine by default, or on infrastructure you control. EOS sits between your
knowledge and agent harnesses through skills, lifecycle integrations, and an
planned MCP boundary; it does not require EOS-managed knowledge hosting.

The current reference integration is an agent-native macOS engineering
environment for Claude, Codex, and other coding agents. The product direction
extends the same user-controlled knowledge layer to web and app agent harnesses
and to workflows beyond coding.

## Why EOS

Agent conversations are useful but temporary. Important context gets buried in
transcripts, copied into incompatible memory systems, or silently rewritten
without a clear approval trail.

EOS separates those concerns:

- The user owns the canonical Markdown knowledge.
- OKF-compatible bundles keep that knowledge portable across tools.
- Agents retrieve only relevant context instead of loading everything.
- Session learnings become reviewable proposals rather than silent memory.
- Stable changes require explicit `propose -> review -> promote` governance.
- Work, personal, and project contexts remain independently routable.
- The same knowledge model can serve terminal, web, and app agent harnesses.

## What It Can Support

Consider one person using AI across their full knowledge life:

- A coding agent retrieves architecture decisions, reproduces a bug, and
  proposes a durable engineering lesson.
- A research agent resumes a paper discussion with its open questions and
  evaluation history.
- A learning agent adapts explanations to established preferences without
  depending on one vendor's private memory.
- A writing agent uses approved voice and project context.
- Finance and health conversations use their own private routes and never leak
  into a work session.

Today, EOS implements this most deeply for local terminal and coding-agent
workflows. Web/app harness access, broader non-coding adapters, and their exact
permission model remain planned work.

## How It Works

```text
Claude / Codex / future web and app harnesses
                    |
             skills, hooks, MCP
                    |
             EOS governance layer
       retrieval, routing, sessions, review
                    |
          user-controlled Markdown KB
      local machine or user-owned hosting
```

Markdown remains the durable source of truth. EOS maintains auditable derived
state for indexes, sessions, approvals, freshness, investigations, and
migrations. Agents do not need private copies of the user's knowledge.

### OKF-compatible by design

EOS uses the OKF bundle and concept model for portable Markdown knowledge:

- human-readable concepts with lightweight YAML frontmatter
- explicit routers connecting projects, areas, patterns, and references
- standard lifecycle, source, verification, and freshness metadata
- EOS extensions namespaced separately from standard OKF fields
- unknown concept types remain consumable instead of being locked out

SQLite indexes and EOS governance records add retrieval and trust behavior, but
they do not replace or trap the canonical OKF-compatible content.

## Current Quick Start

The current distribution installs the KB platform together with its macOS
engineering reference integration. It supports Apple Silicon and expects
Claude or Codex to be installed:

```bash
git clone https://github.com/vik228/eos.git ~/personal/eos
cd ~/personal/eos
scripts/eos setup
```

EOS installs the required instructions and skills, then starts a guided setup
conversation. The agent asks one question at a time about knowledge routes,
privacy boundaries, repositories, tools, workspaces, and response preferences.
It shows the proposed setup and waits for approval before applying it.

Choose an agent explicitly when both are available:

```bash
scripts/eos setup --agent claude
scripts/eos setup --agent codex
```

## Knowledge Capabilities Available Today

- Markdown-canonical personal and work knowledge spaces.
- OKF-compatible bundle validation and generated routers.
- Project and subject routing from a root index.
- Budgeted retrieval and search.
- Freshness and source-drift auditing.
- Explicit proposal, review, approval, and promotion records.
- Session start, checkpoint, recovery, and completion.
- Structured bug investigations with E2E evidence gates.
- Subject-aware session capture and duplicate suppression.
- Profile-scoped pending queues and reminders.
- Migration planning, approval binding, verification, and rollback.
- Direct-write protection for curated knowledge, with explicit working-register
  exceptions for logs and pending proposals.

See [Agent Knowledge System](docs/AGENT_KNOWLEDGE_SYSTEM.md) for the complete
model.

## Privacy and Control

EOS is designed around user ownership:

- Canonical knowledge stays in directories chosen by the user.
- OKF-compatible Markdown remains usable without EOS or a particular agent.
- Local operation is the default.
- Self-hosting on user-controlled infrastructure is part of the architecture.
- Work and personal routes are isolated by profile.
- Credentials and machine-specific context stay in ignored local files.
- Agents propose stable changes; the user approves what becomes knowledge.

The exact permission and consent model for exposing a local or self-hosted EOS
instance to third-party web/app harnesses is intentionally still open. EOS does
not currently claim a finished remote-access solution.

## Optional Integrations

### Engineering reference environment

The bundled macOS integration provides:

- isolated Claude, Codex, and OpenCode profiles
- shared agent instructions and workflow skills
- persistent tmux workspaces
- WezTerm, Neovim/LazyVim, zsh, Git, and Starship configuration
- notebook-style Python cells and inline Jupyter output
- Markdown preview with automatic refresh
- idempotent bootstrap, backups, and verification

Example workspace launches:

```bash
EOS_PROFILE=work backend
EOS_PROFILE=research research
EOS_PROFILE=writing write
```

### Future harness integrations

The intended expansion is to let Claude, ChatGPT, and similar web/app agent
harnesses use the same user-controlled KB through installable skills and MCP.
EOS should facilitate governed access, not take ownership of the knowledge.
The delivery and permission design will be developed separately and is tracked
in the [Roadmap](ROADMAP.md).

## What You Can Customize

- Knowledge ownership: local directories or user-controlled hosting.
- Routing: separate work, personal, project, and subject knowledge spaces.
- Agent behavior: explanation style, challenge level, pacing, and private
  profile context.
- Governance: retrieval budgets, freshness coverage, and approval workflows.
- Integrations: agents, tools, repositories, workspace windows, and commands.
- Identity: Git identities and machine-specific paths per profile.

The guided setup handles current configuration without requiring YAML or shell
knowledge. Advanced users can configure the same system directly. See
[Customization](docs/CUSTOMIZATION.md).

## Current Scope

The governed KB runtime is the product core. The repository still packages it
with an opinionated macOS engineering environment, and setup currently assumes
that distribution. A standalone non-engineering installer, third-party web/app
harness adapters, and a settled remote permission model do not exist yet.

This distinction is deliberate: engineering is the first mature integration,
not the boundary of the platform.

## Documentation

- Knowledge platform: [Agent Knowledge System](docs/AGENT_KNOWLEDGE_SYSTEM.md)
  and [Agent Profiles and Knowledge Paths](docs/AGENT_KNOWLEDGE.md)
- Product boundaries: [Architecture](ARCHITECTURE.md) and
  [Roadmap](ROADMAP.md)
- Current installation: [Installation](INSTALL.md), [Bootstrap](BOOTSTRAP.md),
  and [Customization](docs/CUSTOMIZATION.md)
- Engineering integration: [Productivity Guide](docs/PRODUCTIVITY.md),
  [Keybindings](docs/KEYBINDINGS.md), [Neovim Cheat Sheet](docs/NEOVIM_CHEATSHEET.md),
  and [Notebook Workflow](docs/NOTEBOOKS.md)
- Maintenance: [Testing](TESTING.md), [Migration](docs/MIGRATION.md),
  [Contributing](CONTRIBUTING.md), and [Changelog](CHANGELOG.md)

## License

EOS is available under the [MIT License](LICENSE).
