# EOS

EOS is a personal engineering operating system for running a reproducible,
agent-native development environment on macOS.

It started as dotfiles and workspace automation. It now manages the complete
local workflow around them: terminal workspaces, Neovim, isolated AI-agent
profiles, shared instructions, governed knowledge, session lifecycle, bug
investigations, bootstrap, and verification.

The goal is simple: a new shell, editor, agent session, or machine should enter
the same known operating environment instead of relying on remembered setup or
agent-specific state.

## What EOS Owns

### Reproducible workstation configuration

- Modular configuration for zsh, Git, tmux, WezTerm, Neovim, and Starship.
- Homebrew dependencies declared in one Brewfile.
- Idempotent bootstrap with backups before replacing existing files.
- Directory-aware work and personal Git identities.
- Shell-based verification of tools, links, profiles, workflows, and behavior.

### Persistent, intent-based workspaces

Semantic commands create or attach to tmux workspaces for backend engineering,
research, papers, algorithm practice, writing, and agent coordination:

```bash
backend
research
paper
algo
leetcode
write
agents
```

tmux owns persistent processes and project state. WezTerm owns rendering and OS
integration. Neovim remains the editor rather than becoming the lifecycle owner
for long-running agents.

### Agent-native development

EOS provides isolated default, work, and personal profiles for Claude, Codex,
and OpenCode, plus shared configuration for Gemini-compatible tools and
Antigravity.

It renders one cross-agent instruction baseline that covers:

- repository and knowledge routing
- engineering and collaboration rules
- discussion behavior across every repository and session
- bug-investigation gates
- knowledge proposal and approval rules
- language, attribution, and safety invariants

Claude lifecycle hooks refresh critical instructions after session start and
context compaction. Agent launchers select the correct profile, workspace, KB,
permissions, and lifecycle behavior instead of depending on manual flags.

### Governed shared knowledge

EOS includes a Markdown-canonical knowledge system used across supported
agents. Markdown remains the source of truth; indexes, audit state, session
records, and approval records are derived or auditable state.

The `kb` CLI supports:

- budgeted context retrieval and search
- freshness and source-drift auditing
- explicit `propose -> review -> promote` governance
- session start, checkpoint, recovery, and completion
- structured bug investigations with E2E evidence requirements
- migration planning, approval binding, verification, and rollback
- subject-aware pending queues for work and personal knowledge

Stable knowledge cannot be silently rewritten by an agent. Pending queues and
logs remain writable working registers; curated knowledge changes require
explicit approval.

See [Agent Knowledge System](docs/AGENT_KNOWLEDGE_SYSTEM.md) for the operating
model and [Agent Knowledge Base](docs/AGENT_KNOWLEDGE.md) for installed profiles
and paths.

### Focused Neovim workflows

The LazyVim-based configuration adds practical local workflows without making
Neovim responsible for the whole environment:

- notebook-style Python cells and inline Jupyter output
- agent terminals opened inside the editor when useful
- Markdown preview with Glow and automatic refresh
- project navigation, Git, diagnostics, testing, and terminal shortcuts

See [Neovim Cheat Sheet](docs/NEOVIM_CHEATSHEET.md),
[Keybindings](docs/KEYBINDINGS.md), and [Notebooks](docs/NOTEBOOKS.md).

## Architecture

```text
brew/           Homebrew dependency manifest
configs/        Tool, agent, KB, editor, and launchd configuration
scripts/        Semantic workspaces, agent launchers, KB tools, and installers
bootstrap/      Idempotent installation and full verification
tests/          Shell E2E checks and KB Python test suite
kb/             The Python knowledge-system package and CLI
docs/           Daily workflows, keybindings, migration, and system design
adr/            Architecture decisions
```

The main ownership boundaries are:

1. `configs/` declares the desired local environment.
2. `scripts/` exposes stable user-facing commands and lifecycle automation.
3. `bootstrap/` installs that state safely into the home directory.
4. `tests/` and `bootstrap/verify.sh` validate the workstation contract.
5. `kb/` provides durable, cross-agent context without private memory copies.

## Installation

EOS currently targets macOS on Apple Silicon and expects Homebrew at
`/opt/homebrew/bin/brew`.

```bash
git clone <repository-url> ~/personal/eos
cd ~/personal/eos
cp eos.local.example .eos.local
$EDITOR .eos.local
bootstrap/bootstrap.sh
source ~/.zshrc
eos doctor
```

Bootstrap is idempotent. Any replaced file is backed up under:

```text
~/personal/eos/backups/<timestamp>/
```

For more detail, see [Installation](INSTALL.md) and [Bootstrap](BOOTSTRAP.md).

Copy `eos.local.example` to the ignored `.eos.local` file before bootstrap to
set identity, project paths, KB roots, and workspace routing. See
[Customization](docs/CUSTOMIZATION.md).

Named user-owned profiles can then layer different work, personal, research,
or organization-specific settings and agent context without modifying EOS.

```bash
eos profile init work
eos profile init research
EOS_PROFILE=research research
```

Each profile has a private `config` overlay and `context.md` for agent-specific
instructions. For example, a research profile can change its repository, Git
identity, KB route, and choose whether Neovim runs inside tmux:

```bash
EOS_RESEARCH_DIR="$HOME/research/my-project"
EOS_RESEARCH_PROJECT_SLUG="my-research"
EOS_RESEARCH_TMUX=1
```

Workspace composition is declarative too. A profile can inherit an EOS layout
or define its own ordered windows and commands in YAML, then validate and
preview it before launch:

```bash
EOS_PROFILE=research eos workspace validate research
EOS_PROFILE=research eos workspace preview research
```

The installed `configure-eos-workspace` agent skill can interview a user about
their tools, layout, KB routing, and preferred agent response style, then build
the profile without requiring them to write YAML manually.

## Daily Use

Start or resume the main engineering workspace:

```bash
backend
```

Inspect a workspace layout without opening tmux:

```bash
backend --dry-run
```

Use another backend repository for one launch:

```bash
EOS_BACKEND_DIR="$HOME/work/other-backend" backend
```

Run knowledge operations through EOS:

```bash
eos kb context "task or symptom" --budget 2500
eos kb audit
eos kb status
```

Check or repair the installed environment:

```bash
eos doctor
bootstrap/verify.sh
```

The complete working loop is documented in the
[Productivity Guide](docs/PRODUCTIVITY.md).

## Core Toolchain

EOS currently integrates zsh, Homebrew, Git, tmux, WezTerm, Neovim/LazyVim,
Starship, uv, Python, Node, mise, fzf, ripgrep, fd, bat, eza, zoxide, jq, yq,
tree, lazygit, gh, btop, direnv, Glow, and the configured AI-agent CLIs.

## Design Principles

- Everything important is declared as code.
- Bootstrap and installers must be safe to rerun.
- Persistent work belongs in tmux; rendering belongs in WezTerm.
- Agent behavior should be shared, explicit, and testable.
- Durable knowledge belongs in the shared KB, not private agent memory.
- Stable knowledge changes require human approval.
- Bugs are reproduced from the user-visible path before implementation.
- Work and personal identities, credentials, agents, and knowledge stay
  separated by profile.
- Correctness, robustness, and maintainability outrank setup convenience.

## Verification

Run the full repository and installed-state checks with:

```bash
bootstrap/verify.sh
```

The suite checks bootstrap idempotence, symlinks, workspace commands, Git
profiles, agent launchers and instruction rendering, Claude hooks, KB lifecycle,
MCP installation, notebook behavior, and Neovim integrations.

KB package tests can also be run directly:

```bash
cd kb
uv run pytest
```

See [Testing](TESTING.md) for focused test commands.

## Documentation

- [Architecture](ARCHITECTURE.md)
- [Productivity Guide](docs/PRODUCTIVITY.md)
- [Agent Knowledge System](docs/AGENT_KNOWLEDGE_SYSTEM.md)
- [Agent Profiles and Knowledge Paths](docs/AGENT_KNOWLEDGE.md)
- [Keybindings](docs/KEYBINDINGS.md)
- [Neovim Cheat Sheet](docs/NEOVIM_CHEATSHEET.md)
- [Notebook Workflow](docs/NOTEBOOKS.md)
- [Migration and Recovery](docs/MIGRATION.md)
- [Customization](docs/CUSTOMIZATION.md)
- [Open-source Release Checklist](docs/OPEN_SOURCE_RELEASE.md)
- [Roadmap](ROADMAP.md)
- [Contributing](CONTRIBUTING.md)
