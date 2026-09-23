#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

python_bin="$ROOT/kb/.venv/bin/python"
[[ -x "$python_bin" ]] || python_bin="$(command -v python3)"
kb="$tmp/knowledge"
mkdir -p "$kb/areas" "$tmp/workspace"
printf '%s\n' '---' 'type: Note' 'title: Note' 'resource: kb:test/note' '---' '# Note' 'sharedterm' >"$kb/areas/note.md"
printf 'workspaces:\n  %s:\n    kb: %s\n    project: demo\n' "$tmp/workspace" "$kb" >"$tmp/workspaces.yaml"

run() {
  (cd "$tmp/workspace" && env -i HOME="$tmp/home" PATH="$PATH" EOS_ROOT="$ROOT" \
    EOS_CONFIG_FILE="$tmp/missing" EOS_PROFILE_ROOT="$tmp/profiles" \
    EOS_KB_STATE_ROOT="$tmp/state" EOS_KB_REGISTRY="$tmp/workspaces.yaml" \
    EOS_KB_PYTHON="$python_bin" PYTHONPATH="$ROOT/kb/src" EOS_AGENT_SESSION_ID="s1" "$@")
}

run "$python_bin" -c 'import sys; from pathlib import Path; from eos_kb.indexer import index_bundle; index_bundle(Path(sys.argv[1]))' "$kb"

# Empty log: resolves the KB from the workspace and reports zero calls.
[[ "$(run "$ROOT/scripts/eos-kb-usage" --json | "$python_bin" -c 'import json,sys; print(json.load(sys.stdin)["calls"])')" == "0" ]]

# A plain call followed by a --jev call in the same session is one escalation.
run "$ROOT/scripts/kb" context sharedterm --budget 2500 --json >/dev/null
run "$ROOT/scripts/kb" context sharedterm --budget 2500 --jev --json >/dev/null
summary="$(run "$ROOT/scripts/eos-kb-usage" --json)"
[[ "$("$python_bin" -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["calls"], d["plain_calls"], d["jev_calls"], d["escalations"])' "$summary")" == "2 1 1 1" ]]
run "$ROOT/scripts/eos-kb-usage" --since-days 1 | grep -q '^escalations: 1$'

# Invalid input is rejected before Python runs.
if run "$ROOT/scripts/eos-kb-usage" --since-days abc >/dev/null 2>&1; then
  echo "expected --since-days validation failure"
  exit 1
fi

echo "kb usage ok"
