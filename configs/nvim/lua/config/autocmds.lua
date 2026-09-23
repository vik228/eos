vim.api.nvim_create_autocmd("TextYankPost", {
  callback = function()
    vim.highlight.on_yank()
  end,
})

local function apply_eos_window_highlights()
  vim.api.nvim_set_hl(0, "EosStrongSplit", { fg = "#89b4fa", bg = "NONE", bold = true })
  vim.api.nvim_set_hl(0, "EosTerminalWinBar", { fg = "#11111b", bg = "#89b4fa", bold = true })
  vim.api.nvim_set_hl(0, "EosNotebookReplWinBar", { fg = "#11111b", bg = "#a6e3a1", bold = true })
  vim.api.nvim_set_hl(0, "EosAgentWinBar", { fg = "#11111b", bg = "#f9e2af", bold = true })
  vim.api.nvim_set_hl(0, "WinSeparator", { fg = "#89b4fa", bg = "NONE", bold = true })
end

apply_eos_window_highlights()

vim.api.nvim_create_autocmd("ColorScheme", {
  callback = apply_eos_window_highlights,
})

local notebook_reload_group = vim.api.nvim_create_augroup("EosNotebookReloadProtection", { clear = true })

vim.api.nvim_create_autocmd({ "BufReadPost", "BufEnter" }, {
  group = notebook_reload_group,
  pattern = "*.ipynb",
  callback = function(args)
    -- Notebook saves rewrite the JSON file outside Neovim. Reloading the live
    -- Jupytext buffer causes visible jitter and discards Molten's live output.
    vim.bo[args.buf].autoread = false
  end,
})

vim.api.nvim_create_autocmd("FileChangedShell", {
  group = notebook_reload_group,
  pattern = "*.ipynb",
  callback = function(args)
    -- Acknowledge the new disk timestamp without replacing the live notebook.
    vim.v.fcs_choice = "ignore"
    require("config.notebook_sync").external_change(args.buf)
  end,
})

local function check_external_file_changes()
  if vim.fn.mode() == "c" then
    return
  end
  pcall(vim.cmd, "checktime")
end

vim.api.nvim_create_autocmd({ "FocusGained", "BufEnter", "CursorHold", "CursorHoldI", "TermClose", "TermLeave" }, {
  group = vim.api.nvim_create_augroup("EosAutoReloadExternalChanges", { clear = true }),
  callback = check_external_file_changes,
})

vim.api.nvim_create_autocmd("FileChangedShellPost", {
  group = vim.api.nvim_create_augroup("EosExternalFileChangeNotice", { clear = true }),
  callback = function()
    vim.notify("Reloaded from disk: " .. vim.fn.expand("%:p"), vim.log.levels.INFO)
  end,
})

local function terminal_title()
  local name = vim.api.nvim_buf_get_name(0):lower()
  if name:find("ipython") or name:find("python") then
    return " PYTHON REPL ", "EosNotebookReplWinBar"
  end
  if name:find("claude") then
    return " CLAUDE AGENT ", "EosAgentWinBar"
  end
  if name:find("codex") then
    return " CODEX AGENT ", "EosAgentWinBar"
  end
  if name:find("antigravity") or name:find("agy") then
    return " ANTIGRAVITY AGENT ", "EosAgentWinBar"
  end
  return " TERMINAL ", "EosTerminalWinBar"
end

vim.api.nvim_create_autocmd("TermOpen", {
  callback = function()
    local title, title_hl = terminal_title()
    vim.opt_local.number = false
    vim.opt_local.relativenumber = false
    vim.opt_local.signcolumn = "no"
    vim.opt_local.winbar = "%#" .. title_hl .. "#" .. title .. "%*"
    vim.opt_local.winhighlight = "WinSeparator:EosStrongSplit"
  end,
})

vim.api.nvim_create_autocmd({ "BufNewFile", "BufReadPost", "BufEnter" }, {
  callback = function()
    vim.opt_local.swapfile = false
  end,
})
