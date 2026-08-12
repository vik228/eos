local wezterm = require("wezterm")

local M = {}

M.glare_safe_scheme = "EOS Glare Safe"

M.glare_safe_colors = {
  foreground = "#1f2430",
  background = "#f4f1e8",
  cursor_bg = "#1f2430",
  cursor_border = "#1f2430",
  cursor_fg = "#f4f1e8",
  selection_bg = "#55707f",
  selection_fg = "#fbf7ef",
  scrollbar_thumb = "#b9b4a8",
  split = "#c8c1b4",
  ansi = {
    "#f4f1e8",
    "#9b2c2c",
    "#2f6f4e",
    "#8a5a00",
    "#2f5f8f",
    "#6f4c8f",
    "#2f6f73",
    "#1f2430",
  },
  brights = {
    "#d9d3c6",
    "#b23a3a",
    "#3f8f65",
    "#a86f00",
    "#3f78ad",
    "#8460a8",
    "#3f8f94",
    "#10141d",
  },
  tab_bar = {
    background = "#e4ded2",
    active_tab = {
      bg_color = "#fbf7ef",
      fg_color = "#1f2430",
      intensity = "Bold",
    },
    inactive_tab = {
      bg_color = "#d6cec0",
      fg_color = "#4e5668",
    },
    inactive_tab_hover = {
      bg_color = "#c8c1b4",
      fg_color = "#1f2430",
    },
    new_tab = {
      bg_color = "#e4ded2",
      fg_color = "#4e5668",
    },
    new_tab_hover = {
      bg_color = "#d6cec0",
      fg_color = "#1f2430",
    },
  },
}

function M.apply(config)
  config.enable_kitty_graphics = true
  config.color_schemes = config.color_schemes or {}
  config.color_schemes[M.glare_safe_scheme] = M.glare_safe_colors
  config.color_scheme = "Catppuccin Mocha"
  config.inactive_pane_hsb = { saturation = 0.3, brightness = 0.85 }
  config.window_background_opacity = 1.0
  config.window_padding = {
    left = 18,
    right = 18,
    top = 16,
    bottom = 14,
  }
  config.enable_tab_bar = true
  config.hide_tab_bar_if_only_one_tab = false
  config.use_fancy_tab_bar = false
  config.tab_max_width = 28
  config.window_decorations = "TITLE | RESIZE"
  config.adjust_window_size_when_changing_font_size = false
  config.colors = {
    split = "#45475a",
    tab_bar = {
      background = "#181825",
      active_tab = {
        bg_color = "#11111b",
        fg_color = "#cdd6f4",
        intensity = "Bold",
      },
      inactive_tab = {
        bg_color = "#313244",
        fg_color = "#a6adc8",
      },
      inactive_tab_hover = {
        bg_color = "#45475a",
        fg_color = "#cdd6f4",
      },
      new_tab = {
        bg_color = "#181825",
        fg_color = "#a6adc8",
      },
      new_tab_hover = {
        bg_color = "#313244",
        fg_color = "#cdd6f4",
      },
    },
  }
end

return M
