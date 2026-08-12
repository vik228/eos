local wezterm = require("wezterm")

local M = {}

function M.apply(config)
  config.keys = {
    { key = "P", mods = "CMD|SHIFT", action = wezterm.action.ShowLauncher },
    { key = "b", mods = "CMD", action = wezterm.action.EmitEvent("toggle-glare-safe") },
    { key = "b", mods = "CMD|SHIFT", action = wezterm.action.EmitEvent("toggle-glare-safe") },
    { key = "k", mods = "CMD", action = wezterm.action.SendKey({ key = "k", mods = "ALT" }) },
    { key = "s", mods = "CMD", action = wezterm.action.SendKey({ key = "s", mods = "ALT" }) },
    { key = "Enter", mods = "SHIFT", action = wezterm.action.SendString("\x1b[13;2u") },
    { key = "Enter", mods = "CMD|SHIFT", action = wezterm.action.SplitVertical({ domain = "CurrentPaneDomain" }) },
    { key = "d", mods = "CMD", action = wezterm.action.SplitHorizontal({ domain = "CurrentPaneDomain" }) },
    { key = "h", mods = "CTRL|SHIFT", action = wezterm.action.ActivatePaneDirection("Left") },
    { key = "j", mods = "CTRL|SHIFT", action = wezterm.action.ActivatePaneDirection("Down") },
    { key = "k", mods = "CTRL|SHIFT", action = wezterm.action.ActivatePaneDirection("Up") },
    { key = "l", mods = "CTRL|SHIFT", action = wezterm.action.ActivatePaneDirection("Right") },
    { key = "w", mods = "CTRL|SHIFT", action = wezterm.action.EmitEvent("close-notebook-plot-pane") },
  }
end

return M
