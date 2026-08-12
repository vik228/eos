#!/usr/bin/env bash
set -euo pipefail

ROOT="${EOS_ROOT:-$HOME/personal/eos}"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:$ROOT/scripts:$ROOT/bin:$PATH"
status=0

run_check() {
  local name="$1"
  shift
  printf '%-28s' "$name"
  if "$@" >/tmp/eos-verify.log 2>&1; then
    echo "ok"
  else
    echo "fail"
    cat /tmp/eos-verify.log
    status=1
  fi
}

run_check "brew" test -x /opt/homebrew/bin/brew
for tool in git zsh starship tmux wezterm nvim uv node python3 mise; do
  run_check "$tool" command -v "$tool"
done
run_check "ImageMagick SIXEL" bash -c 'command -v magick >/dev/null && magick -list format | grep -qi sixel'

run_check "paths" "$ROOT/tests/test_paths.sh"
run_check "symlinks" "$ROOT/tests/test_symlinks.sh"
run_check "workspace scripts" "$ROOT/tests/test_workspace_scripts.sh"
run_check "declarative workspaces" "$ROOT/tests/test_declarative_workspaces.sh"
run_check "agent CLI updater" "$ROOT/tests/test_agent_clis.sh"
run_check "git profiles" "$ROOT/tests/test_git_profiles.sh"
run_check "open source config" "$ROOT/tests/test_open_source_config.sh"
run_check "profiles" "$ROOT/tests/test_profiles.sh"
run_check "agent-assisted setup" "$ROOT/tests/test_agent_assisted_setup.sh"
run_check "nvim notebooks" "$ROOT/tests/test_nvim_notebooks.sh"
run_check "notebook output E2E" "$ROOT/tests/test_nvim_notebook_output_e2e.sh"
run_check "notebook save E2E" "$ROOT/tests/test_nvim_notebook_save_e2e.sh"
run_check "nvim keymaps" "$ROOT/tests/test_nvim_keymaps.sh"
run_check "Markdown preview layout" "$ROOT/tests/test_nvim_markdown_preview.sh"
run_check "agent instructions" "$ROOT/tests/test_agent_instructions.sh"
run_check "agent sessions" "$ROOT/tests/test_agent_sessions.sh"
run_check "Claude hooks" "$ROOT/tests/test_claude_hooks.sh"
run_check "personal KB indexes" "$ROOT/tests/test_personal_knowledge_indexes.sh"
run_check "codex work MCPs" "$ROOT/tests/test_codex_work_mcps.sh"
run_check "Antigravity MCPs" "$ROOT/tests/test_antigravity_mcps.sh"
run_check "codex KB lifecycle" "$ROOT/tests/test_codex_kb_lifecycle.sh"
run_check "codex personal writes" "$ROOT/tests/test_codex_personal_writes.sh"
run_check "KB audit schedule" "$ROOT/tests/test_kb_audit_schedule.sh"
run_check "bootstrap idempotence" "$ROOT/tests/test_bootstrap_idempotence.sh"

echo "verify status: $status"
exit "$status"
