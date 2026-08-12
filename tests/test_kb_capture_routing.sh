#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
capture="$ROOT/scripts/eos-kb-capture"
reminder="$ROOT/scripts/eos-kb-pending-reminder"
[[ -x "$capture" ]]
[[ -x "$reminder" ]]

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
kb="$tmp/knowledge"
project="$tmp/project"
queue="$kb/projects/demo/_pending-kb-updates.md"
mkdir -p "$project" "$(dirname "$queue")"
printf '%s\n' '# Pending' '' '- [ ] Existing proposal.' >"$queue"

transcript="$tmp/session.jsonl"
printf '%s\n' \
  "{\"type\":\"session_meta\",\"payload\":{\"cwd\":\"$project\"}}" \
  '{"type":"message","text":"Changed projects/demo/00-index.md"}' >"$transcript"

output="$(DRY_RUN=1 EOS_CAPTURE_PROFILE=work EOS_CAPTURE_AGENT=claude \
  EOS_CAPTURE_KB_ROOT="$kb" EOS_CAPTURE_WORKSPACE_ROOT="$project" \
  EOS_CAPTURE_PROJECT_SLUG=demo "$capture" SessionEnd "$transcript")"
[[ "$output" == *"type: Log"* ]]
[[ "$output" == *'stale_after:'* ]]
[[ "$output" == *"$queue"* ]]
[[ "$output" == *"do not append an item that is already open"* ]]

text="$(EOS_CAPTURE_PROFILE=work EOS_CAPTURE_KB_ROOT="$kb" "$reminder" --text)"
[[ "$text" == *"1 pending work KB proposal(s)"* ]]
[[ "$text" == *"projects/demo/_pending-kb-updates.md: 1"* ]]

personal="$tmp/personal-knowledge"
mkdir -p "$personal/projects/private"
printf '%s\n' '# Pending' '' '- [ ] Personal only.' >"$personal/projects/private/_pending-kb-updates.md"
work_only="$(EOS_CAPTURE_PROFILE=work EOS_CAPTURE_KB_ROOT="$kb" "$reminder" --text)"
[[ "$work_only" != *"projects/private"* ]]

installed_work_kb="$tmp/installed-work-kb"
EOS_WORK_KNOWLEDGE_DIR="$installed_work_kb" "$ROOT/scripts/install-work-knowledge-indexes" >/dev/null
[[ -L "$installed_work_kb/bin/nova-kb-capture.sh" ]]
[[ "$(readlink "$installed_work_kb/bin/nova-kb-capture.sh")" == "$capture" ]]

echo "KB capture routing ok"
