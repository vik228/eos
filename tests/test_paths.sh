#!/usr/bin/env bash
set -euo pipefail

ROOT="${EOS_ROOT:-$HOME/personal/eos}"

required_dirs=(
  adr
  docs
  bootstrap
  brew
  configs/git
  configs/shell
  configs/starship
  configs/tmux
  configs/wezterm
  configs/nvim/lua/config
  configs/nvim/lua/plugins
  configs/agents
  configs/workspaces
  scripts
  workspaces
  tests
  knowledge
  eos
  bin
)

required_files=(
  README.md
  LICENSE
  CHANGELOG.md
  TODO.md
  ROADMAP.md
  ARCHITECTURE.md
  INSTALL.md
  BOOTSTRAP.md
  TESTING.md
  CONTRIBUTING.md
  docs/KEYBINDINGS.md
  docs/MIGRATION.md
  docs/NOTEBOOKS.md
  docs/NEOVIM_CHEATSHEET.md
  docs/PRODUCTIVITY.md
  docs/AGENT_KNOWLEDGE.md
  configs/agents/common-knowledge.md
  configs/agents/AGENTS.md
  configs/agents/GEMINI.md
  configs/agents/CLAUDE.md
  brew/Brewfile
  bootstrap/bootstrap.sh
  bootstrap/verify.sh
  tests/test_bootstrap_idempotence.sh
  scripts/install-agent-instructions
  scripts/install-agent-clis
  scripts/install-work-knowledge-indexes
  scripts/eos-kb-capture
  scripts/eos-kb-pending-reminder
  scripts/setup-notebooks
  bin/claude
  knowledge/00-index.md
  knowledge/_pending-kb-updates.md
)

for path in "${required_dirs[@]}"; do
  [[ -d "$ROOT/$path" ]] || { echo "missing directory: $ROOT/$path"; exit 1; }
done

for path in "${required_files[@]}"; do
  [[ -f "$ROOT/$path" ]] || { echo "missing file: $ROOT/$path"; exit 1; }
done

echo "path layout ok"
