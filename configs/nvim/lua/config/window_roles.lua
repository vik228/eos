local M = {}

local function normal_window(win)
  return vim.api.nvim_win_is_valid(win)
    and vim.api.nvim_win_get_config(win).relative == ""
end

function M.editor_window(tabpage, protected_win)
  tabpage = tabpage or vim.api.nvim_get_current_tabpage()
  for _, win in ipairs(vim.api.nvim_tabpage_list_wins(tabpage)) do
    if win ~= protected_win and normal_window(win) and vim.w[win].eos_window_role == nil then
      local buf = vim.api.nvim_win_get_buf(win)
      if vim.bo[buf].buftype == "" then
        return win
      end
    end
  end
  for _, win in ipairs(vim.api.nvim_tabpage_list_wins(tabpage)) do
    if win ~= protected_win and normal_window(win) and vim.w[win].eos_window_role == nil then
      return win
    end
  end
end

function M.focus_editor()
  local current = vim.api.nvim_get_current_win()
  if vim.w[current].eos_window_role == nil then
    return current
  end
  local target = M.editor_window(vim.api.nvim_win_get_tabpage(current), current)
  if target then
    vim.api.nvim_set_current_win(target)
  end
  return target
end

function M.protect_terminal(win, buf, role)
  if not vim.api.nvim_win_is_valid(win) or not vim.api.nvim_buf_is_valid(buf) then
    return
  end
  vim.w[win].eos_window_role = role or "terminal"
  vim.w[win].eos_protected_buf = buf
  vim.api.nvim_set_option_value("winfixbuf", true, { win = win })
end

local group = vim.api.nvim_create_augroup("EosProtectedWindowRouting", { clear = true })

-- Window-local options and winbars are inherited by :split. A new split is
-- never automatically an agent pane; agent creation marks it explicitly later.
vim.api.nvim_create_autocmd("WinNew", {
  group = group,
  callback = function()
    local win = vim.api.nvim_get_current_win()
    if vim.w[win].eos_window_role ~= nil then
      vim.w[win].eos_window_role = nil
      vim.w[win].eos_protected_buf = nil
      vim.api.nvim_set_option_value("winfixbuf", false, { win = win })
      vim.api.nvim_set_option_value("winbar", "", { win = win })
    end
  end,
})

return M
