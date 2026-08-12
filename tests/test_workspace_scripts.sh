#!/usr/bin/env bash
set -euo pipefail

ROOT="${EOS_ROOT:-$HOME/personal/eos}"
source "$ROOT/scripts/lib-eos-config.sh"

scripts=(backend research paper algo leetcode write agents eos eos-workspace install-agent-clis install-codex-work-mcps install-antigravity-mcps codex-work codex-personal claude-personal opencode-personal opencode-work opencode-default codex-work-kb-capture codex-work-kb-pending-reminder antigravity-full)

for script in "${scripts[@]}"; do
  path="$ROOT/scripts/$script"
  [[ -f "$path" ]] || { echo "missing script: $path"; exit 1; }
  [[ -x "$path" ]] || { echo "script not executable: $path"; exit 1; }
  bash -n "$path"
done

"$ROOT/scripts/eos" --help >/dev/null
"$ROOT/scripts/backend" --dry-run >/dev/null
"$ROOT/scripts/research" --dry-run >/dev/null
"$ROOT/scripts/paper" --dry-run >/dev/null
"$ROOT/scripts/algo" --dry-run >/dev/null
"$ROOT/scripts/leetcode" --dry-run >/dev/null
"$ROOT/scripts/write" --dry-run >/dev/null
"$ROOT/scripts/agents" --dry-run >/dev/null
"$ROOT/scripts/eos" algo --dry-run >/dev/null
"$ROOT/scripts/eos" workspace validate backend >/dev/null
"$ROOT/scripts/eos" workspace preview backend >/dev/null

backend_output="$("$ROOT/scripts/backend" --dry-run)"
[[ "$backend_output" == *"window=editor:nvim \"$EOS_BACKEND_DIR\""* ]]
[[ "$backend_output" == *"window=claude:claude-work; exec zsh"* ]]
[[ "$backend_output" == *"codex-work"* ]]
[[ "$backend_output" == *"codex-work; exec zsh"* ]]
[[ "$backend_output" == *"antigravity-full; exec zsh"* ]]
tmp_backend_dir="$(mktemp -d)"
backend_override_output="$(EOS_BACKEND_DIR="$tmp_backend_dir" "$ROOT/scripts/backend" --dry-run)"
[[ "$backend_override_output" == *"directory=$tmp_backend_dir"* ]]
[[ "$backend_override_output" == *"window=editor:nvim \"$tmp_backend_dir\""* ]]
rm -rf "$tmp_backend_dir"
research_output="$("$ROOT/scripts/research" --dry-run)"
[[ "$research_output" == *"window=editor:nvim \"$EOS_RESEARCH_DIR\""* ]]
[[ "$research_output" == *"claude-personal; exec zsh"* ]]
[[ "$research_output" == *"codex-personal; exec zsh"* ]]
[[ "$research_output" == *"antigravity-full; exec zsh"* ]]
research_wezterm_output="$(TMUX= WEZTERM_PANE=99 "$ROOT/scripts/research" --dry-run)"
[[ "$research_wezterm_output" == *"editor=wezterm-direct:nvim \"$EOS_RESEARCH_DIR\""* ]]
[[ "$research_wezterm_output" == *"window=workspace:zsh"* ]]
[[ "$research_wezterm_output" == *"antigravity-full; exec zsh"* ]]
[[ "$research_wezterm_output" != *"window=editor:nvim"* ]]
paper_output="$("$ROOT/scripts/paper" --dry-run)"
[[ "$paper_output" == *"claude-personal; exec zsh"* ]]
agents_output="$("$ROOT/scripts/agents" --dry-run)"
[[ "$agents_output" == *"claude-work; exec zsh"* ]]
[[ "$agents_output" == *"codex-work"* ]]
[[ "$agents_output" == *"codex-work; exec zsh"* ]]
[[ "$agents_output" == *"claude-personal; exec zsh"* ]]
[[ "$agents_output" == *"codex-personal; exec zsh"* ]]
[[ "$agents_output" == *"antigravity-full; exec zsh"* ]]

codex_personal_output="$("$ROOT/scripts/codex-personal" --dry-run)"
[[ "$codex_personal_output" == *"CODEX_HOME=$HOME/.codex-personal codex"* ]]
[[ "$codex_personal_output" == *"--sandbox danger-full-access"* ]]
[[ "$codex_personal_output" == *"sandbox_permissions=[\"disk-full-read-access\"]"* ]]
[[ "$codex_personal_output" == *"sandbox_workspace_write.network_access=true"* ]]
[[ "$codex_personal_output" == *"--add-dir"* ]]
[[ "$codex_personal_output" == *"$HOME/personal/knowledge"* ]]
[[ "$codex_personal_output" == *"--ask-for-approval never"* ]]

claude_personal_output="$("$ROOT/scripts/claude-personal" --dry-run)"
[[ "$claude_personal_output" == *"CLAUDE_CONFIG_DIR=$HOME/.claude-personal $HOME/personal/eos/bin/claude --permission-mode auto"* ]]

opencode_personal_output="$("$ROOT/scripts/opencode-personal" --dry-run)"
[[ "$opencode_personal_output" == *"OPENCODE_CONFIG_DIR=$HOME/.opencode-personal $HOME/personal/eos/bin/opencode --auto"* ]]

antigravity_output="$("$ROOT/scripts/antigravity-full" --dry-run)"
[[ "$antigravity_output" == *"agy "* ]]
[[ "$antigravity_output" == *"--dangerously-skip-permissions"* ]]
[[ "$antigravity_output" == *"--add-dir"* ]]

echo "workspace scripts ok"
