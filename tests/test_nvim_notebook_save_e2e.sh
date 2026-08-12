#!/usr/bin/env bash
set -euo pipefail

tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/eos-notebook-save.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT

empty_notebook="$tmpdir/empty.ipynb"
percent_notebook="$tmpdir/percent.ipynb"
autosave_notebook="$tmpdir/autosave.ipynb"
python_bin="$HOME/.local/share/eos/notebooks/.venv/bin/python3"

: > "$empty_notebook"
: > "$autosave_notebook"
cat > "$percent_notebook" <<'EOF'
# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %%
print("percent-recovery")
EOF

run_save() {
  local notebook="$1"
  XDG_CACHE_HOME="$tmpdir/cache" \
    XDG_STATE_HOME="$tmpdir/state" \
    JUPYTER_DATA_DIR="$tmpdir/jupyter" \
    nvim -i NONE --headless "$notebook" \
      "+lua assert(vim.bo.filetype == 'python'); assert(vim.api.nvim_buf_get_lines(0, 0, 1, false)[1] == '# ---')" \
      "+lua vim.api.nvim_buf_set_lines(0, -1, -1, false, {'', '# %%', 'print(\"saved\")'})" \
      "+write" "+sleep 2" "+qa!"
}

run_save "$empty_notebook"
run_save "$percent_notebook"

XDG_CACHE_HOME="$tmpdir/cache-autosave" \
  XDG_STATE_HOME="$tmpdir/state-autosave" \
  JUPYTER_DATA_DIR="$tmpdir/jupyter-autosave" \
  nvim -i NONE --headless "$autosave_notebook" \
    "+lua assert(vim.bo.filetype == 'python')" \
    "+lua vim.api.nvim_buf_set_lines(0, -1, -1, false, {'', '# %%', 'print(\"autosaved\")'}); vim.api.nvim_exec_autocmds('TextChanged', { buffer = 0 })" \
    "+sleep 5" "+qa!"

"$python_bin" - "$empty_notebook" "$percent_notebook" "$autosave_notebook" <<'PY'
import json
import sys

for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as stream:
        notebook = json.load(stream)
    assert notebook["nbformat"] == 4
    assert any(cell["cell_type"] == "code" for cell in notebook["cells"])

with open(sys.argv[3], encoding="utf-8") as stream:
    autosaved = json.load(stream)
assert any("autosaved" in "".join(cell.get("source", [])) for cell in autosaved["cells"])
PY

echo "nvim notebook save E2E ok"
