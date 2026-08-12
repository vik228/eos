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
