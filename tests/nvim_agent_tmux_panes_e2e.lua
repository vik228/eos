local root = assert(vim.env.EOS_TEST_ROOT)
vim.opt.runtimepath:append(root .. "/configs/nvim")

local panes = require("config.agent_panes")
panes.open("claude", "claude-work; exec zsh")
assert(vim.wait(2000, function()
  return vim.fn.filereadable(vim.env.EOS_TEST_TMUX_STATE) == 1
end, 20), "tmux agent pane was not created")
vim.wait(300)
panes.open("claude", "claude-work; exec zsh")
assert(vim.wait(1000, function()
  return vim.fn.getfsize(vim.env.EOS_TEST_TMUX_STATE) == 0
end, 20), "existing tmux agent pane was not closed")
panes.open("claude", "claude-work; exec zsh")
assert(vim.wait(2000, function()
  local selections = 0
  for _, line in ipairs(vim.fn.readfile(vim.env.EOS_TEST_TMUX_LOG)) do
    if line:find("select-pane -t %42", 1, true) then
      selections = selections + 1
    end
  end
  return selections >= 2
end, 20), "tmux agent pane was not reopened")
vim.cmd("qa!")
