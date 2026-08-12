local notebook_python = vim.fn.expand("~/.local/share/eos/notebooks/.venv/bin/python3")
local notebook_ipython = vim.fn.expand("~/.local/share/eos/notebooks/.venv/bin/ipython")
local notebook_jupytext = vim.fn.expand("~/.local/share/eos/notebooks/.venv/bin/jupytext")
local shift_enter_csi_u = "\27[13;2u"
local notebook_keys = {
  init_repl = { "<leader>ji" },
  run_cell = { "<leader>jr" },
  run_cell_advance = { "<S-CR>", shift_enter_csi_u },
  run_all = { "<leader>ja" },
  fallback_run_cell = { "<leader>jf" },
  interrupt_kernel = { "<leader>jI" },
  export_output = { "<leader>je" },
  import_output = { "<leader>jE" },
  next_cell = { "<leader>jn" },
  previous_cell = { "<leader>jp" },
  focus_repl = { "<leader>jo" },
  hide_repl = { "<leader>jh" },
  restart_repl = { "<leader>jd" },
  reset_session = { "<leader>jR" },
  insert_code_cell = { "<leader>jc" },
  insert_markdown_cell = { "<leader>jm" },
  clear_cell_status = { "<leader>jx" },
}

if vim.fn.executable(notebook_python) == 1 then
  vim.g.python3_host_prog = notebook_python
end

local function current_buffer_dir()
  local file = vim.api.nvim_buf_get_name(0)
  if file ~= "" then
    return vim.fn.fnamemodify(file, ":p:h")
  end
  return vim.fn.getcwd()
end

local function find_project_venv(start_dir)
  local dir = vim.fn.fnamemodify(start_dir, ":p")
  local home = vim.fn.expand("$HOME")

  while dir ~= "/" and dir ~= "" do
    local venv = dir .. "/.venv"
    if vim.fn.executable(venv .. "/bin/python") == 1 then
      return venv
    end

    if dir == home then
      break
    end

    local parent = vim.fn.fnamemodify(dir, ":h")
    if parent == dir then
      break
    end
    dir = parent
  end

  return nil
end

local function executable_works(command)
  if vim.fn.executable(command) ~= 1 then
    return false
  end

  vim.fn.system({ command, "--version" })
  return vim.v.shell_error == 0
end

local function python_repl_command()
  local project_venv = find_project_venv(current_buffer_dir())
  if project_venv then
    local ipython = project_venv .. "/bin/ipython"
    if executable_works(ipython) then
      return { ipython, "--no-autoindent" }
    end
    return { project_venv .. "/bin/python", "-i" }
  end

  if executable_works(notebook_ipython) then
    return { notebook_ipython, "--no-autoindent" }
  end
  return { notebook_python, "-i" }
end

local function project_kernel_name(project_venv)
  if not project_venv then
    return nil
  end

  local project_root = vim.fn.fnamemodify(project_venv, ":h")
  local project_name = vim.fn.fnamemodify(project_root, ":t"):lower()
  project_name = project_name:gsub("[^%w%._-]", "-")
  return "eos-" .. project_name .. "-venv"
end

local function user_kernel_json(kernel_name)
  if vim.fn.has("macunix") == 1 then
    return vim.fn.expand("~/Library/Jupyter/kernels/" .. kernel_name .. "/kernel.json")
  end
  return vim.fn.expand("~/.local/share/jupyter/kernels/" .. kernel_name .. "/kernel.json")
end

local function kernel_json_points_to(kernel_json, python_path)
  local ok, lines = pcall(vim.fn.readfile, kernel_json)
  if not ok then
    return false
  end
  return table.concat(lines, "\n"):find(python_path, 1, true) ~= nil
end

local function ensure_project_kernel(project_venv)
  local python_path = project_venv and (project_venv .. "/bin/python") or nil
  if not python_path or vim.fn.executable(python_path) ~= 1 then
    return nil
  end

  local kernel_name = project_kernel_name(project_venv)
  local kernel_json = user_kernel_json(kernel_name)
  if kernel_json_points_to(kernel_json, python_path) then
    return kernel_name
  end

  local project_root = vim.fn.fnamemodify(project_venv, ":h")
  local display_name = vim.fn.fnamemodify(project_root, ":t") .. " (.venv)"
  local result = vim.fn.system({
    python_path,
    "-m",
    "ipykernel",
    "install",
    "--user",
    "--name",
    kernel_name,
    "--display-name",
    display_name,
  })

  if vim.v.shell_error ~= 0 then
    vim.notify("Could not register project Jupyter kernel: " .. result, vim.log.levels.WARN)
    return nil
  end

  return kernel_name
end

local function notebook_kernel_name()
  local project_venv = find_project_venv(current_buffer_dir())
  if project_venv then
    local kernel_name = ensure_project_kernel(project_venv)
    if kernel_name then
      return kernel_name
    end
  end

  return "python3"
end

local function eos_image_backend()
  local override = vim.env.EOS_NVIM_IMAGE_BACKEND
  if override and override ~= "" then
    return override
  end

  if vim.env.KITTY_WINDOW_ID and vim.env.KITTY_WINDOW_ID ~= "" then
    return "kitty"
  end

  if vim.env.WEZTERM_PANE and vim.env.WEZTERM_PANE ~= "" then
    return "sixel"
  end

  return "kitty"
end

local function eos_molten_image_provider()
  if vim.env.WEZTERM_PANE and vim.env.WEZTERM_PANE ~= "" and not (vim.env.TMUX and vim.env.TMUX ~= "") then
    return "wezterm"
  end

  return "image.nvim"
end

local function apply_plugin_source_patches(path, replacements)
  local source = table.concat(vim.fn.readfile(path), "\n")
  local changed = false

  for _, item in ipairs(replacements) do
    local applied_marker = item.applied_marker or item.replacement
    if not source:find(applied_marker, 1, true) then
      local start_index, end_index = source:find(item.original, 1, true)
      if not start_index then
        if item.optional then
          goto continue
        end
        error("Unsupported plugin version: could not apply " .. item.name .. " patch")
      end
      source = source:sub(1, start_index - 1) .. item.replacement .. source:sub(end_index + 1)
      changed = true
    end
    ::continue::
  end

  if changed then
    vim.fn.writefile(vim.split(source, "\n", { plain = true, trimempty = false }), path)
  end
end

local function patch_image_nvim_sixel_backend(plugin)
  local backend_path = plugin.dir .. "/lua/image/backends/sixel.lua"
  apply_plugin_source_patches(backend_path, {
    {
      name = "SIXEL settled-frame delay",
      original = "local FLUSH_DELAY_MS = 50",
      replacement = "local FLUSH_DELAY_MS = 120",
    },
    {
      name = "native tmux SIXEL transport",
      original = [[  -- tmux passthrough: wrap DCS sequence so tmux forwards it to the terminal
  if utils.tmux.is_tmux then
    wrapped_data = utils.tmux.escape(wrapped_data)
  end

]],
      replacement = [[  -- EOS uses tmux's native SIXEL transport.

]],
      applied_marker = "-- EOS uses tmux's native SIXEL transport.",
    },
    {
      name = "SIXEL stdout handle",
      original = [[local utils = require("image/utils")
]],
      replacement = [[local utils = require("image/utils")
local stdout = vim.uv.new_tty(1, false)
]],
      applied_marker = "local stdout = vim.uv.new_tty(1, false)",
    },
    {
      name = "SIXEL stdout rendering",
      original = [[  -- send via stderr
  vim.fn.chansend(vim.v.stderr, sequence)
  vim.fn.chansend(vim.v.stderr, "")
]],
      replacement = [[  stdout:write(sequence)
]],
      applied_marker = "stdout:write(sequence)",
    },
  })
end

local function patch_jupytext_notebook_lifecycle(plugin)
  local source_path = plugin.dir .. "/lua/jupytext.lua"
  apply_plugin_source_patches(source_path, {
    {
      name = "skip Jupytext autosync for malformed notebook sources",
      original = [[  if source_file and autosync then
    M.sync(source_file)
  end
]],
      replacement = [[  if source_file and autosync then
    local source_content = M.read_file(ipynb_file)
    if source_content:match('^%s*{') then
      M.sync(source_file)
    end
  end
]],
      applied_marker = "if source_content:match('^%s*{') then",
    },
    {
      name = "empty and percent-script notebook recovery",
      original = [[  local metadata = M.get_metadata(json_lines)
  local format = M.get_option('format')
]],
      replacement = [[  local raw_content = table.concat(json_lines, '\n')
  if source_file and raw_content:match('^%s*$') then
    json_lines = M.read_file(M.get_option('new_template'), true)
    raw_content = table.concat(json_lines, '\n')
  end

  local source_is_percent = source_file
    and raw_content:match('^%s*# %-%-%-')
    and raw_content:find('\n# %%%%')
  local metadata
  if source_is_percent then
    local yaml_data = M.parse_yaml(M.get_yaml_lines(json_lines))
    metadata = yaml_data.jupyter or {}
  else
    metadata = M.get_metadata(json_lines)
  end
  local format = M.get_option('format')
]],
      applied_marker = "source_is_percent",
    },
    {
      name = "open percent-script notebook without JSON conversion",
      original = [[  if format == 'ipynb' then
    vim.api.nvim_buf_set_lines(bufnr, -2, -1, false, json_lines)
  else
]],
      replacement = [[  if source_is_percent or format == 'ipynb' then
    vim.api.nvim_buf_set_lines(bufnr, -2, -1, false, json_lines)
  else
]],
      applied_marker = "if source_is_percent or format == 'ipynb' then",
    },
    {
      name = "skip Jupytext update for malformed notebook destinations",
      original = [[  local update = M.get_option('update')
  local via_tempfile = update
]],
      replacement = [[  local configured_update = M.get_option('update')
  local destination_is_json = false
  if stat and stat.type == 'file' then
    local destination_lines = M.read_file(ipynb_file, true)
    local destination_content = table.concat(destination_lines, '\n')
    destination_is_json = destination_content:match('^%s*{') ~= nil
  end
  local update = configured_update and destination_is_json
  local via_tempfile = configured_update
]],
      applied_marker = "local destination_is_json = false",
    },
    {
      name = "read notebook destination as lines",
      original = "local destination_lines = M.read_file(ipynb_file)",
      replacement = "local destination_lines = M.read_file(ipynb_file, true)",
      applied_marker = "local destination_lines = M.read_file(ipynb_file, true)",
    },
  })
end

local function patch_molten_virtual_output_layout(plugin)
  local output_path = plugin.dir .. "/rplugin/python3/molten/outputbuffer.py"
  apply_plugin_source_patches(output_path, {
    {
      name = "virtual image offset",
      original = [[                y = lineno
                if virtual:
                    y = shape[1]
]],
      replacement = [[                y = lineno
                if virtual:
                    y = shape[1] + lineno + virtual_lines
]],
    },
    {
      name = "explicit output label",
      original = [[        if output.status == OutputStatus.NEW:
            return f"Out[_]: Never Run"
        else:
            return f"{old}Out[{execution_count}]: {status} {time}".rstrip()
]],
      replacement = [[        if output.status == OutputStatus.NEW:
            return "Output | Not Run"
        else:
            return f"{old}Output | Run {execution_count} | {status} {time}".rstrip()
]],
    },
    {
      name = "output block styling",
      original = [[                "virt_lines": [[(line, self.options.hl.virtual_text)] for line in lines],
]],
      replacement = [[                "virt_lines": [
                    [
                        (
                            line.ljust(max(1, shape[2])),
                            "MoltenOutputHeader" if index == 0 else self.options.hl.virtual_text,
                        )
                    ]
                    for index, line in enumerate(lines)
                ]
                + [
                    [(" " * max(1, shape[2]), "MoltenOutputFooter")]
                ],
]],
    },
    {
      name = "live output scroll preservation",
      applied_marker = "previous_cursor = None",
      original = [[    def show_floating_win(self, anchor: Position) -> None:
        win = self.nvim.current.window
]],
      replacement = [[    def show_floating_win(self, anchor: Position) -> None:
        previous_cursor = None
        if self.display_win is not None and self.display_win.valid:
            previous_cursor = self.display_win.api.get_cursor()

        win = self.nvim.current.window
]],
    },
    {
      name = "strict pynvim output window handle",
      original = [[                self.nvim.funcs.nvim_set_current_win(self.display_win)
        elif self.options.enter_output_behavior != "no_open":
            entered = True
            self.nvim.funcs.nvim_set_current_win(self.display_win)
]],
      replacement = [[                self.nvim.funcs.nvim_set_current_win(self.display_win.handle)
        elif self.options.enter_output_behavior != "no_open":
            entered = True
            self.nvim.funcs.nvim_set_current_win(self.display_win.handle)
]],
    },
    {
      name = "focused live output refresh",
      applied_marker = "self.nvim.current.buffer.number == self.display_buf.number",
      original = [[        if self.display_win is not None and self.display_win.valid:
            previous_cursor = self.display_win.api.get_cursor()

        win = self.nvim.current.window
]],
      replacement = [[        if self.display_win is not None and self.display_win.valid:
            previous_cursor = self.display_win.api.get_cursor()

        if self.nvim.current.buffer.number == self.display_buf.number:
            shape = (0, 0, max(1, self.display_win.width), max(1, self.display_win.height))
            lines, _ = self.build_output_text(shape, self.display_buf.number, False)
            self.display_buf.api.set_lines(0, -1, False, lines)
            if previous_cursor is not None:
                row = min(previous_cursor[0], len(self.display_buf))
                self.display_win.api.set_cursor((max(1, row), previous_cursor[1]))
            return

        win = self.nvim.current.window
]],
    },
    {
      name = "live output cursor restoration",
      original = [[        if self.options.floating_window_focus == "top":
            self.display_win.api.set_cursor((1, 0))

        elif self.options.floating_window_focus == "bottom":
            self.display_win.api.set_cursor((len(self.display_buf), 0))
]],
      replacement = [[        if previous_cursor is not None:
            row = min(previous_cursor[0], len(self.display_buf))
            self.display_win.api.set_cursor((max(1, row), previous_cursor[1]))
        elif self.options.floating_window_focus == "top":
            self.display_win.api.set_cursor((1, 0))
        elif self.options.floating_window_focus == "bottom":
            self.display_win.api.set_cursor((len(self.display_buf), 0))
]],
    },
  })

  local chunks_path = plugin.dir .. "/rplugin/python3/molten/outputchunks.py"
  apply_plugin_source_patches(chunks_path, {
    {
      name = "virtual image cell anchor",
      original = [[        self.img_identifier = canvas.add_image(
            self.img_path,
            f"{'virt-' if virtual else ''}{self.img_path}",
            0,
            lineno,
            bufnr,
            winnr,
        )
]],
      replacement = [[        image_y = lineno
        render_offset_top = 0
        if virtual and options.image_provider == "image.nvim":
            image_y = _shape[1]
            render_offset_top = max(0, lineno - image_y)

        image_args = (
            self.img_path,
            f"{'virt-' if virtual else ''}{self.img_path}",
            0,
            image_y,
            bufnr,
            winnr,
        )
        if virtual and options.image_provider == "image.nvim":
            self.img_identifier = canvas.add_image(
                *image_args,
                render_offset_top=render_offset_top,
            )
        else:
            self.img_identifier = canvas.add_image(*image_args)
]],
    },
  })

  local images_path = plugin.dir .. "/rplugin/python3/molten/images.py"
  apply_plugin_source_patches(images_path, {
    {
      name = "image.nvim render offset",
      original = [[        bufnr: int,
        winnr: int | None = None,
    ) -> str:
        img = self.image_api.from_file(
]],
      replacement = [[        bufnr: int,
        winnr: int | None = None,
        render_offset_top: int = 0,
    ) -> str:
        img = self.image_api.from_file(
]],
    },
    {
      name = "image.nvim render offset option",
      original = [[                "y": y,
                "window": winnr,
]],
      replacement = [[                "y": y,
                "window": winnr,
                "render_offset_top": render_offset_top,
]],
    },
    {
      name = "lazy WezTerm image pane",
      original = [[        for identifier in to_work_on:
            self.wezterm_api.send_image(
                identifier,
                str(self.image_pane).strip(),
                str(self.initial_pane_id).strip(),
            )
]],
      replacement = [[        for identifier in to_work_on:
            self.image_pane = self.wezterm_api.send_image(
                identifier,
                self.image_pane,
                self.initial_pane_id,
                self.split_dir,
                self.split_size,
            )
]],
    },
    {
      name = "safe absent WezTerm image pane cleanup",
      original = [[        self.wezterm_api.close_image_pane(str(self.image_pane).strip())
]],
      replacement = [[        if self.image_pane is not None:
            self.wezterm_api.close_image_pane(self.image_pane)
]],
    },
  })

  local molten_buffer_path = plugin.dir .. "/rplugin/python3/molten/moltenbuffer.py"
  apply_plugin_source_patches(molten_buffer_path, {
    {
      name = "focused output buffer updates",
      original = [[        buffer_numbers = [buf.number for buf in self.buffers]
        if self.nvim.current.buffer.number not in buffer_numbers:
            return

        if self.nvim.current.window.buffer.number not in buffer_numbers:
            return
]],
      replacement = [[        buffer_numbers = [buf.number for buf in self.buffers]
        if self.nvim.current.buffer.number not in buffer_numbers:
            for span, output in self.outputs.items():
                if self.nvim.current.buffer.number == output.display_buf.number:
                    output.show_floating_win(span.end)
                    self.canvas.present()
                    return
            return

        if self.nvim.current.window.buffer.number not in buffer_numbers:
            return
]],
    },
  })

  local molten_init_path = plugin.dir .. "/rplugin/python3/molten/__init__.py"
  apply_plugin_source_patches(molten_init_path, {
    {
      name = "output buffer kernel ownership",
      original = [[        maybe_molten = self.buffers.get(self.nvim.current.buffer.number)
        if requires_instance and (maybe_molten is None or len(maybe_molten) == 0):
]],
      replacement = [[        current_bufno = self.nvim.current.buffer.number
        maybe_molten = self.buffers.get(current_bufno)
        if maybe_molten is None:
            for kernels in self.buffers.values():
                if any(
                    output.display_buf.number == current_bufno
                    for kernel in kernels
                    for output in kernel.outputs.values()
                ):
                    maybe_molten = kernels
                    break

        if requires_instance and (maybe_molten is None or len(maybe_molten) == 0):
]],
    },
    {
      name = "defer WezTerm pane until first image",
      original = [[            if isinstance(self.canvas, WeztermCanvas):
                self.canvas.wezterm_split()

]],
      replacement = [[            # EOS opens the WezTerm plot pane lazily when an image is emitted.

]],
      applied_marker = "# EOS opens the WezTerm plot pane lazily when an image is emitted.",
    },
  })

  local wezterm_loader_path = plugin.dir .. "/lua/load_wezterm_nvim.lua"
  apply_plugin_source_patches(wezterm_loader_path, {
    {
      name = "tagged lazy WezTerm plot pane",
      original = [[  wezterm.exec_sync({ "cli", "split-pane", direction, "--percent", tostring(size) })
  wezterm.exec_sync({ "cli", "activate-pane", "--pane-id", tostring(initial_pane_id) })
  local _, image_pane_id = wezterm.exec_sync({ "cli", "get-pane-direction", "Prev" })
  return tonumber(image_pane_id, 10)
]],
      replacement = [[  local marker = "printf '\\033]1337;SetUserVar=EOS_NOTEBOOK_PLOTS=MQ==\\007' && exec zsh"
  local ok, image_pane_id = wezterm.exec_sync({
    "cli", "split-pane", direction, "--percent", tostring(size), "--",
    "zsh", "-lc", marker,
  })
  if not ok then
    return nil
  end
  wezterm.exec_sync({ "cli", "activate-pane", "--pane-id", tostring(initial_pane_id) })
  return tonumber(image_pane_id, 10)
]],
      applied_marker = "EOS_NOTEBOOK_PLOTS=MQ==",
    },
    {
      name = "upgrade WezTerm pane liveness check",
      original = [[  if image_pane_id ~= nil then
    pane_ok = wezterm.exec_sync({ "cli", "get-text", "--pane-id", tostring(image_pane_id) })
  end
]],
      replacement = [[  if image_pane_id ~= nil then
    for _, pane in ipairs(wezterm.list_panes() or {}) do
      if pane.pane_id == tonumber(image_pane_id) then
        pane_ok = true
        break
      end
    end
  end
]],
      applied_marker = "wezterm.list_panes()",
      optional = true,
    },
    {
      name = "recreate closed WezTerm plot pane",
      original = [[wezterm_api.send_image = function(path, image_pane_id, initial_pane_id)
  local placeholder = "wezterm imgcat --tmux-passthru detect %s \r"
  local image = string.format(placeholder, path)
  wezterm.exec_sync({ "cli", "activate-pane", "--pane-id", tostring(image_pane_id) })
  wezterm.exec_sync({
    "cli",
    "send-text",
    "--pane-id",
    tostring(image_pane_id),
    "--no-paste",
    image,
  })
  wezterm.exec_sync({ "cli", "activate-pane", "--pane-id", tostring(initial_pane_id) })
end
]],
      replacement = [[wezterm_api.send_image = function(path, image_pane_id, initial_pane_id, direction, size)
  local pane_ok = false
  if image_pane_id ~= nil then
    for _, pane in ipairs(wezterm.list_panes() or {}) do
      if pane.pane_id == tonumber(image_pane_id) then
        pane_ok = true
        break
      end
    end
  end
  if not pane_ok then
    image_pane_id = wezterm_api.wezterm_molten_init(initial_pane_id, direction, size)
  end
  if image_pane_id == nil then
    return nil
  end

  local placeholder = "wezterm imgcat --tmux-passthru detect %s \r"
  local image = string.format(placeholder, vim.fn.shellescape(path))
  wezterm.exec_sync({ "cli", "activate-pane", "--pane-id", tostring(image_pane_id) })
  wezterm.exec_sync({
    "cli",
    "send-text",
    "--pane-id",
    tostring(image_pane_id),
    "--no-paste",
    image,
  })
  wezterm.exec_sync({ "cli", "activate-pane", "--pane-id", tostring(initial_pane_id) })
  return image_pane_id
end
]],
      applied_marker = "wezterm.list_panes()",
    },
  })
end

local function initialize_python_repl()
  local ok, iron = pcall(require, "iron.core")
  if not ok then
    vim.notify("iron.nvim is not available", vim.log.levels.WARN)
    return false
  end

  iron.repl_for("python")
  vim.schedule(function()
    for _, win in ipairs(vim.api.nvim_list_wins()) do
      local buf = vim.api.nvim_win_get_buf(win)
      if vim.bo[buf].buftype == "terminal" then
        local name = vim.api.nvim_buf_get_name(buf):lower()
        if name:find("python") or name:find("ipython") then
          vim.api.nvim_set_option_value("winbar", "%#EosNotebookReplWinBar# PYTHON REPL %*", { win = win })
          vim.api.nvim_set_option_value("winhighlight", "WinSeparator:EosStrongSplit", { win = win })
        end
      end
    end
  end)
  return true
end

local notebook_ns = vim.api.nvim_create_namespace("eos_notebook_cells")

local function is_cell_marker(text)
  return text:match("^# %%%%") ~= nil
end

local function cell_kind(text)
  if text:match("%[markdown%]") then
    return "Markdown", "EosNotebookMarkdownCell"
  end
  return "Code", "EosNotebookCodeCell"
end

local function has_cell_markers(bufnr)
  local max_line = math.min(vim.api.nvim_buf_line_count(bufnr), 500)
  local lines = vim.api.nvim_buf_get_lines(bufnr, 0, max_line, false)
  for _, line in ipairs(lines) do
    if is_cell_marker(line) then
      return true
    end
  end
  return false
end

local render_cell_markers

local function window_for_buffer(bufnr)
  for _, win in ipairs(vim.api.nvim_list_wins()) do
    if vim.api.nvim_win_get_buf(win) == bufnr then
      return win
    end
  end
  return nil
end

local function current_cell_marker_line(bufnr)
  bufnr = bufnr or vim.api.nvim_get_current_buf()
  local win = window_for_buffer(bufnr)
  local cursor = win and vim.api.nvim_win_get_cursor(win)[1] or vim.api.nvim_win_get_cursor(0)[1]

  for line = cursor, 1, -1 do
    local text = vim.api.nvim_buf_get_lines(bufnr, line - 1, line, false)[1] or ""
    if is_cell_marker(text) then
      return line
    end
  end

  return nil
end

local function notebook_status(bufnr)
  bufnr = bufnr or vim.api.nvim_get_current_buf()
  vim.b[bufnr].eos_notebook_cell_status = vim.b[bufnr].eos_notebook_cell_status or {}
  return vim.b[bufnr].eos_notebook_cell_status
end

local function mark_cell_sent(bufnr, marker_line)
  bufnr = bufnr or vim.api.nvim_get_current_buf()
  marker_line = marker_line or current_cell_marker_line(bufnr)
  if not marker_line then
    return
  end

  local status = notebook_status(bufnr)
  status[tostring(marker_line)] = {
    status = "Sent",
    time = os.date("%H:%M:%S"),
  }
  vim.b[bufnr].eos_notebook_cell_status = status
  render_cell_markers(bufnr)
end

local function mark_cell_inline(bufnr, marker_line)
  bufnr = bufnr or vim.api.nvim_get_current_buf()
  marker_line = marker_line or current_cell_marker_line(bufnr)
  if not marker_line then
    return
  end

  local status = notebook_status(bufnr)
  status[tostring(marker_line)] = {
    status = "Inline",
    time = os.date("%H:%M:%S"),
  }
  vim.b[bufnr].eos_notebook_cell_status = status
  render_cell_markers(bufnr)
end

render_cell_markers = function(bufnr)
  bufnr = bufnr or vim.api.nvim_get_current_buf()
  if bufnr == 0 then
    bufnr = vim.api.nvim_get_current_buf()
  end
  if not vim.api.nvim_buf_is_valid(bufnr) then
    return
  end

  vim.api.nvim_buf_clear_namespace(bufnr, notebook_ns, 0, -1)

  local lines = vim.api.nvim_buf_get_lines(bufnr, 0, -1, false)
  local cell_number = 0
  local status = notebook_status(bufnr)
  local active_marker = current_cell_marker_line(bufnr)

  for index, text in ipairs(lines) do
    if is_cell_marker(text) then
      cell_number = cell_number + 1
      local label, hl_group = cell_kind(text)
      local line_number = index
      local cell_status = status[tostring(line_number)]
      local status_text = cell_status and (cell_status.status .. " " .. cell_status.time) or "Idle"
      local is_active = active_marker == line_number
      local header_hl = is_active and "EosNotebookActiveCellHeader" or "EosNotebookCellHeader"
      local sign_text = cell_status and "✔✔" or (is_active and ">>" or "  ")
      local sign_hl = cell_status and "EosNotebookExecutedCell" or "EosNotebookRunCell"
      local header_prefix = string.format("  Cell %d  ", cell_number)
      local header_separator = "  "
      local header = header_prefix .. label .. header_separator .. status_text
      local status_hl = cell_status and "EosNotebookExecutedCell" or header_hl
      local padding = math.max(0, vim.fn.strdisplaywidth(text) - vim.fn.strdisplaywidth(header))
      vim.api.nvim_buf_set_extmark(bufnr, notebook_ns, index - 1, 0, {
        line_hl_group = is_active and "EosNotebookActiveCellLine" or nil,
        sign_text = sign_text,
        sign_hl_group = sign_hl,
        virt_text = {
          { header_prefix, header_hl },
          { label, hl_group },
          { header_separator, header_hl },
          { status_text, status_hl },
          { string.rep(" ", padding), header_hl },
        },
        virt_text_pos = "overlay",
      })
    end
  end
end

local function current_cell_range()
  local bufnr = 0
  local cursor = vim.api.nvim_win_get_cursor(0)[1]
  local line_count = vim.api.nvim_buf_line_count(bufnr)
  local start_line = 1
  local end_line = line_count

  for line = cursor, 1, -1 do
    local text = vim.api.nvim_buf_get_lines(bufnr, line - 1, line, false)[1] or ""
    if is_cell_marker(text) then
      start_line = line + 1
      break
    end
  end

  for line = cursor + 1, line_count do
    local text = vim.api.nvim_buf_get_lines(bufnr, line - 1, line, false)[1] or ""
    if is_cell_marker(text) then
      end_line = line - 1
      break
    end
  end

  return start_line, math.max(start_line, end_line)
end

local function send_lines_to_repl(lines)
  if not initialize_python_repl() then
    return
  end

  local ok, iron = pcall(require, "iron.core")
  if not ok then
    vim.notify("iron.nvim is not available", vim.log.levels.WARN)
    return
  end

  iron.send("python", lines)
end

local function all_cell_marker_lines(bufnr)
  bufnr = bufnr or vim.api.nvim_get_current_buf()
  local markers = {}
  local lines = vim.api.nvim_buf_get_lines(bufnr, 0, -1, false)
  for index, text in ipairs(lines) do
    if is_cell_marker(text) then
      table.insert(markers, index)
    end
  end
  return markers
end

local function cell_range_from_marker(bufnr, marker_line)
  bufnr = bufnr or vim.api.nvim_get_current_buf()
  local line_count = vim.api.nvim_buf_line_count(bufnr)
  local start_line = marker_line + 1
  local end_line = line_count

  for line = marker_line + 1, line_count do
    local text = vim.api.nvim_buf_get_lines(bufnr, line - 1, line, false)[1] or ""
    if is_cell_marker(text) then
      end_line = line - 1
      break
    end
  end

  return start_line, math.max(start_line, end_line)
end

local function go_to_next_cell()
  local cursor = vim.api.nvim_win_get_cursor(0)[1]
  local line_count = vim.api.nvim_buf_line_count(0)

  for line = cursor + 1, line_count do
    local text = vim.api.nvim_buf_get_lines(0, line - 1, line, false)[1] or ""
    if is_cell_marker(text) then
      vim.api.nvim_win_set_cursor(0, { math.min(line + 1, line_count), 0 })
      return true
    end
  end
  return false
end

local function advance_or_create_cell()
  if go_to_next_cell() then
    return
  end
  insert_code_cell()
end

local function go_to_previous_cell()
  local cursor = vim.api.nvim_win_get_cursor(0)[1]

  for line = cursor - 1, 1, -1 do
    local text = vim.api.nvim_buf_get_lines(0, line - 1, line, false)[1] or ""
    if is_cell_marker(text) then
      vim.api.nvim_win_set_cursor(0, { math.min(line + 1, vim.api.nvim_buf_line_count(0)), 0 })
      return
    end
  end
end

local function run_current_cell(opts)
  opts = opts or {}
  local bufnr = vim.api.nvim_get_current_buf()
  local win = vim.api.nvim_get_current_win()
  local marker_line = current_cell_marker_line(bufnr)
  local start_line, end_line = current_cell_range()
  local lines = vim.api.nvim_buf_get_lines(bufnr, start_line - 1, end_line, false)
  send_lines_to_repl(lines)
  mark_cell_sent(bufnr, marker_line)
  if opts.advance then
    if vim.api.nvim_win_is_valid(win) then
      vim.api.nvim_set_current_win(win)
    end
    advance_or_create_cell()
  end
end

local function run_all_cells()
  local bufnr = vim.api.nvim_get_current_buf()
  local lines = vim.api.nvim_buf_get_lines(bufnr, 0, -1, false)
  send_lines_to_repl(lines)
  local status = notebook_status(bufnr)
  local time = os.date("%H:%M:%S")
  for _, marker_line in ipairs(all_cell_marker_lines(bufnr)) do
    status[tostring(marker_line)] = {
      status = "Sent",
      time = time,
    }
  end
  vim.b[bufnr].eos_notebook_cell_status = status
  render_cell_markers(bufnr)
end

local function run_visual_selection()
  local bufnr = vim.api.nvim_get_current_buf()
  local marker_line = current_cell_marker_line(bufnr)
  local start_line = vim.fn.line("'<")
  local end_line = vim.fn.line("'>")
  if start_line > end_line then
    start_line, end_line = end_line, start_line
  end

  local lines = vim.api.nvim_buf_get_lines(bufnr, start_line - 1, end_line, false)
  send_lines_to_repl(lines)
  mark_cell_sent(bufnr, marker_line)
end

local function molten_command_available(command)
  return vim.fn.exists(":" .. command) == 2
end

local pending_molten_evaluations = {}

local function evaluate_molten_range(bufnr, start_line, end_line)
  return vim.api.nvim_buf_call(bufnr, function()
    return pcall(vim.fn.MoltenEvaluateRange, start_line, end_line)
  end)
end

local function flush_pending_molten_evaluations(bufnr)
  local pending = pending_molten_evaluations[bufnr]
  pending_molten_evaluations[bufnr] = nil
  if not pending or not vim.api.nvim_buf_is_valid(bufnr) then
    return
  end

  vim.b[bufnr].eos_molten_ready = true
  for _, range in ipairs(pending) do
    local ok, err = evaluate_molten_range(bufnr, range.start_line, range.end_line)
    if not ok then
      vim.notify("Molten inline execution failed: " .. tostring(err), vim.log.levels.WARN)
    end
  end
end

local function molten_init_kernel()
  if not molten_command_available("MoltenInit") then
    vim.notify("molten.nvim is not available. Run :Lazy sync after installing EOS updates.", vim.log.levels.WARN)
    return false
  end

  if vim.b.eos_molten_initialized then
    return true
  end

  local kernel_name = notebook_kernel_name()
  vim.b.eos_molten_ready = false
  local ok = pcall(vim.cmd, "MoltenInit " .. kernel_name)
  if not ok then
    ok = pcall(vim.cmd, "MoltenInit")
  end

  if ok then
    vim.b.eos_molten_initialized = true
    return true
  end

  vim.b.eos_molten_ready = nil
  vim.notify("Could not initialize a Jupyter kernel for Molten.", vim.log.levels.WARN)
  return false
end

local function evaluate_range_inline(start_line, end_line)
  if start_line > end_line then
    return false
  end

  local bufnr = vim.api.nvim_get_current_buf()
  if not vim.b[bufnr].eos_molten_initialized then
    pending_molten_evaluations[bufnr] = pending_molten_evaluations[bufnr] or {}
    table.insert(pending_molten_evaluations[bufnr], { start_line = start_line, end_line = end_line })

    -- Register work before MoltenInit. A warm kernel can emit
    -- MoltenKernelReady before the command returns.
    if molten_init_kernel() then
      return true
    end

    pending_molten_evaluations[bufnr] = nil
    return false
  end

  if not molten_init_kernel() then
    return false
  end

  if vim.b[bufnr].eos_molten_ready == false then
    pending_molten_evaluations[bufnr] = pending_molten_evaluations[bufnr] or {}
    table.insert(pending_molten_evaluations[bufnr], { start_line = start_line, end_line = end_line })
    return true
  end

  local ok, err = evaluate_molten_range(bufnr, start_line, end_line)
  if not ok then
    vim.notify("Molten inline execution failed: " .. tostring(err), vim.log.levels.WARN)
    return false
  end

  return true
end

local function run_cell_inline(opts)
  opts = opts or {}
  local bufnr = vim.api.nvim_get_current_buf()
  local win = vim.api.nvim_get_current_win()
  local marker_line = current_cell_marker_line(bufnr)
  if not marker_line then
    vim.notify("No # %% notebook cell found above the cursor.", vim.log.levels.WARN)
    return
  end

  local start_line, end_line = cell_range_from_marker(bufnr, marker_line)
  if evaluate_range_inline(start_line, end_line) then
    mark_cell_inline(bufnr, marker_line)
  end

  if opts.advance then
    if vim.api.nvim_win_is_valid(win) then
      vim.api.nvim_set_current_win(win)
    end
    advance_or_create_cell()
  end
end

local function run_all_inline()
  local bufnr = vim.api.nvim_get_current_buf()
  for _, marker_line in ipairs(all_cell_marker_lines(bufnr)) do
    local start_line, end_line = cell_range_from_marker(bufnr, marker_line)
    if evaluate_range_inline(start_line, end_line) then
      mark_cell_inline(bufnr, marker_line)
    end
  end
end

local function run_visual_selection_inline()
  local bufnr = vim.api.nvim_get_current_buf()
  local marker_line = current_cell_marker_line(bufnr)
  local start_line = vim.fn.line("'<")
  local end_line = vim.fn.line("'>")
  if start_line > end_line then
    start_line, end_line = end_line, start_line
  end

  if evaluate_range_inline(start_line, end_line) then
    mark_cell_inline(bufnr, marker_line)
  end
end

local function molten_show_output()
  local ok, err = pcall(vim.cmd, "noautocmd MoltenEnterOutput")
  if not ok then
    vim.notify("Could not open full notebook output: " .. tostring(err), vim.log.levels.WARN)
  end
end

local function molten_interrupt_kernel()
  local bufnr = vim.api.nvim_get_current_buf()
  pending_molten_evaluations[bufnr] = nil

  if not molten_command_available("MoltenInterrupt") then
    vim.notify("MoltenInterrupt command not available. Is the kernel initialized?", vim.log.levels.WARN)
    return
  end

  local ok, err = pcall(vim.cmd, "MoltenInterrupt")
  if ok then
    vim.notify("Kernel interrupt signal sent.", vim.log.levels.INFO)
  else
    vim.notify("Interrupt failed: " .. tostring(err), vim.log.levels.ERROR)
  end
end

local function molten_export_output()
  pcall(vim.cmd, "MoltenExportOutput! %")
end

local function molten_import_output()
  pcall(vim.cmd, "MoltenImportOutput %")
end

local function focus_python_repl()
  local ok, iron = pcall(require, "iron.core")
  if ok then
    iron.focus_on("python")
  end
end

local function hide_python_repl()
  pcall(vim.cmd, "IronHide python")
end

local clear_cell_status

local function restart_python_repl()
  pcall(vim.cmd, "IronRestart")
end

local function reset_python_session()
  local bufnr = vim.api.nvim_get_current_buf()
  pending_molten_evaluations[bufnr] = nil
  vim.b[bufnr].eos_molten_ready = false
  local ok = pcall(vim.cmd, "MoltenRestart!")
  if not ok then
    vim.b[bufnr].eos_molten_ready = nil
    vim.b[bufnr].eos_molten_initialized = nil
  end
  restart_python_repl()
  clear_cell_status()
end

local function insert_cell(marker)
  local line = vim.api.nvim_win_get_cursor(0)[1]
  vim.api.nvim_buf_set_lines(0, line, line, false, { "", marker, "" })
  vim.api.nvim_win_set_cursor(0, { line + 3, 0 })
  render_cell_markers(0)
  vim.cmd("startinsert")
end

local function insert_code_cell()
  insert_cell("# %%")
end

local function insert_markdown_cell()
  insert_cell("# %% [markdown]")
end

clear_cell_status = function()
  pending_molten_evaluations[vim.api.nvim_get_current_buf()] = nil
  pcall(vim.cmd, "MoltenDelete!")
  vim.b[vim.api.nvim_get_current_buf()].eos_notebook_cell_status = {}
  render_cell_markers(0)
end

local function map_notebook_key(modes, keys, rhs, desc)
  for _, key in ipairs(keys) do
    vim.keymap.set(modes, key, rhs, { buffer = true, silent = true, desc = desc })
  end
end

local function notebook_buffer_keymaps()
  map_notebook_key("n", notebook_keys.init_repl, molten_init_kernel, "Notebook init inline kernel")
  map_notebook_key("n", notebook_keys.run_cell, run_cell_inline, "Notebook run cell inline")
  map_notebook_key("n", notebook_keys.run_cell_advance, function()
    run_cell_inline({ advance = true })
  end, "Notebook run cell inline and advance")
  map_notebook_key("i", notebook_keys.run_cell_advance, function()
    vim.cmd("stopinsert")
    run_cell_inline({ advance = true })
  end, "Notebook run cell inline and advance")
  map_notebook_key("v", notebook_keys.run_cell, run_visual_selection_inline, "Notebook run selection inline")
  map_notebook_key("n", notebook_keys.run_all, run_all_inline, "Notebook run all inline")
  map_notebook_key("n", notebook_keys.fallback_run_cell, run_current_cell, "Notebook fallback run cell in REPL")
  map_notebook_key("v", notebook_keys.fallback_run_cell, run_visual_selection, "Notebook fallback run selection in REPL")
  map_notebook_key("n", notebook_keys.interrupt_kernel, molten_interrupt_kernel, "Notebook interrupt inline kernel")
  map_notebook_key("n", notebook_keys.export_output, molten_export_output, "Notebook export inline output")
  map_notebook_key("n", notebook_keys.import_output, molten_import_output, "Notebook import inline output")
  map_notebook_key("n", notebook_keys.next_cell, go_to_next_cell, "Notebook next cell")
  map_notebook_key("n", notebook_keys.previous_cell, go_to_previous_cell, "Notebook previous cell")
  map_notebook_key("n", notebook_keys.focus_repl, molten_show_output, "Notebook show inline output")
  map_notebook_key("n", notebook_keys.hide_repl, hide_python_repl, "Notebook hide REPL")
  map_notebook_key("n", notebook_keys.restart_repl, restart_python_repl, "Notebook restart REPL")
  map_notebook_key("n", notebook_keys.reset_session, reset_python_session, "Notebook reset Python session")
  map_notebook_key("n", notebook_keys.insert_code_cell, insert_code_cell, "Notebook insert code cell")
  map_notebook_key("n", notebook_keys.insert_markdown_cell, insert_markdown_cell, "Notebook insert markdown cell")
  map_notebook_key("n", notebook_keys.clear_cell_status, clear_cell_status, "Notebook clear cell status")
end

local function setup_notebook_buffer()
  local bufnr = vim.api.nvim_get_current_buf()
  if vim.b[bufnr].eos_notebook_buffer then
    render_cell_markers(bufnr)
    return
  end

  if not vim.fn.expand("%:p"):match("%.ipynb$") and not has_cell_markers(bufnr) then
    return
  end

  vim.b[bufnr].eos_notebook_buffer = true
  vim.opt_local.signcolumn = "yes:2"
  vim.opt_local.cursorline = true
  notebook_buffer_keymaps()
  render_cell_markers(bufnr)

  local group = vim.api.nvim_create_augroup("EosNotebookBuffer" .. bufnr, { clear = true })
  vim.api.nvim_create_autocmd({ "BufEnter", "CursorMoved", "CursorMovedI", "TextChanged", "TextChangedI" }, {
    group = group,
    buffer = bufnr,
    callback = function()
      render_cell_markers(bufnr)
    end,
  })
end

return {
  {
    "goerz/jupytext.nvim",
    version = "0.2.0",
    lazy = false,
    build = patch_jupytext_notebook_lifecycle,
    opts = {
      jupytext = vim.fn.executable(notebook_jupytext) == 1 and notebook_jupytext or "jupytext",
      format = "py:percent",
      update = true,
      filetype = "python",
      autosync = true,
    },
    config = function(plugin, opts)
      patch_jupytext_notebook_lifecycle(plugin)
      require("jupytext").setup(opts)
    end,
  },
  {
    "3rd/image.nvim",
    commit = "88351f1f7d9dbae286e671ce3690a49660dd8a5c",
    lazy = false,
    build = patch_image_nvim_sixel_backend,
    opts = function()
      local ok, image_utils = pcall(require, "image/utils")
      if ok and image_utils.tmux.is_tmux then
        -- EOS enforces allow-passthrough in tmux.conf. The subprocess probe can
        -- fail in restricted agent panes and otherwise poisons the cached value.
        image_utils.tmux.has_passthrough = true
      end

      return {
        backend = eos_image_backend(),
        processor = "magick_cli",
        integrations = {
          markdown = { enabled = false },
          neorg = { enabled = false },
          html = { enabled = false },
          css = { enabled = false },
        },
        max_width = 100,
        max_height = 24,
        max_width_window_percentage = math.huge,
        max_height_window_percentage = math.huge,
        window_overlap_clear_enabled = false,
        window_overlap_clear_ft_ignore = { "cmp_menu", "cmp_docs", "" },
      }
    end,
    config = function(plugin, opts)
      patch_image_nvim_sixel_backend(plugin)
      require("image").setup(opts)
    end,
  },
  {
    "benlubas/molten-nvim",
    commit = "bedea63819c618e007e7c40059fc6e72d598c8df",
    lazy = false,
    build = function(plugin)
      patch_molten_virtual_output_layout(plugin)
      vim.cmd("UpdateRemotePlugins")
    end,
    config = function(plugin)
      -- Re-assert EOS patches on every load so an existing pinned checkout is
      -- repaired immediately after EOS updates, without reinstalling plugins.
      patch_molten_virtual_output_layout(plugin)
    end,
    dependencies = {
      "3rd/image.nvim",
      {
        "willothy/wezterm.nvim",
        commit = "032c33b621b96cc7228955b4352b48141c482098",
        opts = { create_commands = false },
      },
    },
    init = function()
      vim.g.molten_image_provider = eos_molten_image_provider()
      vim.g.molten_image_location = "virt"
      vim.g.molten_split_direction = "bottom"
      vim.g.molten_split_size = 40
      vim.g.molten_auto_open_output = false
      vim.g.molten_enter_output_behavior = "open_and_enter"
      vim.g.molten_cover_empty_lines = false
      vim.g.molten_output_virt_lines = false
      vim.g.molten_virt_text_output = true
      vim.g.molten_virt_lines_off_by_1 = false
      vim.g.molten_virt_text_max_lines = 24
      vim.g.molten_wrap_output = true
      vim.g.molten_output_show_more = true
      vim.g.molten_output_show_exec_time = true
      vim.g.molten_output_win_hide_on_leave = true
      vim.g.molten_use_border_highlights = true
      vim.g.molten_tick_rate = 200
      vim.g.molten_output_win_border = { "╭", "─", "╮", "│", "╯", "─", "╰", "│" }
    end,
  },
  {
    "Vigemus/iron.nvim",
    lazy = false,
    config = function()
      local iron = require("iron.core")
      local common = require("iron.fts.common")

      vim.api.nvim_set_hl(0, "EosNotebookCellHeader", { fg = "#a6adc8", bg = "#1e2030" })
      vim.api.nvim_set_hl(0, "EosNotebookActiveCellHeader", { fg = "#cdd6f4", bg = "#2a3148", bold = true })
      vim.api.nvim_set_hl(0, "EosNotebookActiveCellLine", { bg = "#24283b" })
      vim.api.nvim_set_hl(0, "EosNotebookCodeCell", { fg = "#89b4fa", bg = "#1e2030", bold = true })
      vim.api.nvim_set_hl(0, "EosNotebookMarkdownCell", { fg = "#a6e3a1", bg = "#1e2030", bold = true })
      vim.api.nvim_set_hl(0, "EosNotebookRunCell", { fg = "#f9e2af", bg = "#1e2030", bold = true })
      vim.api.nvim_set_hl(0, "EosNotebookExecutedCell", { fg = "#3be88f", bg = "#1e2030", bold = true })
      vim.api.nvim_set_hl(0, "EosNotebookMuted", { fg = "#7f849c", bg = "#1e2030" })
      vim.api.nvim_set_hl(0, "MoltenOutputWin", { fg = "#e2e8f0", bg = "#111827" })
      vim.api.nvim_set_hl(0, "MoltenOutputWinNC", { fg = "#cbd5e1", bg = "#111827" })
      vim.api.nvim_set_hl(0, "MoltenOutputHeader", { fg = "#ecfeff", bg = "#155e75", bold = true })
      vim.api.nvim_set_hl(0, "MoltenVirtualText", { fg = "#e2e8f0", bg = "#0f172a", italic = false })
      vim.api.nvim_set_hl(0, "MoltenOutputBorder", { fg = "#60a5fa", bg = "#111827" })
      vim.api.nvim_set_hl(0, "MoltenOutputBorderSuccess", { fg = "#34d399", bg = "#111827", bold = true })
      vim.api.nvim_set_hl(0, "MoltenOutputBorderFail", { fg = "#fb7185", bg = "#111827", bold = true })
      vim.api.nvim_set_hl(0, "MoltenOutputFooter", { fg = "#64748b", bg = "#1e293b", italic = false })

      iron.setup({
        config = {
          scratch_repl = true,
          close_window_on_exit = true,
          repl_definition = {
            python = {
              command = python_repl_command,
              format = common.bracketed_paste_python,
              block_dividers = { "# %%", "#%%" },
              env = { PYTHON_BASIC_REPL = "1" },
            },
          },
          repl_filetype = function()
            return "python"
          end,
          repl_open_cmd = "botright 16 split",
          buflisted = false,
          ignore_blank_lines = true,
        },
        keymaps = {},
        highlight = {
          italic = true,
        },
      })

      vim.api.nvim_create_user_command("NotebookInit", initialize_python_repl, {})
      vim.api.nvim_create_user_command("NotebookRunCell", run_cell_inline, {})
      vim.api.nvim_create_user_command("NotebookInitKernel", molten_init_kernel, {})
      vim.api.nvim_create_user_command("NotebookRunCellInline", run_cell_inline, {})
      vim.api.nvim_create_user_command("NotebookRunCellRepl", run_current_cell, {})
      vim.api.nvim_create_user_command("NotebookRunAll", run_all_inline, {})
      vim.api.nvim_create_user_command("NotebookRunAllInline", run_all_inline, {})
      vim.api.nvim_create_user_command("NotebookRunAllRepl", run_all_cells, {})
      vim.api.nvim_create_user_command("NotebookInterruptKernel", molten_interrupt_kernel, {})
      vim.api.nvim_create_user_command("NotebookExportOutput", molten_export_output, {})
      vim.api.nvim_create_user_command("NotebookImportOutput", molten_import_output, {})
      vim.api.nvim_create_user_command("NotebookOpenOutput", molten_show_output, {})
      vim.api.nvim_create_user_command("NotebookResetSession", reset_python_session, {})
      vim.api.nvim_create_user_command("NotebookRenderCells", function()
        render_cell_markers(0)
      end, {})

      vim.api.nvim_create_autocmd({ "BufReadPost", "BufNewFile" }, {
        pattern = { "*.ipynb", "*.py" },
        callback = function()
          vim.schedule(function()
            setup_notebook_buffer()
          end)
        end,
      })

      vim.api.nvim_create_autocmd("FileType", {
        pattern = "python",
        callback = function()
          vim.schedule(setup_notebook_buffer)
        end,
      })

      vim.api.nvim_create_autocmd("User", {
        pattern = "MoltenKernelReady",
        callback = function(args)
          local bufnr = args.buf ~= 0 and args.buf or vim.api.nvim_get_current_buf()
          flush_pending_molten_evaluations(bufnr)
        end,
      })

      vim.api.nvim_create_autocmd("FileType", {
        pattern = "molten_output",
        callback = function(args)
          local function close_output()
            if vim.api.nvim_win_is_valid(0) then
              vim.api.nvim_win_close(0, true)
            end
          end
          vim.keymap.set("n", "q", close_output, { buffer = args.buf, silent = true, desc = "Close notebook output" })
          vim.keymap.set("n", "<Esc>", close_output, { buffer = args.buf, silent = true, desc = "Close notebook output" })
        end,
      })
    end,
    keys = {
      { "<leader>ji", molten_init_kernel, desc = "Notebook init inline kernel" },
      { "<leader>jr", run_cell_inline, desc = "Notebook run cell inline" },
      { "<leader>ja", run_all_inline, desc = "Notebook run all inline" },
      { "<leader>jo", molten_show_output, desc = "Notebook show inline output" },
      { "<leader>jf", run_current_cell, desc = "Notebook fallback run cell in REPL" },
      { "<leader>jI", molten_interrupt_kernel, desc = "Notebook interrupt inline kernel" },
      { "<leader>je", molten_export_output, desc = "Notebook export inline output" },
      { "<leader>jE", molten_import_output, desc = "Notebook import inline output" },
      { "<leader>jh", hide_python_repl, desc = "Notebook hide REPL" },
      { "<leader>jd", restart_python_repl, desc = "Notebook restart REPL" },
      { "<leader>jR", reset_python_session, desc = "Notebook reset Python session" },
      { "<leader>jc", insert_code_cell, desc = "Notebook insert code cell" },
      { "<leader>jm", insert_markdown_cell, desc = "Notebook insert markdown cell" },
      { "<leader>jx", clear_cell_status, desc = "Notebook clear cell status" },
    },
  },
}
