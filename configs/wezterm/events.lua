local wezterm = require("wezterm")
local appearance = require("appearance")

local M = {}

function M.apply(_config)
  wezterm.on("toggle-glare-safe", function(window, _pane)
    local overrides = window:get_config_overrides() or {}
    local enabled = overrides.color_scheme == appearance.glare_safe_scheme

    if enabled then
      overrides.color_scheme = nil
      overrides.colors = nil
      overrides.window_background_opacity = nil
      window:set_config_overrides(overrides)
      window:toast_notification("WezTerm", "Glare Safe off", nil, 1800)
      return
    end

    overrides.color_scheme = appearance.glare_safe_scheme
    overrides.colors = nil
    overrides.window_background_opacity = 1.0
    window:set_config_overrides(overrides)
    window:toast_notification("WezTerm", "Glare Safe on", nil, 1800)
  end)

  wezterm.on("close-notebook-plot-pane", function(window, pane)
    local user_vars = pane:get_user_vars() or {}
    if user_vars.EOS_NOTEBOOK_PLOTS == "1" then
      window:perform_action(wezterm.action.CloseCurrentPane({ confirm = false }), pane)
      return
    end

    window:toast_notification(
      "WezTerm",
      "Ctrl+Shift+W only closes the notebook plot pane",
      nil,
      1800
    )
  end)
end

return M
