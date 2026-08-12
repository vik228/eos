#!/usr/bin/env bash
set -euo pipefail

tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/eos-notebook-output.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT

cat >"$tmpdir/queued-cells.py" <<'PYTHON'
# %%
print("eos-cell-one")
# %%
print("eos-cell-two")
# %%
print("eos-cell-three")
# %%
{"eos_cell": 4}
# %%
import time; [print(f"eos-long-{i}") for i in range(80)]; time.sleep(1); print("eos-long-finished")
PYTHON

cat >"$tmpdir/verify.lua" <<'LUA'
local function molten_outputs()
  local namespace = vim.api.nvim_get_namespaces()["molten-extmarks"]
  if not namespace then
    return {}
  end

  local outputs = {}
  for _, mark in ipairs(vim.api.nvim_buf_get_extmarks(0, namespace, 0, -1, { details = true })) do
    if mark[4].virt_lines then
      local lines = {}
      for _, virtual_line in ipairs(mark[4].virt_lines) do
        table.insert(lines, virtual_line[1] and virtual_line[1][1] or "")
      end
      table.insert(outputs, { row = mark[2], text = table.concat(lines, "\n") })
    end
  end
  return outputs
end

local expected = {
  ["eos-cell-one"] = 1,
  ["eos-cell-two"] = 3,
  ["eos-cell-three"] = 5,
  ["'eos_cell': 4"] = 7,
}

local function fail(message)
  vim.fn.writefile(vim.api.nvim_buf_get_lines(0, 0, -1, false), "/tmp/eos-notebook-output-e2e-failure.txt")
  vim.api.nvim_err_writeln(message)
  vim.cmd("cquit 1")
end

if not vim.wait(5000, function()
  return vim.fn.exists(":NotebookRunCellInline") == 2
end, 50) then
  fail("EOS notebook command was not registered")
  return
end

for _, row in ipairs({ 2, 4, 6, 8 }) do
  vim.api.nvim_win_set_cursor(0, { row, 0 })
  vim.cmd("NotebookRunCellInline")
end

local completed = vim.wait(20000, function()
  local found = 0
  for _, output in ipairs(molten_outputs()) do
    for needle, _ in pairs(expected) do
      if output.text:find(needle, 1, true) then
        found = found + 1
      end
    end
  end
  return found == 4
end, 100)

if not completed then
  fail("queued notebook outputs did not complete")
  return
end

for needle, expected_row in pairs(expected) do
  local actual_row = nil
  for _, output in ipairs(molten_outputs()) do
    if output.text:find(needle, 1, true) then
      actual_row = output.row
      break
    end
  end
  if actual_row ~= expected_row then
    fail(string.format("%s rendered at row %s instead of %d", needle, tostring(actual_row), expected_row))
    return
  end
end

vim.cmd("NotebookResetSession")
for _, row in ipairs({ 2, 4 }) do
  vim.api.nvim_win_set_cursor(0, { row, 0 })
  vim.cmd("NotebookRunCellInline")
end

local restarted = vim.wait(20000, function()
  local found = {}
  for _, output in ipairs(molten_outputs()) do
    if output.text:find("eos-cell-one", 1, true) then
      found.one = output.row == 1
    end
    if output.text:find("eos-cell-two", 1, true) then
      found.two = output.row == 3
    end
  end
  return found.one and found.two
end, 100)

if not restarted then
  fail("outputs shifted after restarting the Jupyter kernel")
  return
end

vim.api.nvim_win_set_cursor(0, { 10, 0 })
vim.cmd("NotebookRunCellInline")
if not vim.wait(10000, function()
  for _, output in ipairs(molten_outputs()) do
    if output.text:find("eos-long-0", 1, true) then
      return true
    end
  end
  return false
end, 50) then
  fail("live long output did not start")
  return
end

vim.cmd("NotebookOpenOutput")
if vim.bo.filetype ~= "molten_output" then
  fail("complete output window did not receive focus")
  return
end

if not vim.wait(5000, function()
  return vim.api.nvim_buf_line_count(0) >= 40
end, 50) then
  fail("complete output window did not expose all log lines")
  return
end

vim.api.nvim_win_set_cursor(0, { 30, 0 })
if not vim.wait(10000, function()
  return table.concat(vim.api.nvim_buf_get_lines(0, 0, -1, false), "\n"):find("eos-long-finished", 1, true) ~= nil
end, 50) then
  fail("live long output did not finish")
  return
end

if vim.api.nvim_win_get_cursor(0)[1] ~= 30 then
  fail("live output refresh reset the user's scroll position")
  return
end

vim.cmd("qa!")
LUA

nvim -i NONE --headless "$tmpdir/queued-cells.py" "+luafile $tmpdir/verify.lua"
