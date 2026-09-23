#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
first="$(mktemp -t eos-editor-first).md"
second="$(mktemp -t eos-editor-second).md"
trap 'unlink "$first" "$second" 2>/dev/null || true' EXIT
printf '# First\n' > "$first"
printf '# Second\n' > "$second"

output="$(EOS_TEST_ROOT="$ROOT" EOS_TEST_FIRST="$first" EOS_TEST_SECOND="$second" \
  nvim -i NONE --headless -u NONE \
  -c "lua dofile('$ROOT/tests/nvim_window_roles_e2e.lua')" 2>&1)" || {
  printf '%s\n' "$output" >&2
  exit 1
}
[[ "$output" != *"Error in command line"* ]] || {
  printf '%s\n' "$output" >&2
  exit 1
}

echo "nvim protected window routing ok"
