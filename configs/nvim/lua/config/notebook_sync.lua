local M = {}

local uv = vim.uv or vim.loop
local pending = {}

local function jupytext_bin()
  local candidate = vim.fn.expand("~/.local/share/eos/notebooks/.venv/bin/jupytext")
  return vim.fn.executable(candidate) == 1 and candidate or "jupytext"
end

local function disk_signature(path)
  local stat = uv.fs_stat(path)
  if not stat then
    return nil
  end
  local mtime = stat.mtime or {}
  return table.concat({ stat.size or 0, mtime.sec or 0, mtime.nsec or 0 }, ":")
end

local function split_lines(text)
  local lines = vim.split(text or "", "\n", { plain = true })
  if lines[#lines] == "" then
    table.remove(lines)
  end
  return lines
end

local function changed_range(current, incoming)
  local first = 1
  while first <= #current and first <= #incoming and current[first] == incoming[first] do
    first = first + 1
  end
  if first > #current and first > #incoming then
    return nil
  end

  local current_last = #current
  local incoming_last = #incoming
  while current_last >= first and incoming_last >= first and current[current_last] == incoming[incoming_last] do
    current_last = current_last - 1
    incoming_last = incoming_last - 1
  end
  return first, current_last, incoming_last
end

local function shifted_row(row, first, current_last, incoming_last)
  if row < first then
    return row
  end
  if row > current_last then
    return math.max(1, row + (incoming_last - current_last))
  end
  return math.max(first, math.min(row, incoming_last + 1))
end

local function apply_minimal_diff(bufnr, incoming)
  local current = vim.api.nvim_buf_get_lines(bufnr, 0, -1, false)
  local first, current_last, incoming_last = changed_range(current, incoming)
  if not first then
    return false
  end

  local replacement = {}
  for index = first, incoming_last do
    replacement[#replacement + 1] = incoming[index]
  end

  local views = {}
  for _, win in ipairs(vim.fn.win_findbuf(bufnr)) do
    views[win] = vim.api.nvim_win_call(win, vim.fn.winsaveview)
  end

  vim.api.nvim_buf_set_lines(bufnr, first - 1, current_last, false, replacement)
  vim.bo[bufnr].modified = false

  for win, view in pairs(views) do
    if vim.api.nvim_win_is_valid(win) then
      view.lnum = shifted_row(view.lnum, first, current_last, incoming_last)
      view.topline = shifted_row(view.topline, first, current_last, incoming_last)
      vim.api.nvim_win_call(win, function()
        vim.fn.winrestview(view)
      end)
    end
  end
  return true
end

local function finish(bufnr)
  local entry = pending[bufnr]
  if entry and entry.timer then
    entry.timer:stop()
    entry.timer:close()
  end
  pending[bufnr] = nil
end

local sync_now

local function retry(bufnr, path)
  local entry = pending[bufnr]
  if not entry then
    return
  end
  entry.attempts = (entry.attempts or 0) + 1
  if entry.attempts > 20 then
    finish(bufnr)
    vim.notify("Notebook changed on disk but is not valid yet", vim.log.levels.WARN)
    return
  end
  local delay = math.min(1000, 200 * (2 ^ math.min(entry.attempts - 1, 3)))
  entry.timer:start(delay, 0, vim.schedule_wrap(function()
    sync_now(bufnr, path, disk_signature(path))
  end))
end

sync_now = function(bufnr, path, signature)
  if not vim.api.nvim_buf_is_valid(bufnr) then
    finish(bufnr)
    return
  end
  if vim.bo[bufnr].modified then
    retry(bufnr, path)
    return
  end

  vim.system({ jupytext_bin(), "--to", "py:percent", "--output", "-", path }, { text = true }, function(proc)
    vim.schedule(function()
      if not vim.api.nvim_buf_is_valid(bufnr) then
        finish(bufnr)
        return
      end
      if proc.code ~= 0 or disk_signature(path) ~= signature then
        retry(bufnr, path)
        return
      end
      if vim.bo[bufnr].modified then
        retry(bufnr, path)
        return
      end
      local changed = apply_minimal_diff(bufnr, split_lines(proc.stdout))
      vim.b[bufnr].eos_notebook_disk_signature = signature
      finish(bufnr)
      if changed then
        vim.notify("Synced agent notebook changes", vim.log.levels.INFO)
      end
    end)
  end)
end

function M.record_self_write(bufnr, path)
  if vim.api.nvim_buf_is_valid(bufnr) then
    vim.b[bufnr].eos_notebook_disk_signature = disk_signature(path)
    vim.b[bufnr].eos_notebook_write_in_progress = false
  end
end

function M.external_change(bufnr)
  if not vim.api.nvim_buf_is_valid(bufnr) then
    return
  end
  if vim.b[bufnr].eos_notebook_write_in_progress then
    return
  end
  local path = vim.api.nvim_buf_get_name(bufnr)
  local signature = disk_signature(path)
  if signature and signature == vim.b[bufnr].eos_notebook_disk_signature then
    return
  end

  local entry = pending[bufnr]
  if not entry then
    entry = { timer = uv.new_timer(), attempts = 0 }
    pending[bufnr] = entry
  end
  entry.attempts = 0
  entry.timer:stop()
  entry.timer:start(200, 0, vim.schedule_wrap(function()
    sync_now(bufnr, path, disk_signature(path))
  end))
end

return M
