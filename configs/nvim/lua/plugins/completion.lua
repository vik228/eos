-- Python type-ahead + AI completion.
--
-- Type-ahead: LazyVim python extra (pyright + ruff via mason) plus blink.cmp.
-- Applies to plain .py files and notebook buffers (jupytext `# %%` python).
-- Global: no privacy concern (local LSP).
--
-- AI: Supermaven, gated in two layers (privacy: Supermaven sends Code Data
-- to its cloud servers, so work files must never reach it):
--   1. Instance level: the extra loads only when EOS_PROFILE ~= "work".
--      Backend/research workspaces launch separate nvim instances, so a work
--      workspace nvim never loads the plugin at all.
--   2. Buffer level: `condition` stops the binary for buffers under work
--      roots. This covers work files opened from a non-work nvim (plain
--      `nvim` from shell, cross-opened paths). Checked on every BufEnter.

local specs = {
  { import = "lazyvim.plugins.extras.lang.python" },
  { import = "lazyvim.plugins.extras.coding.blink" },
}

local function work_path_prefixes()
  local roots = {}
  if vim.env.EOS_WORK_ROOT and vim.env.EOS_WORK_ROOT ~= "" then
    table.insert(roots, vim.env.EOS_WORK_ROOT)
  else
    table.insert(roots, vim.fn.expand("~/work"))
  end
  if vim.env.EOS_BACKEND_DIR and vim.env.EOS_BACKEND_DIR ~= "" then
    table.insert(roots, vim.env.EOS_BACKEND_DIR)
  end
  return roots
end

local function supermaven_off_for_buffer()
  local path = vim.api.nvim_buf_get_name(0)
  if path == "" then
    return false
  end
  for _, root in ipairs(work_path_prefixes()) do
    local norm = vim.fn.fnamemodify(root, ":p"):gsub("/$", "")
    if path == norm or path:sub(1, #norm + 1) == norm .. "/" then
      return true
    end
  end
  return false
end

if vim.env.EOS_PROFILE ~= "work" then
  specs[#specs + 1] = { import = "lazyvim.plugins.extras.ai.supermaven" }
  specs[#specs + 1] = {
    "supermaven-inc/supermaven-nvim",
    optional = true,
    opts = function(_, opts)
      opts.condition = supermaven_off_for_buffer
    end,
  }
end

return specs
