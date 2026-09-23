local M = {}

local panes = {}
local pane_backends = {}
local pane_width = 42

local function native_tmux_binary()
  local configured = vim.env.EOS_TMUX_BIN
  if configured and configured ~= "" and vim.fn.executable(configured) == 1 then
    return configured
  end

  local uname = vim.uv.os_uname()
  if uname.sysname == "Darwin" and uname.machine == "arm64" then
    local apple_silicon_homebrew = "/opt/homebrew/opt/tmux/bin/tmux"
    if vim.fn.executable(apple_silicon_homebrew) == 1 then
      return apple_silicon_homebrew
    end
  elseif uname.sysname == "Darwin" and uname.machine == "x86_64" then
    local intel_homebrew = "/usr/local/opt/tmux/bin/tmux"
    if vim.fn.executable(intel_homebrew) == 1 then
      return intel_homebrew
    end
  end

  return vim.fn.exepath("tmux")
end

local function tmux_command(args)
  local binary = native_tmux_binary()
  return vim.list_extend({ binary ~= "" and binary or "tmux" }, args)
end

local function wezterm_cli(args)
  return vim.list_extend({ "env", "-u", "WEZTERM_UNIX_SOCKET", "wezterm", "cli" }, args)
end

local function in_tmux()
  return vim.env.TMUX and vim.env.TMUX ~= "" and vim.env.TMUX_PANE and vim.env.TMUX_PANE ~= ""
end

local function pane_ids()
  local proc = vim.system(wezterm_cli({ "list", "--format", "json" }), { text = true }):wait(1500)
  if proc.code ~= 0 then
    return {}
  end
  local ok, listed = pcall(vim.json.decode, proc.stdout)
  if not ok then
    return {}
  end
  local ids = {}
  for _, pane in ipairs(listed) do
    ids[tonumber(pane.pane_id)] = true
  end
  return ids
end

local function activate(pane_id)
  vim.system(wezterm_cli({ "activate-pane", "--pane-id", tostring(pane_id) }), { detach = true })
end

local function forget(agent)
  panes[agent] = nil
  pane_backends[agent] = nil
end

local function close_wezterm(agent, pane_id)
  local proc = vim.system(wezterm_cli({ "kill-pane", "--pane-id", tostring(pane_id) }), { text = true }):wait(1500)
  if proc.code ~= 0 then
    vim.notify("Could not close " .. agent .. " pane: " .. vim.trim(proc.stderr or ""), vim.log.levels.ERROR)
    return false
  end
  forget(agent)
  return true
end

local function tmux_pane_ids()
  local proc = vim.system(tmux_command({ "list-panes", "-a", "-F", "#{pane_id}" }), { text = true }):wait(1500)
  local ids = {}
  if proc.code == 0 then
    for _, pane_id in ipairs(vim.split(proc.stdout or "", "\n", { trimempty = true })) do
      ids[pane_id] = true
    end
  end
  return ids
end

local function open_tmux(agent, command)
  local live = tmux_pane_ids()
  if panes[agent] and live[panes[agent]] then
    local proc = vim.system(tmux_command({ "kill-pane", "-t", panes[agent] }), { text = true }):wait(1500)
    if proc.code ~= 0 then
      vim.notify("Could not close " .. agent .. " tmux pane: " .. vim.trim(proc.stderr or ""), vim.log.levels.ERROR)
      return
    end
    forget(agent)
    return
  end
  forget(agent)
  vim.system(tmux_command({
    "split-window", "-h", "-d", "-P", "-F", "#{pane_id}",
    "-t", vim.env.TMUX_PANE, "-c", vim.fn.getcwd(),
    "zsh", "-lc", command,
  }), { text = true }, function(proc)
    vim.schedule(function()
      local pane_id = vim.trim(proc.stdout or "")
      if proc.code ~= 0 or pane_id == "" then
        vim.notify("Could not open " .. agent .. " tmux pane: " .. vim.trim(proc.stderr or ""), vim.log.levels.ERROR)
        return
      end
      panes[agent] = pane_id
      pane_backends[agent] = "tmux"
      vim.system(tmux_command({ "select-pane", "-t", pane_id }), { detach = true })
    end)
  end)
end

function M.open(agent, command)
  -- Keep an agent launched from a tmux editor scoped to that tmux window.
  if in_tmux() then
    open_tmux(agent, command)
    return
  end

  local editor_pane = tonumber(vim.env.WEZTERM_PANE or "")
  if not editor_pane then
    vim.notify("Agent panes require WezTerm or tmux", vim.log.levels.ERROR)
    return
  end

  local live = pane_ids()
  if panes[agent] and live[panes[agent]] then
    close_wezterm(agent, panes[agent])
    return
  end
  forget(agent)

  local parent = editor_pane
  local direction = "--right"
  local percent = pane_width
  local top_level = true
  for _, pane_id in pairs(panes) do
    if live[pane_id] then
      parent = pane_id
      direction = "--bottom"
      percent = 50
      top_level = false
      break
    end
  end

  local title = "AGENT: " .. string.upper(agent)
  local shell_command = "printf '\\033]2;" .. title .. "\\007'; " .. command
  local args = { "split-pane" }
  if top_level then
    table.insert(args, "--top-level")
  end
  vim.list_extend(args, {
    direction,
    "--pane-id", tostring(parent),
    "--percent", tostring(percent),
    "--cwd", vim.fn.getcwd(),
    "--", "zsh", "-lc", shell_command,
  })
  vim.system(wezterm_cli(args), { text = true }, function(proc)
    vim.schedule(function()
      if proc.code ~= 0 then
        vim.notify("Could not open " .. agent .. " pane: " .. vim.trim(proc.stderr or ""), vim.log.levels.ERROR)
        return
      end
      local pane_id = tonumber(vim.trim(proc.stdout or ""))
      if not pane_id then
        vim.notify("WezTerm did not return an agent pane id", vim.log.levels.ERROR)
        return
      end
      panes[agent] = pane_id
      pane_backends[agent] = "wezterm"
      activate(pane_id)
    end)
  end)
end

function M.close_all()
  for agent, pane_id in pairs(panes) do
    if pane_backends[agent] == "wezterm" then
      vim.system(wezterm_cli({ "kill-pane", "--pane-id", tostring(pane_id) }), { text = true }):wait(1500)
    elseif pane_backends[agent] == "tmux" then
      vim.system(tmux_command({ "kill-pane", "-t", tostring(pane_id) }), { text = true }):wait(1500)
    end
  end
  panes = {}
  pane_backends = {}
end

vim.api.nvim_create_autocmd("VimLeavePre", {
  group = vim.api.nvim_create_augroup("EosAgentPaneLifecycle", { clear = true }),
  callback = M.close_all,
  desc = "Close agent panes owned by this Neovim instance",
})

return M
