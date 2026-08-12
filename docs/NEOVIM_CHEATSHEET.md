# Neovim Cheat Sheet

EOS uses Space as `<leader>`.

## Files

| Shortcut | Action |
| --- | --- |
| `Cmd+k` / `<leader>ff` | Search files |
| `<leader>f` / `<leader>e` | Toggle file explorer |
| `a` in explorer | Add file or directory |
| `u` in Snacks explorer | Refresh explorer |
| `<C-l>` in Oil explorer | Refresh explorer |
| `<leader>fr` | Recent files |
| `<leader>bb` | Open buffers |
| `<leader>w` / `Cmd+s` | Save file |
| `<leader>bd` | Close buffer |

## Search

| Shortcut | Action |
| --- | --- |
| `/` | Search inside current file |
| `<leader>/` | Picker search inside current file |
| `<leader>sg` | Search text across project |

## Agent Editing Review

Agent terminals write real files. Neovim auto-reloads clean buffers when Claude, Codex, or Antigravity edits files on disk. If your buffer has unsaved local edits, Neovim will not silently overwrite them.

| Shortcut | Action |
| --- | --- |
| `<leader>rd` | Diff current file |
| `<leader>rD` | Open full workspace diff |
| `<leader>rp` | Preview current hunk |
| `<leader>rs` | Accept/stage current hunk |
| `<leader>rr` | Reject/reset current hunk |
| `<leader>rS` | Accept/stage current file |
| `<leader>rR` | Reject/reset current file |
| `<leader>rh` | Show current file history |

## Agents

| Shortcut | Action |
| --- | --- |
| `<leader>ac` | Open Claude agent terminal |
| `<leader>ax` | Open Codex agent terminal |
| `<leader>ag` | Open Antigravity agent terminal |
| `<leader>ae` | Copy explain-this-code prompt |

## Notebook

| Shortcut | Action |
| --- | --- |
| `<leader>ji` | Initialize inline Jupyter kernel |
| `<leader>jr` | Run current cell inline |
| `Shift+Enter` | Run current cell inline and advance |
| `<leader>ja` | Run all cells inline |
| `<leader>jo` | Open complete scrollable cell output (`q`/`Esc` closes) |
| `<leader>jf` | Fallback run current cell in REPL |
| `<leader>jI` | Interrupt inline kernel |
| `<leader>je` | Export inline outputs to `.ipynb` |
| `<leader>jE` | Import `.ipynb` outputs |
| `<leader>jc` | Insert code cell |
| `<leader>jm` | Insert markdown cell |
| `<leader>mp` | Open formatted Markdown preview buffer (`q` returns to source) |
| `<leader>jx` | Clear inline outputs and status |
| `<leader>jR` | Reset kernel, REPL, outputs, and status |

## Editing

| Shortcut | Action |
| --- | --- |
| `Shift+v`, then `>` | Indent selected lines |
| `Shift+v`, then `<` | Unindent selected lines |
| `y` in visual mode | Copy selection to clipboard |
| `<leader>y` | Copy to clipboard |
| `<leader>p` | Paste from clipboard |
| `<leader>cf` | Format current buffer |
