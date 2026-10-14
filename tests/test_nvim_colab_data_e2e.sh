#!/usr/bin/env bash
# :ColabData runs the code cell carrying # eos-data, never a markdown cell
# that merely mentions it. Verified headless with the real config.
set -euo pipefail

tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/eos-notebook-colabdata.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT

cat >"$tmpdir/cells.py" <<'PYTHON'
# %%
print("warmup")
PYTHON

cat >"$tmpdir/verify.lua" <<'LUA'
local function molten_texts()
  local namespace = vim.api.nvim_get_namespaces()["molten-extmarks"]
  if not namespace then
    return ""
  end
  local parts = {}
  for _, mark in ipairs(vim.api.nvim_buf_get_extmarks(0, namespace, 0, -1, { details = true })) do
    if mark[4].virt_lines then
      for _, virtual_line in ipairs(mark[4].virt_lines) do
        table.insert(parts, virtual_line[1] and virtual_line[1][1] or "")
      end
    end
  end
  return table.concat(parts, "\n")
end

local results_path = vim.fn.getenv("EOS_COLABDATA_TMP") .. "/results.txt"
if not vim.wait(60000, function()
  return vim.b.eos_notebook_buffer == true
end, 100) then
  vim.fn.writefile({ "FAIL notebook buffer was not set up" }, results_path)
  vim.cmd("cquit 1")
  return
end

vim.api.nvim_buf_set_lines(0, 0, -1, false, {
  "# %% [markdown]",
  "# eos-data: decoy text that must not trigger the finder",
  "# %%",
  "# eos-data: probe",
  "print('eos-data-cell-ran')",
})
vim.cmd("ColabData")
local ok = vim.wait(90000, function()
  return molten_texts():find("eos-data-cell-ran", 1, true) ~= nil
end, 500)
vim.fn.writefile({ ok and "PASS colab-data-code-cell" or "FAIL colab-data-timeout" }, results_path)
vim.cmd("qa!")
LUA

export EOS_COLABDATA_TMP="$tmpdir"
nvim -i NONE --headless "$tmpdir/cells.py" "+luafile $tmpdir/verify.lua" 2>"$tmpdir/colabdata-stderr.txt" &
nvim_pid=$!
waited=0
while kill -0 "$nvim_pid" 2>/dev/null; do
  sleep 5
  waited=$((waited + 5))
  if [[ "$waited" -gt 280 ]]; then
    kill -9 "$nvim_pid" 2>/dev/null || true
    echo "colab data e2e timed out" >&2
    exit 1
  fi
done
wait "$nvim_pid" || true
[[ -f "$tmpdir/results.txt" ]] || { echo "colab data e2e produced no results" >&2; exit 1; }
cat "$tmpdir/results.txt"
grep -q "^FAIL" "$tmpdir/results.txt" && exit 1
echo "notebook colab data e2e ok"
