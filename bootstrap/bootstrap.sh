#!/usr/bin/env bash
set -euo pipefail

ROOT="${EOS_ROOT:-$HOME/personal/eos}"
source "$ROOT/scripts/lib-eos-config.sh"
BACKUP_ROOT="$ROOT/backups/$(date +%Y%m%d-%H%M%S)"

backup_path() {
  local path="$1"
  if [[ -e "$path" || -L "$path" ]]; then
    mkdir -p "$BACKUP_ROOT$(dirname "$path")"
    cp -a "$path" "$BACKUP_ROOT$path"
    echo "backed up: $path -> $BACKUP_ROOT$path"
  fi
}

link_file() {
  local link="$1"
  local target="$2"
  mkdir -p "$(dirname "$link")"
  if [[ -L "$link" && "$(readlink "$link")" == "$target" ]]; then
    echo "link ok: $link -> $target"
    return 0
  fi
  backup_path "$link"
  rm -rf "$link"
  ln -s "$target" "$link"
  echo "linked: $link -> $target"
}

echo "EOS bootstrap: $ROOT"

if [[ "${EOS_BOOTSTRAP_OFFLINE:-0}" == "1" ]]; then
  echo "offline bootstrap: skipping Homebrew and agent CLI network installs"
elif [[ -x /opt/homebrew/bin/brew ]]; then
  /opt/homebrew/bin/brew bundle --file "$ROOT/brew/Brewfile" || echo "brew bundle reported issues; continue and verify manually"
else
  echo "Homebrew missing at /opt/homebrew/bin/brew; install it before running brew bundle"
fi

mkdir -p "$EOS_WORK_ROOT" "$EOS_PERSONAL_ROOT" "$EOS_PERSONAL_KNOWLEDGE_ROOT" "$EOS_RESEARCH_ROOT" "$EOS_TOOLS_ROOT" "$HOME/.config/wezterm" "$HOME/.claude" "$HOME/.claude-work" "$HOME/.claude-personal" "$HOME/.codex" "$HOME/.codex-work" "$HOME/.codex-personal" "$HOME/.gemini" "$HOME/.opencode" "$HOME/.opencode-work" "$HOME/.opencode-personal" "$ROOT/bin"
mkdir -p "$HOME/.config/nvim/lua/config" "$HOME/.config/nvim/lua/plugins"

"$ROOT/scripts/setup-kb"

link_file "$HOME/.zshrc" "$ROOT/configs/shell/zshrc"
link_file "$HOME/.tmux.conf" "$ROOT/configs/tmux/tmux.conf"
"$ROOT/scripts/render-local-config"
GENERATED="${EOS_GENERATED_DIR:-$HOME/.config/eos/generated}"
link_file "$HOME/.gitconfig" "$GENERATED/git/gitconfig"
link_file "$HOME/.gitconfig-work" "$GENERATED/git/gitconfig-work"
link_file "$HOME/.gitconfig-personal" "$GENERATED/git/gitconfig-personal"
link_file "$HOME/.gitignore_global" "$ROOT/configs/git/gitignore_global"
link_file "$HOME/.config/starship.toml" "$ROOT/configs/starship/starship.toml"
link_file "$HOME/.wezterm.lua" "$ROOT/configs/wezterm/wezterm.lua"
link_file "$HOME/.config/wezterm/wezterm.lua" "$ROOT/configs/wezterm/wezterm.lua"
link_file "$HOME/.config/nvim/lua/config/autocmds.lua" "$ROOT/configs/nvim/lua/config/autocmds.lua"
link_file "$HOME/.config/nvim/lua/config/eos_keymaps.lua" "$ROOT/configs/nvim/lua/config/eos_keymaps.lua"
link_file "$HOME/.config/nvim/lua/config/markdown_preview.lua" "$ROOT/configs/nvim/lua/config/markdown_preview.lua"
link_file "$HOME/.config/nvim/lua/config/keymaps.lua" "$ROOT/configs/nvim/lua/config/keymaps.lua"
link_file "$HOME/.config/nvim/lua/config/options.lua" "$ROOT/configs/nvim/lua/config/options.lua"
link_file "$HOME/.config/nvim/lua/plugins/eos.lua" "$ROOT/configs/nvim/lua/plugins/eos.lua"
link_file "$HOME/.config/nvim/lua/plugins/notebooks.lua" "$ROOT/configs/nvim/lua/plugins/notebooks.lua"
link_file "$HOME/.config/nvim/lua/plugins/save.lua" "$ROOT/configs/nvim/lua/plugins/save.lua"

"$ROOT/scripts/install-agent-instructions"
"$ROOT/scripts/install-work-knowledge-indexes"
"$ROOT/scripts/install-personal-knowledge-indexes"
if [[ "${EOS_BOOTSTRAP_OFFLINE:-0}" != "1" ]]; then
  "${EOS_AGENT_CLI_INSTALLER:-$ROOT/scripts/install-agent-clis}"
fi
bash "$ROOT/scripts/install-codex-work-mcps"
bash "$ROOT/scripts/install-antigravity-mcps"
"$ROOT/scripts/install-kb-audit"

find "$ROOT/scripts" -maxdepth 1 -type f ! -name 'lib-*' -exec chmod +x {} +
chmod +x "$ROOT"/bootstrap/*.sh "$ROOT"/tests/*.sh

if [[ "${EOS_BOOTSTRAP_SKIP_VERIFY:-0}" != "1" ]]; then
  "$ROOT/scripts/eos" agent doctor
  "$ROOT/bootstrap/verify.sh"
fi

echo "Next steps:"
echo "  source ~/.zshrc"
echo "  eos doctor"
echo "  backend"
