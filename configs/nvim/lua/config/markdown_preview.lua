local M = {}

local uv = vim.uv or vim.loop
local previews = {}
local module_dir = vim.fn.fnamemodify(debug.getinfo(1, "S").source:sub(2), ":h")
local style_path = module_dir .. "/markdown_preview_style.json"
local max_reading_width = 96
local preview_options = { "number", "relativenumber", "signcolumn", "wrap", "winbar" }

local function save_window_options(entry)
  entry.window_options = entry.window_options or {}
  for _, option in ipairs(preview_options) do
    entry.window_options[option] = vim.api.nvim_get_option_value(option, { win = entry.win })
  end
end

local function restore_window_options(entry)
  if not entry.window_options or not vim.api.nvim_win_is_valid(entry.win) then
    return
  end
  for option, value in pairs(entry.window_options) do
    pcall(vim.api.nvim_set_option_value, option, value, { win = entry.win })
  end
end

local function render_command(path, window_width)
  local available_width = math.max(20, window_width - 2)
  local reading_width = math.min(max_reading_width, available_width)
  local padding = math.max(0, math.floor((window_width - reading_width) / 2))

  -- Glow owns Markdown styling; awk only centers its fixed-width output.
  return {
    "sh",
    "-c",
    [[pad="$1"; shift; "$@" | awk -v pad="$pad" '{ printf "%*s%s\n", pad, "", $0 }']],
    "eos-markdown-preview",
    tostring(padding),
    "glow",
    "--style",
    style_path,
    "--width",
    tostring(reading_width),
    path,
  }
end

local function file_stamp(path)
  local stat = uv.fs_stat(path)
  if not stat then
    return nil
  end
  local mtime = stat.mtime or {}
  return table.concat({ stat.size or 0, mtime.sec or 0, mtime.nsec or 0 }, ":")
end

local function valid(entry)
  return entry
    and vim.api.nvim_win_is_valid(entry.win)
    and vim.w[entry.win].eos_window_role ~= "agent"
end

local function visible(entry)
  return valid(entry)
    and entry.buf
    and vim.api.nvim_buf_is_valid(entry.buf)
    and vim.api.nvim_win_get_buf(entry.win) == entry.buf
end

local function stop(entry)
  if entry.timer then
    entry.timer:stop()
    entry.timer:close()
    entry.timer = nil
  end
  previews[entry.path] = nil
end

local function close(entry)
  if not valid(entry) then
    stop(entry)
    return
  end
  if visible(entry) and entry.source_buf and vim.api.nvim_buf_is_valid(entry.source_buf) then
    vim.api.nvim_win_set_buf(entry.win, entry.source_buf)
  elseif visible(entry) and uv.fs_stat(entry.path) then
    vim.cmd.edit(vim.fn.fnameescape(entry.path))
  end
  restore_window_options(entry)
  if entry.buf and vim.api.nvim_buf_is_valid(entry.buf) then
    pcall(vim.api.nvim_buf_delete, entry.buf, { force = true })
  end
  stop(entry)
end

local function restore_cursor(entry, row)
  vim.schedule(function()
    if not visible(entry) then
      return
    end
    local line_count = vim.api.nvim_buf_line_count(entry.buf)
    pcall(vim.api.nvim_win_set_cursor, entry.win, { math.max(1, math.min(row, line_count)), 0 })
  end)
end

local function render(entry)
  if not valid(entry) then
    stop(entry)
    return
  end
  if entry.rendering then
    entry.pending = true
    return
  end
  if entry.buf and vim.api.nvim_buf_is_valid(entry.buf) and not visible(entry) then
    entry.dirty = true
    return
  end

  entry.rendering = true
  entry.pending = false
  entry.dirty = false
  local cursor = visible(entry) and vim.api.nvim_win_get_cursor(entry.win) or { 1, 0 }
  local old_buf = entry.buf

  vim.api.nvim_win_call(entry.win, function()
    if not visible(entry) then
      save_window_options(entry)
    end
    entry.buf = vim.api.nvim_create_buf(true, true)
    vim.api.nvim_buf_set_name(entry.buf, "markdown-preview://" .. entry.path .. "#" .. entry.buf)
    vim.api.nvim_win_set_buf(entry.win, entry.buf)
    vim.bo[entry.buf].bufhidden = "hide"
    vim.bo[entry.buf].buflisted = true
    vim.bo[entry.buf].swapfile = false
    vim.wo[entry.win].number = false
    vim.wo[entry.win].relativenumber = false
    vim.wo[entry.win].signcolumn = "no"
    vim.wo[entry.win].wrap = false
    vim.wo[entry.win].winbar = "%#EosTerminalWinBar# 󰽛  READ  " .. vim.fn.fnamemodify(entry.path, ":t") .. " %*"

    local width = vim.api.nvim_win_get_width(entry.win)
    vim.fn.termopen(render_command(entry.path, width), {
      on_exit = function()
        entry.rendering = false
        restore_cursor(entry, cursor[1])
        if entry.pending then
          vim.schedule(function()
            render(entry)
          end)
        end
      end,
    })
    vim.bo[entry.buf].filetype = "markdown-preview"
    vim.b[entry.buf].eos_markdown_preview_path = entry.path
    vim.keymap.set("n", "q", function()
      close(entry)
    end, { buffer = entry.buf, silent = true, desc = "Close Markdown preview" })
  end)

  if old_buf and vim.api.nvim_buf_is_valid(old_buf) and old_buf ~= entry.buf then
    pcall(vim.api.nvim_buf_delete, old_buf, { force = true })
  end
  entry.stamp = file_stamp(entry.path)
end

local function refresh_path(path)
  local entry = previews[path]
  if entry then
    entry.stamp = file_stamp(entry.path)
    if visible(entry) then
      render(entry)
    else
      entry.dirty = true
    end
  end
end

local function start_watch(entry)
  entry.timer = uv.new_timer()
  entry.timer:start(1000, 1000, vim.schedule_wrap(function()
    if not valid(entry) then
      stop(entry)
      return
    end
    local stamp = file_stamp(entry.path)
    if stamp and stamp ~= entry.stamp then
      if entry.source_buf and vim.api.nvim_buf_is_valid(entry.source_buf) then
        vim.api.nvim_buf_call(entry.source_buf, function()
          pcall(vim.cmd, "checktime")
        end)
      end
      entry.stamp = stamp
      if visible(entry) then
        render(entry)
      else
        entry.dirty = true
      end
    end
  end))
end

local group = vim.api.nvim_create_augroup("EosMarkdownPreview", { clear = true })
vim.api.nvim_create_autocmd({ "BufWritePost", "FileChangedShellPost" }, {
  group = group,
  pattern = { "*.md", "*.markdown" },
  callback = function(args)
    refresh_path(vim.api.nvim_buf_get_name(args.buf))
  end,
})

vim.api.nvim_create_autocmd("BufEnter", {
  group = group,
  callback = function(args)
    for _, entry in pairs(previews) do
      if entry.buf == args.buf and entry.dirty then
        vim.schedule(function()
          render(entry)
        end)
        return
      end
    end
  end,
})

vim.api.nvim_create_autocmd("BufLeave", {
  group = group,
  callback = function(args)
    for _, entry in pairs(previews) do
      if entry.buf == args.buf then
        restore_window_options(entry)
        return
      end
    end
  end,
})

vim.api.nvim_create_autocmd("BufWipeout", {
  group = group,
  callback = function(args)
    for _, entry in pairs(previews) do
      if entry.buf == args.buf and not entry.rendering then
        stop(entry)
        return
      end
    end
  end,
})

vim.api.nvim_create_autocmd("WinResized", {
  group = group,
  callback = function()
    for _, entry in pairs(previews) do
      if visible(entry) then
        render(entry)
      end
    end
  end,
})

function M.open()
  if vim.fn.executable("glow") ~= 1 then
    vim.notify("Markdown preview requires glow. Run: brew install glow", vim.log.levels.ERROR)
    return
  end

  local editor_win = require("config.window_roles").focus_editor()
  if not editor_win then
    vim.notify("Markdown preview needs an editor pane", vim.log.levels.WARN)
    return
  end
  local source_buf = vim.api.nvim_win_get_buf(editor_win)
  local preview_path = vim.b[source_buf].eos_markdown_preview_path
  if preview_path and previews[preview_path] then
    local entry = previews[preview_path]
    entry.win = editor_win
    entry.dirty = true
    render(entry)
    return
  end
  local path = vim.api.nvim_buf_get_name(source_buf)
  local filetype = vim.bo[source_buf].filetype
  if path == "" or (filetype ~= "markdown" and not path:match("%.md$") and not path:match("%.markdown$")) then
    vim.notify("Markdown preview requires a saved .md or .markdown file", vim.log.levels.WARN)
    return
  end

  local existing = previews[path]
  if valid(existing) then
    existing.win = editor_win
    existing.source_buf = source_buf
    vim.api.nvim_set_current_win(existing.win)
    vim.api.nvim_win_set_buf(existing.win, existing.buf)
    if existing.dirty then
      render(existing)
    end
    return
  elseif existing then
    stop(existing)
  end

  local entry = {
    path = path,
    source_buf = source_buf,
    win = editor_win,
    stamp = file_stamp(path),
    rendering = false,
    pending = false,
    dirty = true,
  }
  previews[path] = entry
  render(entry)
  start_watch(entry)
end

return M
