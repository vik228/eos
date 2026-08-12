# EOS

EOS is an agent-configured engineering environment for people who work across
code, research, writing, and long-running AI sessions.

It turns a fresh macOS machine into a reproducible workspace with persistent
terminal sessions, Neovim, isolated agent profiles, shared instructions, and a
governed knowledge base. Instead of manually editing a collection of dotfiles,
you describe how you work and an agent builds a validated local profile for
you.

Today that experience starts in Claude or Codex from the terminal. The longer
term direction is to make the same guided setup available through agent-harness
web and app interfaces, so using EOS does not require shell or YAML knowledge.

## Quick Start

EOS currently supports macOS on Apple Silicon. Install Claude or Codex, then
run:

```bash
git clone https://github.com/vik228/eos.git ~/personal/eos
cd ~/personal/eos
scripts/eos setup
```

EOS detects the available agent, installs the required instructions and skills,
and starts a guided setup conversation. The agent asks one question at a time,
shows the proposed environment and workspace layout, and waits for approval
before applying anything.

If both agents are installed, choose one explicitly when needed:

```bash
scripts/eos setup --agent claude
scripts/eos setup --agent codex
```

## What the Result Can Look Like

Consider an AI/ML engineer who moves between product development, model
research, and technical writing.

Their EOS installation could provide three independent profiles:

- `work` opens the product repository, Neovim, service terminals, logs, and a
  work agent connected only to the work knowledge base and Git identity.
- `research` opens a paper implementation, notebook workflow, experiment
  terminals, research notes, and an agent tuned for first-principles
  discussion.
- `writing` opens Markdown notes with live preview and an agent configured for
  concise editing rather than software implementation.

Each workspace can be resumed after the terminal closes because tmux owns its
processes and state. The profiles can use different repositories, tools,
identities, knowledge roots, agent instructions, and layouts without changing
the public EOS repository.

Typical launch commands remain simple:

```bash
EOS_PROFILE=work backend
EOS_PROFILE=research research
EOS_PROFILE=writing write
```

The names are examples, not fixed roles. A user can create profiles for their
own projects, teams, learning tracks, or personal workflows.

## What You Can Customize

### How agents work with you

Choose how agents explain, challenge, pace, and structure their responses.
Profiles can carry different private context while still inheriting shared
safety, discussion, bug-investigation, and knowledge-management rules.

### What opens together

Define the tools and views that belong to a workflow: repositories, editors,
shells, notebooks, logs, previews, services, or agents. Workspaces are
declarative, validated before launch, and can inherit an existing layout with
small changes.

### Where knowledge lives

Route work and personal knowledge separately. Agents retrieve relevant context
from Markdown, capture reviewable suggestions, and require explicit approval
before changing curated knowledge. Pending reminders stay inside the active
profile, so a work session does not expose personal queues.

### Which identity and repositories apply

Set Git identity, project directories, knowledge roots, agent environment, and
private context per profile. Machine-specific and personal values stay in
ignored local files rather than the public repository.

The guided setup handles these choices without requiring users to understand
the underlying profile files or workspace YAML. Advanced users can configure
the same system directly. See [Customization](docs/CUSTOMIZATION.md).

## What EOS Includes

### Agent-native workflows

- Isolated default, work, and personal environments for Claude, Codex, and
  OpenCode, with shared support for Gemini-compatible tools and Antigravity.
- One rendered instruction baseline across supported agents.
- Mandatory workflows for exploratory discussions, bug investigation, and
  governed knowledge changes.
- Lifecycle hooks that refresh critical behavior and capture reviewable session
  learnings.

### Persistent workspaces

- Intent-based commands such as `backend`, `research`, `paper`, `algo`,
  `write`, and `agents`.
- tmux-owned sessions that survive terminal and editor restarts.
- Declarative layouts that can be validated and previewed before launch.
- Clear ownership boundaries: tmux manages processes, WezTerm renders the
  terminal, and Neovim remains the editor.

### Governed shared knowledge

- Markdown as the durable source of truth rather than private agent memory.
- Budgeted retrieval, search, freshness checks, and source-drift auditing.
- Explicit `propose -> review -> promote` governance for stable changes.
- Subject-aware capture with duplicate suppression and profile-scoped pending
  queues.
- Structured session and bug-investigation lifecycles.

### Focused Neovim workflows

- Notebook-style Python cells with inline Jupyter output.
- Markdown preview in a separate Neovim tab with automatic refresh.
- Agent terminals, project navigation, Git, diagnostics, testing, and terminal
  shortcuts.

### Reproducible local configuration

- Modular zsh, Git, tmux, WezTerm, Neovim, and Starship configuration.
- Homebrew dependencies declared in one Brewfile.
- Idempotent bootstrap with backups before replacing existing files.
- Verification for tools, symlinks, profiles, workspaces, hooks, and editor
  behavior.

## Current Scope

EOS is opinionated software, not a universal dotfiles framework. It currently
targets macOS on Apple Silicon and expects Homebrew under
`/opt/homebrew/bin/brew`. The defaults reflect an agent-heavy terminal workflow,
but identities, repositories, profiles, knowledge routes, agent behavior, and
workspace composition are designed to be replaced locally.

The terminal-based agent interview is the current onboarding interface.
Web/app onboarding and broader platform support are future work, not current
features. See the [Roadmap](ROADMAP.md).

## Daily Use

Launch or resume a workspace:

```bash
backend
research
write
```

Preview a layout without opening it:

```bash
EOS_PROFILE=research eos workspace preview research
```

Inspect knowledge or verify the installation:

```bash
eos kb context "task or symptom" --budget 2500
eos kb audit
eos doctor
```

See the [Productivity Guide](docs/PRODUCTIVITY.md) for the complete working
loop.

## Documentation

- Start here: [Installation](INSTALL.md) and
  [Agent-assisted customization](docs/CUSTOMIZATION.md)
- Everyday workflows: [Productivity Guide](docs/PRODUCTIVITY.md),
  [Keybindings](docs/KEYBINDINGS.md), and
  [Neovim Cheat Sheet](docs/NEOVIM_CHEATSHEET.md)
- Editor workflows: [Notebook Workflow](docs/NOTEBOOKS.md)
- Agent and knowledge model:
  [Agent Knowledge System](docs/AGENT_KNOWLEDGE_SYSTEM.md) and
  [Agent Profiles and Knowledge Paths](docs/AGENT_KNOWLEDGE.md)
- Internals and recovery: [Architecture](ARCHITECTURE.md),
  [Bootstrap](BOOTSTRAP.md), [Testing](TESTING.md), and
  [Migration](docs/MIGRATION.md)
- Project direction: [Roadmap](ROADMAP.md),
  [Contributing](CONTRIBUTING.md), and [Changelog](CHANGELOG.md)

## License

EOS is available under the [MIT License](LICENSE).
