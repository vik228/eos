# Keybindings

This file documents the shortcuts currently configured in EOS. tmux shortcuts use `Ctrl+a` as the prefix.

## WezTerm

| Shortcut | Action |
| --- | --- |
| `Cmd+Shift+P` | Open WezTerm launcher |
| `Cmd+B` / `Cmd+Shift+B` | Toggle Glare Safe low-reflection color mode |
| `Cmd+k` | Forward to Neovim file search |
| `Cmd+s` | Forward to Neovim save |
| `Shift+Enter` | Forward distinct Shift+Enter to terminal programs for notebook cell execution |
| `Cmd+Shift+Enter` | Split pane vertically in WezTerm |
| `Cmd+d` | Split pane horizontally in WezTerm |
| `Ctrl+Shift+h` | Move to left WezTerm pane |
| `Ctrl+Shift+j` | Move to lower WezTerm pane |
| `Ctrl+Shift+k` | Move to upper WezTerm pane |
| `Ctrl+Shift+l` | Move to right WezTerm pane |
| `Ctrl+Shift+w` | Close the focused notebook plot pane only |

Use WezTerm splits for quick temporary panes. Use tmux windows and panes for persistent project work.

## tmux

| Shortcut | Action |
| --- | --- |
| `Ctrl+a` then `Ctrl+a` | Send literal prefix to terminal program |
| `Ctrl+a` then `\|` | Split pane horizontally |
| `Ctrl+a` then `-` | Split pane vertically |
| `Ctrl+a` then `c` | New window in current pane directory |
| `Ctrl+a` then `h` | Move to left pane |
| `Ctrl+a` then `j` | Move to lower pane |
| `Ctrl+a` then `k` | Move to upper pane |
| `Ctrl+a` then `l` | Move to right pane |
| `Ctrl+a` then `z` | Zoom/unzoom current pane |
| `Ctrl+a` then `r` | Reload tmux config |

tmux also uses:

- mouse support;
- extended key passthrough for shortcuts like Shift+Enter in Neovim;
- 1-based window and pane indexes;
- vi mode in copy mode;
- automatic window renumbering;
- 50,000 lines of history.

## Neovim

| Shortcut | Mode | Action |
| --- | --- | --- |
| `Cmd+k` | normal | Search files |
| `<leader>ff` | normal | Search files |
| `<leader>f` / `<leader>e` | normal | Toggle file explorer |
| `/` then text then `Enter` | normal | Search inside current file and jump to match |
| `<leader>/` | normal | Picker search inside current file |
| `<leader>sg` | normal | Search text across project |
| `<leader>fr` | normal | Recent files |
| `<leader>bb` | normal | Open buffers |
| `<leader>w` | normal | Save current buffer |
| `Cmd+s` | normal | Save current buffer |
| `<leader>q` | normal | Quit current window |
| `<leader>bd` | normal | Close current buffer |
| `]b` / `[b` | normal | Next / previous buffer |
| `<leader>xx` | normal | Diagnostics |
| `<leader>cf` | normal | Format current buffer |
| `<leader>cp` | normal | Copy current file path |
| `<leader>ac` | normal | Open or focus Claude in a right-side WezTerm pane |
| `<leader>ax` | normal | Open or focus Codex in a right-side WezTerm pane |
| `<leader>ag` | normal | Open or focus Antigravity in a right-side WezTerm pane |
| `<leader>ae` | normal/visual | Copy an explain-this-code prompt for current line or selection |
| `<leader>rd` | normal | Diff current file |
| `<leader>rD` | normal | Open full workspace diff |
| `<leader>rp` | normal | Preview current Git hunk |
| `<leader>rs` | normal/visual | Accept/stage current hunk or selection |
| `<leader>rr` | normal/visual | Reject/reset current hunk or selection |
| `<leader>rS` | normal | Accept/stage current file |
| `<leader>rR` | normal | Reject/reset current file |
| `<leader>rh` | normal | Show current file history |
| `y` | visual | Copy selection to system clipboard |
| `<leader>y` | normal/visual | Copy to system clipboard |
| `<leader>p` | normal/visual | Paste from system clipboard |

EOS keeps Neovim AI-light by design. Long agent conversations run in tmux windows.
Shortcut choices live in `configs/nvim/lua/config/eos_keymaps.lua`.
Agent terminal profile is selected from the current directory: `~/work/**` uses work Claude/Codex homes, everything else uses personal Claude/Codex homes.
Agents run outside Neovim's split tree while preserving the shared working directory and filesystem. Direct-WezTerm profiles such as research use sibling WezTerm panes. Editors running inside tmux, such as backend, use a pane in the current tmux window so the agent stays with the editor and does not split unrelated tmux windows. Each shortcut toggles its agent pane open or closed, and exiting Neovim closes any agent panes it created.

Each declarative workspace uses an isolated tmux server named `eos-<session>`. Restarting one workspace therefore does not reuse or disturb another workspace's tmux server.
Clean buffers auto-reload from disk when agent terminals edit files. Review agent edits with the Git hunk shortcuts above.

## Shell Aliases

| Alias | Expands to |
| --- | --- |
| `ll` | `eza -la --icons --git` |
| `lt` | `eza --tree --level=2 --icons` |
| `cat` | `bat` |
| `lg` | `lazygit` |
| `gs` | `git status` |
| `ga` | `git add` |
| `gc` | `git commit` |
| `gp` | `git push` |
| `gpl` | `git pull` |
| `v` | `nvim` |
| `c` | `clear` |

## Directory Helpers

| Command | Action |
| --- | --- |
| `wrk` | `cd ~/work` |
| `per` | `cd ~/personal` |
| `res` | `cd ~/research` |
| `tools` | `cd ~/tools` |

## Workspace Commands

| Command | Purpose |
| --- | --- |
| `backend` / `eos backend` | Work backend tmux workspace |
| `research` / `eos research` | Research implementation workspace |
| `paper` / `eos paper` | Paper reading and experiments workspace |
| `algo` / `eos algo` | Algorithmic coding workspace |
| `leetcode` / `eos leetcode` | Compatibility alias for `algo` |
| `write` / `eos write` | Writing and knowledge workspace |
| `agents` / `eos agents` | Multi-agent workspace |
| `eos doctor` | Health check |

## Agent Profiles

| Context | Command behavior |
| --- | --- |
| Work Claude | `CLAUDE_CONFIG_DIR=$HOME/.claude-work ~/personal/eos/bin/claude --permission-mode auto; exec zsh` |
| Personal Claude | `claude-personal; exec zsh` |
| Work Codex | `CODEX_HOME=$HOME/.codex-work codex-work; exec zsh` |
| Personal Codex | `codex-personal; exec zsh` |
| Antigravity | Uses `antigravity-full`, which wraps `agy --dangerously-skip-permissions` |
## Markdown Preview

| Key | Action |
| --- | --- |
| `<leader>mp` | Open or refresh the current Markdown file as a formatted, read-only buffer in the editor window |
| `q` | Return from the preview to the Markdown source buffer |

The preview uses `glow`, preserves the existing Neovim split layout and approximate scroll position, and refreshes after Neovim saves, external agent writes, or window resizes. It renders a centered, readability-first column with the tracked theme in `configs/nvim/lua/config/markdown_preview_style.json`. Sibling WezTerm agent panes remain independent while the editor switches between source, notebook, and preview buffers.
