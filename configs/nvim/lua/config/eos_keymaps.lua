local M = {}

M.config = {
  clipboard = "unnamedplus",
  keys = {
    find_files = { "<D-k>", "<M-k>", "<leader>ff" },
    toggle_explorer = { "<leader>f", "<leader>e" },
    live_grep = { "<leader>sg" },
    current_buffer_search = { "<leader>/" },
    recent_files = { "<leader>fr" },
    buffers = { "<leader>bb" },
    save = { "<D-s>", "<M-s>", "<leader>w" },
    quit = { "<leader>q" },
    close_buffer = { "<leader>bd" },
    next_buffer = { "]b" },
    previous_buffer = { "[b" },
    diagnostics = { "<leader>xx" },
    format = { "<leader>cf" },
    copy_file_path = { "<leader>cp" },
    markdown_preview = { "<leader>mp" },
    claude_agent = { "<leader>ac" },
    codex_agent = { "<leader>ax" },
    antigravity_agent = { "<leader>ag" },
    opencode_agent = { "<leader>ao" },
    copy_explain_prompt = { "<leader>ae" },
    git_review = {
      file_diff = { "<leader>rd" },
      full_diff = { "<leader>rD" },
      preview_hunk = { "<leader>rp" },
      stage_hunk = { "<leader>rs" },
      reset_hunk = { "<leader>rr" },
      stage_file = { "<leader>rS" },
      reset_file = { "<leader>rR" },
      file_history = { "<leader>rh" },
    },
  },
  agent_terminals = {
    position = "right",
    width = 0.42,
    profiles = {
      work = {
        claude = 'claude-work; exec zsh',
        codex = 'codex-work; exec zsh',
        antigravity = "antigravity-full; exec zsh",
      },
      personal = {
        claude = "claude-personal; exec zsh",
        codex = "codex-personal; exec zsh",
        antigravity = "antigravity-full; exec zsh",
        opencode = "opencode-personal; exec zsh",
      },
    },
  },
}

local function snacks_picker(name, opts)
  return function()
    if _G.Snacks and Snacks.picker and Snacks.picker[name] then
      return Snacks.picker[name](opts or {})
    end

    local ok, telescope = pcall(require, "telescope.builtin")
    if ok and telescope[name] then
      return telescope[name](opts or {})
    end

    vim.notify("No picker available for " .. name, vim.log.levels.WARN)
  end
end

local function toggle_explorer()
  if _G.Snacks and Snacks.explorer then
    return Snacks.explorer()
  end

  local ok, oil = pcall(require, "oil")
  if ok then
    return oil.toggle_float()
  end

  vim.cmd("Explore")
end

local function format_buffer()
  vim.lsp.buf.format({ async = true })
end

local function copy_file_path()
  local path = vim.fn.expand("%:p")
  vim.fn.setreg("+", path)
  vim.notify("Copied path: " .. path)
end

local function current_profile()
  local home = vim.fn.expand("$HOME")
  local cwd = vim.fn.getcwd()
  if vim.startswith(cwd, home .. "/work") then
    return "work"
  end
  return "personal"
end

local function apply_strong_split_highlight(win)
  local current = vim.api.nvim_get_option_value("winhighlight", { win = win })
  local highlights = vim.tbl_filter(function(item)
    return not vim.startswith(item, "WinSeparator:")
  end, vim.split(current, ",", { plain = true, trimempty = true }))
  table.insert(highlights, "WinSeparator:EosStrongSplit")
  vim.api.nvim_set_option_value("winhighlight", table.concat(highlights, ","), { win = win })
end

local function style_agent_window(agent, profile)
  local title = " AGENT: " .. string.upper(agent) .. " [" .. profile .. "] "
  vim.opt_local.winbar = "%#EosAgentWinBar#" .. title .. "%*"
  vim.opt_local.number = false
  vim.opt_local.relativenumber = false
  vim.opt_local.signcolumn = "no"
  for _, win in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
    apply_strong_split_highlight(win)
  end
end

local function open_agent_terminal(agent)
  local profile = current_profile()
  local terminal_config = M.config.agent_terminals
  local command = terminal_config.profiles[profile][agent]

  if not command then
    vim.notify("Agent " .. agent .. " is not available in profile " .. profile, vim.log.levels.WARN)
    return
  end

  if _G.Snacks and Snacks.terminal then
    local terminal = Snacks.terminal({ "zsh", "-lc", command }, {
      cwd = vim.fn.getcwd(),
      interactive = true,
      auto_close = false,
      win = {
        position = terminal_config.position,
        width = terminal_config.width,
        border = "rounded",
        title = " AGENT: " .. string.upper(agent) .. " [" .. profile .. "] ",
        title_pos = "center",
        wo = {
          winhighlight = "WinSeparator:EosStrongSplit",
        },
      },
    })
    vim.schedule(function()
      pcall(style_agent_window, agent, profile)
    end)
    return terminal
  end

  vim.cmd("botright vertical terminal zsh -lc " .. vim.fn.shellescape(command))
  style_agent_window(agent, profile)
end

local function selected_or_current_lines(use_visual)
  local start_line
  local end_line

  if use_visual then
    start_line = vim.fn.line("'<")
    end_line = vim.fn.line("'>")
  else
    start_line = vim.fn.line(".")
    end_line = start_line
  end

  if start_line > end_line then
    start_line, end_line = end_line, start_line
  end

  local lines = vim.api.nvim_buf_get_lines(0, start_line - 1, end_line, false)
  return start_line, end_line, table.concat(lines, "\n")
end

local function copy_explain_prompt(use_visual)
  local file = vim.fn.expand("%:p")
  local start_line, end_line, code = selected_or_current_lines(use_visual)
  local prompt = table.concat({
    "Explain this code in context.",
    "",
    "File: " .. file,
    "Lines: " .. start_line .. "-" .. end_line,
    "",
    "Code:",
    "```",
    code,
    "```",
    "",
    "Focus on what it does, why it exists, important edge cases, and what I should inspect next.",
  }, "\n")

  vim.fn.setreg("+", prompt)
  vim.notify("Copied explain prompt for " .. vim.fn.fnamemodify(file, ":t") .. ":" .. start_line .. "-" .. end_line)
end

local function gitsigns_action(action)
  return function()
    local ok, gitsigns = pcall(require, "gitsigns")
    if not ok then
      vim.notify("gitsigns.nvim is not available", vim.log.levels.WARN)
      return
    end
    gitsigns[action]()
  end
end

local function gitsigns_range_action(action)
  return function()
    local ok, gitsigns = pcall(require, "gitsigns")
    if not ok then
      vim.notify("gitsigns.nvim is not available", vim.log.levels.WARN)
      return
    end
    local start_line = vim.fn.line(".")
    local end_line = vim.fn.line("v")
    if start_line > end_line then
      start_line, end_line = end_line, start_line
    end
    gitsigns[action]({ start_line, end_line })
  end
end

local function git_command(command)
  return function()
    vim.cmd(command)
  end
end

local function map_all(modes, keys, rhs, desc)
  for _, key in ipairs(keys) do
    vim.keymap.set(modes, key, rhs, { desc = desc, silent = true })
  end
end

function M.setup()
  vim.opt.clipboard = M.config.clipboard
  vim.opt.ignorecase = true
  vim.opt.smartcase = true
  vim.opt.incsearch = true
  vim.opt.hlsearch = true
  vim.opt.wrapscan = true

  local keys = M.config.keys

  map_all("n", keys.find_files, snacks_picker("files"), "Find files")
  map_all("n", keys.toggle_explorer, toggle_explorer, "Toggle file explorer")
  map_all("n", keys.live_grep, snacks_picker("grep"), "Search in project")
  map_all("n", keys.current_buffer_search, snacks_picker("lines"), "Search current file")
  map_all("n", keys.recent_files, snacks_picker("recent"), "Recent files")
  map_all("n", keys.buffers, snacks_picker("buffers"), "Open buffers")
  map_all("n", keys.save, "<cmd>write<cr>", "Save file")
  map_all("n", keys.quit, "<cmd>quit<cr>", "Quit window")
  map_all("n", keys.close_buffer, function()
    if _G.Snacks and Snacks.bufdelete then
      Snacks.bufdelete()
    else
      vim.cmd("bdelete")
    end
  end, "Close buffer")
  map_all("n", keys.next_buffer, "<cmd>bnext<cr>", "Next buffer")
  map_all("n", keys.previous_buffer, "<cmd>bprevious<cr>", "Previous buffer")
  map_all("n", keys.diagnostics, "<cmd>Trouble diagnostics toggle<cr>", "Diagnostics")
  map_all("n", keys.format, format_buffer, "Format buffer")
  map_all("n", keys.copy_file_path, copy_file_path, "Copy file path")
  map_all("n", keys.markdown_preview, function()
    require("config.markdown_preview").open()
  end, "Open formatted Markdown preview tab")
  map_all("n", keys.claude_agent, function()
    open_agent_terminal("claude")
  end, "Open Claude agent")
  map_all("n", keys.codex_agent, function()
    open_agent_terminal("codex")
  end, "Open Codex agent")
  map_all("n", keys.antigravity_agent, function()
    open_agent_terminal("antigravity")
  end, "Open Antigravity agent")
  map_all("n", keys.opencode_agent, function()
    open_agent_terminal("opencode")
  end, "Open OpenCode agent")
  map_all("n", keys.copy_explain_prompt, function()
    copy_explain_prompt(false)
  end, "Copy explain prompt")
  map_all("v", keys.copy_explain_prompt, function()
    copy_explain_prompt(true)
  end, "Copy explain prompt for selection")

  local git_review = keys.git_review
  map_all("n", git_review.file_diff, gitsigns_action("diffthis"), "Git diff current file")
  map_all("n", git_review.full_diff, git_command("DiffviewOpen"), "Git diff workspace")
  map_all("n", git_review.preview_hunk, gitsigns_action("preview_hunk"), "Git preview hunk")
  map_all("n", git_review.stage_hunk, gitsigns_action("stage_hunk"), "Git accept/stage hunk")
  map_all("v", git_review.stage_hunk, gitsigns_range_action("stage_hunk"), "Git accept/stage selection")
  map_all("n", git_review.reset_hunk, gitsigns_action("reset_hunk"), "Git reject/reset hunk")
  map_all("v", git_review.reset_hunk, gitsigns_range_action("reset_hunk"), "Git reject/reset selection")
  map_all("n", git_review.stage_file, gitsigns_action("stage_buffer"), "Git accept/stage file")
  map_all("n", git_review.reset_file, gitsigns_action("reset_buffer"), "Git reject/reset file")
  map_all("n", git_review.file_history, git_command("DiffviewFileHistory %"), "Git file history")

  vim.keymap.set("v", "y", '"+y', { desc = "Copy selection to clipboard", silent = true })
  vim.keymap.set("n", "Y", '"+y$', { desc = "Copy to end of line to clipboard", silent = true })
  vim.keymap.set({ "n", "v" }, "<leader>y", '"+y', { desc = "Copy to clipboard", silent = true })
  vim.keymap.set({ "n", "v" }, "<leader>p", '"+p', { desc = "Paste from clipboard", silent = true })
end

return M
