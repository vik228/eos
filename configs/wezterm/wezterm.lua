local wezterm = require("wezterm")
local home = os.getenv("HOME")
local eos_root = os.getenv("EOS_ROOT") or (home .. "/personal/eos")

package.path = eos_root .. "/configs/wezterm/?.lua;" .. package.path

local config = wezterm.config_builder()

require("appearance").apply(config)
require("fonts").apply(config)
require("keys").apply(config)
require("launch").apply(config)
require("status").apply(config)
require("events").apply(config)

return config
