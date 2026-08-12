#!/usr/bin/env bash
set -euo pipefail

ROOT="${EOS_ROOT:-$HOME/personal/eos}"

check_link() {
  local link="$1"
  local target="$2"
  [[ -L "$link" ]] || { echo "not a symlink: $link"; exit 1; }
  local actual
  actual="$(readlink "$link")"
  [[ "$actual" == "$target" ]] || {
    echo "bad symlink: $link"
    echo "  expected: $target"
    echo "  actual:   $actual"
    exit 1
  }
  [[ -e "$link" ]] || { echo "broken symlink: $link -> $target"; exit 1; }
}

check_link "$HOME/.zshrc" "$ROOT/configs/shell/zshrc"
check_link "$HOME/.tmux.conf" "$ROOT/configs/tmux/tmux.conf"
generated="$HOME/.config/eos/generated"
check_link "$HOME/.gitconfig" "$generated/git/gitconfig"
check_link "$HOME/.gitconfig-work" "$generated/git/gitconfig-work"
check_link "$HOME/.gitconfig-personal" "$generated/git/gitconfig-personal"
check_link "$HOME/.gitignore_global" "$ROOT/configs/git/gitignore_global"
check_link "$HOME/.config/starship.toml" "$ROOT/configs/starship/starship.toml"
check_link "$HOME/.wezterm.lua" "$ROOT/configs/wezterm/wezterm.lua"
check_link "$HOME/.config/wezterm/wezterm.lua" "$ROOT/configs/wezterm/wezterm.lua"
check_link "$HOME/.config/nvim/lua/config/autocmds.lua" "$ROOT/configs/nvim/lua/config/autocmds.lua"
check_link "$HOME/.config/nvim/lua/config/eos_keymaps.lua" "$ROOT/configs/nvim/lua/config/eos_keymaps.lua"
check_link "$HOME/.config/nvim/lua/config/markdown_preview.lua" "$ROOT/configs/nvim/lua/config/markdown_preview.lua"
check_link "$HOME/.config/nvim/lua/config/keymaps.lua" "$ROOT/configs/nvim/lua/config/keymaps.lua"
check_link "$HOME/.config/nvim/lua/config/options.lua" "$ROOT/configs/nvim/lua/config/options.lua"
check_link "$HOME/.config/nvim/lua/plugins/eos.lua" "$ROOT/configs/nvim/lua/plugins/eos.lua"
check_link "$HOME/.config/nvim/lua/plugins/notebooks.lua" "$ROOT/configs/nvim/lua/plugins/notebooks.lua"
check_link "$HOME/.config/nvim/lua/plugins/save.lua" "$ROOT/configs/nvim/lua/plugins/save.lua"
check_link "$HOME/.codex/AGENTS.md" "$generated/agents/AGENTS.md"
check_link "$HOME/.codex-work/AGENTS.md" "$generated/agents/AGENTS.md"
check_link "$HOME/.codex-personal/AGENTS.md" "$generated/agents/AGENTS.md"
check_link "$HOME/.gemini/GEMINI.md" "$generated/agents/GEMINI.md"
# Antigravity reads Gemini's global ~/.gemini/GEMINI.md policy.
check_link "$HOME/.claude/CLAUDE.md" "$generated/agents/CLAUDE.md"
check_link "$HOME/.claude-work/CLAUDE.md" "$generated/agents/CLAUDE.md"
check_link "$HOME/.claude-personal/CLAUDE.md" "$generated/agents/CLAUDE.md"

echo "symlinks ok"
