#!/usr/bin/env bash
# Run-and-advance must append after the current cell's body, never split it
# at the cursor. Verified through the real Shift+Enter path in headless nvim.
set -euo pipefail

tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/eos-notebook-advance.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT

cat >"$tmpdir/cells.py" <<'PYTHON'
# %%
print(1)
PYTHON

cat >"$tmpdir/verify.lua" <<'LUA'
local results = {}
local function check(name, cond, detail)
  table.insert(results, (cond and "PASS " or "FAIL ") .. name .. (detail and (" | " .. detail) or ""))
end
local function lines()
  return table.concat(vim.api.nvim_buf_get_lines(0, 0, -1, false), "\n")
end
local function set_cells(body_lines)
  vim.api.nvim_buf_set_lines(0, 0, -1, false, body_lines)
end
local function press_shift_enter()
  vim.api.nvim_feedkeys("\27[13;2u", "x", false)
  vim.wait(8000)
end

local results_path = vim.fn.getenv("EOS_ADVANCE_TMP") .. "/results.txt"
if not vim.wait(60000, function()
  return vim.b.eos_notebook_buffer == true
end, 100) then
  vim.fn.writefile({ "FAIL notebook buffer was not set up" }, results_path)
  vim.cmd("cquit 1")
  return
end

-- Cursor in the middle of the final cell: append after the body, no split.
set_cells({ "# %%", "print(1)", "print(2)" })
vim.api.nvim_win_set_cursor(0, { 2, 0 })
press_shift_enter()
check("middle-final-no-split", lines() == "# %%\nprint(1)\nprint(2)\n\n# %%\n")

-- Cursor at the header and at the end of the final cell: same outcome.
set_cells({ "# %%", "print(1)", "print(2)" })
vim.api.nvim_win_set_cursor(0, { 1, 0 })
press_shift_enter()
check("header-final-no-split", lines() == "# %%\nprint(1)\nprint(2)\n\n# %%\n")

set_cells({ "# %%", "print(1)", "print(2)" })
vim.api.nvim_win_set_cursor(0, { 3, 0 })
press_shift_enter()
check("end-final-no-split", lines() == "# %%\nprint(1)\nprint(2)\n\n# %%\n")

-- Existing next cell: cursor moves, buffer untouched.
set_cells({ "# %%", "print(1)", "# %%", "print(2)" })
vim.api.nvim_win_set_cursor(0, { 2, 0 })
press_shift_enter()
check("next-cell-no-mutation", lines() == "# %%\nprint(1)\n# %%\nprint(2)")
check("next-cell-cursor-moved", vim.api.nvim_win_get_cursor(0)[1] == 4)

-- Empty final cell: append without error.
set_cells({ "# %%", "print(1)", "# %%" })
vim.api.nvim_win_set_cursor(0, { 3, 0 })
press_shift_enter()
check("empty-final-append", lines() == "# %%\nprint(1)\n# %%\n\n# %%\n")

-- Manual <leader>jc keeps cursor-position insertion.
set_cells({ "# %%", "print(1)", "print(2)" })
vim.api.nvim_win_set_cursor(0, { 2, 0 })
vim.api.nvim_feedkeys(" jc", "x", false)
vim.wait(5000)
check("manual-jc-at-cursor", lines() == "# %%\nprint(1)\n\n# %%\n\nprint(2)")

-- Insert-mode Shift+Enter takes the same advance path.
set_cells({ "# %%", "print(1)", "print(2)" })
vim.api.nvim_win_set_cursor(0, { 2, 7 })
vim.cmd("startinsert")
vim.api.nvim_feedkeys("\27[13;2u", "x", false)
vim.wait(8000)
check("insert-mode-no-split", lines() == "# %%\nprint(1)\nprint(2)\n\n# %%\n")

vim.fn.writefile(results, results_path)
local failed = 0
for _, result in ipairs(results) do
  if result:sub(1, 4) == "FAIL" then
    failed = failed + 1
  end
end
if failed > 0 then
  vim.api.nvim_err_writeln(failed .. " advance case(s) failed")
  vim.cmd("cquit 1")
  return
end
vim.cmd("qa!")
LUA

export EOS_ADVANCE_TMP="$tmpdir"
nvim -i NONE --headless "$tmpdir/cells.py" "+luafile $tmpdir/verify.lua" 2>/tmp/eos-advance-e2e-stderr.txt &
nvim_pid=$!
waited=0
while kill -0 "$nvim_pid" 2>/dev/null; do
  sleep 5
  waited=$((waited + 5))
  if [[ "$waited" -gt 280 ]]; then
    kill -9 "$nvim_pid" 2>/dev/null || true
    echo "advance e2e timed out" >&2
    exit 1
  fi
done
wait "$nvim_pid" || true
[[ -f "$tmpdir/results.txt" ]] || { echo "advance e2e produced no results" >&2; exit 1; }
cat "$tmpdir/results.txt"
grep -q "^FAIL" "$tmpdir/results.txt" && exit 1
echo "notebook advance e2e ok"
