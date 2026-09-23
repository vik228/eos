local root = assert(vim.env.EOS_TEST_ROOT)
local fixture = assert(vim.env.EOS_TEST_NOTEBOOK)
local incoming = assert(vim.env.EOS_TEST_INCOMING_NOTEBOOK)
local jupytext = assert(vim.env.EOS_TEST_JUPYTEXT)

vim.opt.runtimepath:append(root .. "/configs/nvim")
dofile(root .. "/configs/nvim/lua/config/options.lua")
dofile(root .. "/configs/nvim/lua/config/autocmds.lua")
vim.cmd.edit(vim.fn.fnameescape(fixture))

local proc = vim.system({ jupytext, "--to", "py:percent", "--output", "-", fixture }, { text = true }):wait()
assert(proc.code == 0, proc.stderr)
local lines = vim.split(proc.stdout, "\n", { plain = true })
if lines[#lines] == "" then
  table.remove(lines)
end
vim.api.nvim_buf_set_lines(0, 0, -1, false, lines)
vim.bo.modified = false

local stable = vim.fn.search([[print("stable")]])
assert(stable > 0, "stable cell not found")
local output_ns = vim.api.nvim_create_namespace("molten-extmarks")
vim.api.nvim_buf_set_extmark(0, output_ns, stable - 1, 0, { virt_text = { { "OUTPUT", "Comment" } } })
vim.api.nvim_win_set_cursor(0, { stable, 0 })

vim.wait(1100)
assert(vim.uv.fs_copyfile(incoming, fixture))
vim.bo.modified = true
vim.cmd.checktime()

vim.wait(500)
local deferred_text = table.concat(vim.api.nvim_buf_get_lines(0, 0, -1, false), "\n")
assert(deferred_text:find([[print("before")]], 1, true), "agent change overwrote a dirty notebook")
vim.bo.modified = false

local synced = vim.wait(3000, function()
  local text = table.concat(vim.api.nvim_buf_get_lines(0, 0, -1, false), "\n")
  return text:find([[print("after")]], 1, true) ~= nil
end, 50)
assert(synced, "agent change was not synced")

local text = table.concat(vim.api.nvim_buf_get_lines(0, 0, -1, false), "\n")
local outputs = vim.api.nvim_buf_get_extmarks(0, output_ns, 0, -1, {})
assert(not text:find([[print("before")]], 1, true), "stale notebook text remained")
assert(#outputs == 1, "unchanged notebook output disappeared")
assert(math.abs(vim.api.nvim_win_get_cursor(0)[1] - stable) <= 1, "cursor jumped during notebook sync")
assert(not vim.bo.modified, "agent sync left notebook dirty")

vim.cmd("qa!")
