local root = assert(vim.env.EOS_TEST_ROOT)
vim.opt.runtimepath:append(root .. "/configs/nvim")

vim.defer_fn(function()
  vim.api.nvim_err_writeln("WezTerm agent pane test timed out")
  vim.cmd("cquit 9")
end, 4000)

local panes = require("config.agent_panes")
panes.open("claude", "claude-personal; exec zsh")
assert(vim.wait(2000, function()
  if vim.fn.filereadable(vim.env.EOS_TEST_WEZTERM_LOG) ~= 1 then
    return false
  end
  for _, line in ipairs(vim.fn.readfile(vim.env.EOS_TEST_WEZTERM_LOG)) do
    if line:find("cli activate-pane", 1, true) then
      return true
    end
  end
  return false
end, 20), "agent pane was not created and activated")

panes.open("claude", "claude-personal; exec zsh")
assert(vim.wait(1000, function()
  return vim.fn.getfsize(vim.env.EOS_TEST_WEZTERM_STATE) == 0
end, 20), "existing agent pane was not closed")

panes.open("claude", "claude-personal; exec zsh")
assert(vim.wait(2000, function()
  local activations = 0
  for _, line in ipairs(vim.fn.readfile(vim.env.EOS_TEST_WEZTERM_LOG)) do
    if line:find("cli activate-pane", 1, true) then
      activations = activations + 1
    end
  end
  return activations >= 2
end, 20), "agent pane was not reopened")

vim.cmd("qa!")
