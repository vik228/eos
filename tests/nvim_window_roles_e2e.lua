local root = assert(vim.env.EOS_TEST_ROOT)
local first = assert(vim.env.EOS_TEST_FIRST)
local second = assert(vim.env.EOS_TEST_SECOND)

vim.defer_fn(function()
  vim.api.nvim_err_writeln("native protected window test timed out")
  vim.cmd("cquit 9")
end, 3000)

vim.opt.runtimepath:append(root .. "/configs/nvim")
local roles = require("config.window_roles")

vim.cmd.edit(vim.fn.fnameescape(first))
local editor_win = vim.api.nvim_get_current_win()
vim.cmd("vsplit | enew")
local agent_win = vim.api.nvim_get_current_win()
local agent_buf = vim.api.nvim_get_current_buf()
roles.protect_terminal(agent_win, agent_buf, "repl")

assert(vim.wo[agent_win].winfixbuf, "agent window is not natively protected")
local switched = pcall(vim.api.nvim_win_set_buf, agent_win, vim.fn.bufadd(second))
assert(not switched, "normal file replaced a winfixbuf-protected agent window")
assert(vim.api.nvim_win_get_buf(agent_win) == agent_buf, "agent buffer changed despite native protection")

assert(roles.focus_editor() == editor_win, "navigation did not choose the editor pane")
assert(vim.api.nvim_get_current_win() == editor_win, "navigation focus remained in the agent pane")
vim.cmd.edit(vim.fn.fnameescape(second))
assert(vim.uv.fs_realpath(vim.api.nvim_buf_get_name(0)) == vim.uv.fs_realpath(second), "selected file did not open in editor pane")

-- A split made while the agent owns focus must not inherit its role or winbar.
vim.api.nvim_set_current_win(agent_win)
vim.cmd("split")
local child_win = vim.api.nvim_get_current_win()
assert(child_win ~= agent_win, "split was not created")
assert(vim.w[child_win].eos_window_role == nil, "new split inherited terminal ownership")
assert(not vim.wo[child_win].winfixbuf, "new split inherited agent buffer protection")
assert(vim.wo[child_win].winbar == "", "new split inherited the agent winbar")

vim.cmd("qa!")
