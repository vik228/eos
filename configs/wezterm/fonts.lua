local wezterm = require("wezterm")

local M = {}

function M.apply(config)
  config.font = wezterm.font_with_fallback({
    "JetBrains Mono",
    "Symbols Nerd Font Mono",
    "Menlo",
    "Monaco",
  })
  config.font_size = 14
end

return M
