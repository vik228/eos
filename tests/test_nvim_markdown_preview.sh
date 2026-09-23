#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fixture="$(mktemp -t eos-markdown-preview).md"
trap 'unlink "$fixture" 2>/dev/null || true' EXIT
cp "$ROOT/README.md" "$fixture"

output="$(nvim --headless -u NONE \
  "+set rtp+=$ROOT/configs/nvim" \
  "+edit $fixture" \
  '+lua _G.source_win=vim.api.nvim_get_current_win(); _G.source_buf=vim.api.nvim_get_current_buf(); vim.cmd("vsplit | enew"); _G.agent_win=vim.api.nvim_get_current_win(); _G.agent_buf=vim.api.nvim_get_current_buf(); vim.api.nvim_set_current_win(_G.source_win); require("config.markdown_preview").open(); _G.preview_buf=vim.api.nvim_get_current_buf(); assert(#vim.api.nvim_list_tabpages()==1, "preview must not create a Neovim tab page"); assert(#vim.api.nvim_tabpage_list_wins(0)==2, "preview must preserve the agent split"); assert(vim.bo[_G.preview_buf].buflisted, "preview must appear in bufferline"); assert(vim.api.nvim_win_get_buf(_G.agent_win)==_G.agent_buf); vim.api.nvim_win_set_buf(_G.source_win, _G.source_buf); vim.cmd("enew"); _G.other_buf=vim.api.nvim_get_current_buf(); vim.fn.writefile({"", "external update"}, vim.api.nvim_buf_get_name(_G.source_buf), "a")' \
  '+sleep 1200m' \
  '+lua assert(vim.api.nvim_get_current_buf()==_G.other_buf, "background refresh hijacked the editor window"); assert(vim.wo.winbar=="", "preview winbar leaked into normal editor buffer"); assert(vim.api.nvim_win_get_buf(_G.agent_win)==_G.agent_buf, "background refresh changed the agent window"); assert(vim.api.nvim_buf_is_valid(_G.preview_buf), "hidden preview buffer was deleted"); vim.api.nvim_set_current_win(_G.source_win); for _=1,4 do vim.cmd("enew") end; vim.api.nvim_win_set_buf(_G.source_win, _G.source_buf); require("config.markdown_preview").open(); assert(vim.api.nvim_get_current_win()==_G.source_win, "preview did not reacquire editor window after buffer churn"); assert(vim.bo.filetype=="markdown-preview", "preview did not reopen after buffer churn"); local current_preview=vim.api.nvim_get_current_buf(); vim.api.nvim_buf_delete(_G.source_buf,{force=true}); require("config.markdown_preview").open(); assert(vim.wait(2000,function() return vim.api.nvim_get_current_buf()~=current_preview end,20), "preview was not regenerated after source buffer closed"); assert(vim.bo.filetype=="markdown-preview", "preview did not rerun after source buffer closed first"); assert(vim.api.nvim_win_get_buf(_G.agent_win)==_G.agent_buf, "preview churn changed the agent window")' \
  '+qa!' 2>&1)"
[[ "$output" != *"Error in command line"* ]] || { printf '%s\n' "$output" >&2; exit 1; }

echo "nvim Markdown preview layout ok"
