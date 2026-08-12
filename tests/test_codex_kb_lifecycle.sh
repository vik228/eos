#!/usr/bin/env bash
set -euo pipefail

ROOT="${EOS_ROOT:-$HOME/personal/eos}"

scripts=(
  codex-work
  codex-work-kb-capture
  codex-work-kb-pending-reminder
)

for script in "${scripts[@]}"; do
  path="$ROOT/scripts/$script"
  [[ -f "$path" ]] || { echo "missing script: $path"; exit 1; }
  [[ -x "$path" ]] || { echo "script not executable: $path"; exit 1; }
  bash -n "$path"
done

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

kb="$tmp_dir/knowledge"
project_dir="$tmp_dir/work-project"
project_slug="work-project"
mkdir -p "$project_dir"
project_real="$(cd "$project_dir" && pwd -P)"
pending="$kb/projects/$project_slug/_pending-kb-updates.md"
mkdir -p "$(dirname "$pending")"
cat >"$pending" <<'MD'
# Pending KB updates (review then apply)

## 2026-07-07 - test

- [ ] Add one thing.
- [x] Already applied.
- [ ] Add another thing.
MD

text_output="$(EOS_WORK_PROJECT_SLUG="$project_slug" EOS_WORK_KNOWLEDGE_ROOT="$kb" "$ROOT/scripts/codex-work-kb-pending-reminder" --text)"
[[ "$text_output" == *"2 pending work KB proposal(s)"* ]]
[[ "$text_output" == *"$pending"* ]]

json_output="$(EOS_WORK_PROJECT_SLUG="$project_slug" EOS_WORK_KNOWLEDGE_ROOT="$kb" "$ROOT/scripts/codex-work-kb-pending-reminder" --json)"
[[ "$json_output" == *'"additional_context"'* ]]
[[ "$json_output" == *"2 unreviewed work KB update proposals"* ]]

transcript="$tmp_dir/session.jsonl"
cat >"$transcript" <<JSONL
{"type":"session_meta","payload":{"cwd":"$project_dir"}}
{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Worked on the project."}]}}
JSONL

capture_output="$(DRY_RUN=1 EOS_BACKEND_DIR="$project_dir" EOS_WORK_PROJECT_SLUG="$project_slug" EOS_WORK_KNOWLEDGE_ROOT="$kb" "$ROOT/scripts/codex-work-kb-capture" SessionEnd "$transcript")"
[[ "$capture_output" == *"would run: CODEX_HOME="* ]]
[[ "$capture_output" == *"codex exec"* ]]
[[ "$capture_output" == *"$transcript"* ]]
[[ "$capture_output" == *"$pending"* ]]

missing_output="$(DRY_RUN=1 EOS_WORK_KNOWLEDGE_ROOT="$kb" "$ROOT/scripts/codex-work-kb-capture" SessionEnd "$tmp_dir/missing.jsonl")"
[[ "$missing_output" == *"skip: transcript missing"* ]]

work_output="$(EOS_WORK_KNOWLEDGE_ROOT="$kb" CODEX_HOME="$tmp_dir/codex-home" CODEX_WORK_DIR="$project_dir" "$ROOT/scripts/codex-work" --dry-run)"
[[ "$work_output" == *"codex "* ]]
[[ "$work_output" == *"--ask-for-approval never"* ]]
[[ "$work_output" == *"--cd $project_real"* ]]
[[ "$work_output" == *"--sandbox danger-full-access"* ]]
[[ "$work_output" == *"sandbox_permissions=[\"disk-full-read-access\"]"* ]]
[[ "$work_output" == *"sandbox_workspace_write.network_access=true"* ]]
[[ "$work_output" == *"--add-dir $project_real"* ]]
[[ "$work_output" == *"--add-dir $kb"* ]]
[[ "$work_output" == *"post-session capture routed through EOS session"* ]]

no_read_output="$(EOS_WORK_KNOWLEDGE_ROOT="$kb" CODEX_WORK_SANDBOX_CONFIG="" CODEX_HOME="$tmp_dir/codex-home" CODEX_WORK_DIR="$project_dir" "$ROOT/scripts/codex-work" --dry-run)"
[[ "$no_read_output" != *"sandbox_permissions="* ]]
[[ "$no_read_output" == *"sandbox_workspace_write.network_access=true"* ]]
[[ "$no_read_output" == *"--add-dir $kb"* ]]

no_network_output="$(EOS_WORK_KNOWLEDGE_ROOT="$kb" CODEX_WORK_NETWORK_ACCESS=0 CODEX_HOME="$tmp_dir/codex-home" CODEX_WORK_DIR="$project_dir" "$ROOT/scripts/codex-work" --dry-run)"
[[ "$no_network_output" != *"sandbox_workspace_write.network_access=true"* ]]

no_work_write_output="$(EOS_WORK_KNOWLEDGE_ROOT="$kb" CODEX_WORK_ADD_WORK_DIR=0 CODEX_HOME="$tmp_dir/codex-home" CODEX_WORK_DIR="$project_dir" "$ROOT/scripts/codex-work" --dry-run)"
[[ "$no_work_write_output" == *"--cd $project_real"* ]]
[[ "$no_work_write_output" != *"--add-dir $project_real"* ]]

no_kb_write_output="$(EOS_WORK_KNOWLEDGE_ROOT="$kb" CODEX_WORK_ADD_KB_DIR=0 CODEX_HOME="$tmp_dir/codex-home" CODEX_WORK_DIR="$project_dir" "$ROOT/scripts/codex-work" --dry-run)"
[[ "$no_kb_write_output" != *"--add-dir $kb"* ]]

other_output="$(EOS_WORK_KNOWLEDGE_ROOT="$kb" CODEX_HOME="$tmp_dir/codex-home" CODEX_WORK_DIR="$tmp_dir/other" "$ROOT/scripts/codex-work" --dry-run)"
[[ "$other_output" == *"post-session capture routed through EOS session"* ]]

echo "codex KB lifecycle ok"
