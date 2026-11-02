-- Supermaven work-profile guard (buffer level).
--
-- The extra itself is imported top-level in config/lazy.lua (LazyVim
-- requires extras imports before your own `plugins`). Instance level is
-- handled there via `enabled`. This spec only stops the binary for buffers
-- under work roots, covering work files opened from a non-work nvim.
-- Checked on every BufEnter. Python LSP stays global (local, no privacy
-- concern).

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

return {
  {
    "supermaven-inc/supermaven-nvim",
    optional = true,
    opts = function(_, opts)
      opts.condition = supermaven_off_for_buffer
    end,
  },
}
