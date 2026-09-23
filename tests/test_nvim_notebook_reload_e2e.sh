#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/eos-notebook-sync.XXXXXX")"
trap 'find "$tmpdir" -type f -delete 2>/dev/null || true; rmdir "$tmpdir" 2>/dev/null || true' EXIT
jupytext="$HOME/.local/share/eos/notebooks/.venv/bin/jupytext"
fixture="$tmpdir/live.ipynb"
old_source="$tmpdir/old.py"
new_source="$tmpdir/new.py"
new_notebook="$tmpdir/new.ipynb"

printf '# %%%%\nprint("before")\n\n# %%%%\nprint("stable")\n' > "$old_source"
printf '# %%%%\nprint("after")\n\n# %%%%\nprint("stable")\n' > "$new_source"
"$jupytext" --to ipynb --output "$fixture" "$old_source" >/dev/null
"$jupytext" --to ipynb --output "$new_notebook" "$new_source" >/dev/null

output="$(EOS_TEST_ROOT="$ROOT" \
  EOS_TEST_NOTEBOOK="$fixture" \
  EOS_TEST_INCOMING_NOTEBOOK="$new_notebook" \
  EOS_TEST_JUPYTEXT="$jupytext" \
  nvim -i NONE --headless -u NONE \
  -c "lua dofile('$ROOT/tests/nvim_notebook_sync_e2e.lua')" 2>&1)" || {
  printf '%s\n' "$output" >&2
  exit 1
}
[[ "$output" != *"Error in command line"* ]] || {
  printf '%s\n' "$output" >&2
  exit 1
}

echo "nvim notebook agent sync ok"
