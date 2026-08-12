return {
  {
    "folke/which-key.nvim",
    optional = true,
    init = function()
      vim.keymap.set({ "n", "i", "v" }, "<D-s>", "<cmd>w<cr>", { desc = "Save file" })

      local group = vim.api.nvim_create_augroup("AutoSave", { clear = true })
      local writing = {}
      local queued = {}
      local request_autosave

      local function jupytext_bin()
        local candidate = vim.fn.expand("~/.local/share/eos/notebooks/.venv/bin/jupytext")
        if vim.fn.executable(candidate) == 1 then
          return candidate
        end
        return "jupytext"
      end

      local function should_autosave(bufnr)
        if not vim.api.nvim_buf_is_valid(bufnr) then
          return false
        end
        if not vim.bo[bufnr].modified or not vim.bo[bufnr].modifiable then
          return false
        end
        if vim.bo[bufnr].buftype ~= "" then
          return false
        end
        local name = vim.api.nvim_buf_get_name(bufnr)
        if name == "" then
          return false
        end
        if name:match("^/tmp/") or name:match("^/private/tmp/") then
          return false
        end
        return true
      end

      local function destination_is_json(path)
        local fd = vim.uv.fs_open(path, "r", 420)
        if not fd then
          return false
        end
        local data = vim.uv.fs_read(fd, 64, 0)
        vim.uv.fs_close(fd)
        return type(data) == "string" and data:match("^%s*{") ~= nil
      end

      local function write_tempfile(path, lines)
        local fh, err = io.open(path, "w")
        if not fh then
          return false, err
        end
        for _, line in ipairs(lines) do
          fh:write(line, "\n")
        end
        fh:close()
        return true
      end

      local function finish_write(bufnr)
        writing[bufnr] = nil
        if queued[bufnr] then
          queued[bufnr] = nil
          vim.schedule(function()
            request_autosave(bufnr)
          end)
        end
      end

      local function async_write_notebook(bufnr, path)
        local lines = vim.api.nvim_buf_get_lines(bufnr, 0, -1, false)
        local tick = vim.api.nvim_buf_get_changedtick(bufnr)
        local tempdir = vim.fn.tempname()
        vim.fn.mkdir(tempdir, "p")
        local tempfile = tempdir .. "/" .. vim.fn.fnamemodify(path, ":t:r") .. ".py"
        local ok, err = write_tempfile(tempfile, lines)
        if not ok then
          vim.fn.delete(tempdir, "rf")
          finish_write(bufnr)
          vim.notify("Autosave tempfile failed: " .. tostring(err), vim.log.levels.WARN)
          return
        end

        local cmd = { jupytext_bin(), "--to", "ipynb" }
        if destination_is_json(path) then
          table.insert(cmd, "--update")
        end
        table.insert(cmd, "--output")
        table.insert(cmd, path)
        table.insert(cmd, tempfile)

        -- jupytext runs off-thread; only buffer snapshot and tiny header peek stay on main.
        vim.system(cmd, { text = true }, function(proc)
          vim.schedule(function()
            vim.fn.delete(tempdir, "rf")
            if proc.code == 0 and vim.api.nvim_buf_is_valid(bufnr) then
              if vim.api.nvim_buf_get_changedtick(bufnr) == tick then
                vim.bo[bufnr].modified = false
                local stat = vim.uv.fs_stat(path)
                if stat then
                  vim.b[bufnr].mtime = stat.mtime
                end
              end
            elseif proc.code ~= 0 then
              local msg = (proc.stderr or proc.stdout or ""):gsub("%s+$", "")
              if msg ~= "" then
                vim.notify("Notebook autosave failed: " .. msg, vim.log.levels.WARN)
              end
            end
            finish_write(bufnr)
          end)
        end)
      end

      local function sync_write_buffer(bufnr)
        vim.api.nvim_buf_call(bufnr, function()
          vim.cmd("silent! write")
        end)
        finish_write(bufnr)
      end

      request_autosave = function(bufnr)
        if not should_autosave(bufnr) then
          return
        end
        if writing[bufnr] then
          queued[bufnr] = true
          return
        end
        writing[bufnr] = true

        local path = vim.api.nvim_buf_get_name(bufnr)
        if path:match("%.ipynb$") then
          async_write_notebook(bufnr, path)
        else
          -- Keep plain-file writes off the autocmd stack so nested BufWrite* still run.
          vim.schedule(function()
            if should_autosave(bufnr) then
              sync_write_buffer(bufnr)
            else
              finish_write(bufnr)
            end
          end)
        end
      end

      vim.api.nvim_create_autocmd({ "FocusLost", "BufLeave" }, {
        group = group,
        callback = function(args)
          local bufnr = args.buf
          vim.schedule(function()
            request_autosave(bufnr)
          end)
        end,
      })

      local timer = vim.uv.new_timer()
      vim.api.nvim_create_autocmd({ "InsertLeave", "TextChanged" }, {
        group = group,
        callback = function(args)
          local bufnr = args.buf
          timer:stop()
          timer:start(1500, 0, vim.schedule_wrap(function()
            request_autosave(bufnr)
          end))
        end,
      })

      vim.api.nvim_create_autocmd("InsertEnter", {
        group = group,
        callback = function()
          timer:stop()
        end,
      })
    end,
  },
}
