# Neovim Notebook Workflow

EOS configures Neovim so `.ipynb` files open as editable Python `# %%` cell files.

The workflow uses:

- `jupytext.nvim` to convert `.ipynb` files to `py:percent` text on open and back to `.ipynb` on save.
- `molten.nvim` to execute cells through a Jupyter kernel and show execution state, inline text output, and matplotlib/image output inside Neovim.
- `image.nvim` to render inline images from Molten output.
- `iron.nvim` as an explicit fallback for sending cells to a live IPython/Python REPL inside Neovim.
- an EOS-owned Python venv at `~/.local/share/eos/notebooks/.venv` for Neovim/Jupyter/IPython integration packages.

## Setup

Run once:

```bash
~/personal/eos/scripts/setup-notebooks
```

After that:

```bash
nvim experiment.ipynb
```

Neovim opens the notebook as Python with `# %%` cell markers. The first run action initializes Molten's Jupyter kernel and shows output inline. Runs submitted while the kernel is starting are queued until Jupyter reports that it is ready, which keeps rapid `Shift+Enter` results associated with the cells that produced them.

Molten chooses the inline Jupyter kernel in this order:

1. nearest project `.venv` from the current notebook or Python file;
2. EOS notebook venv at `~/.local/share/eos/notebooks/.venv`.

When a project `.venv` is found, EOS registers or refreshes a user Jupyter kernel for that exact `.venv` before initializing Molten. So `~/personal/research-project/notebooks/*.ipynb` uses `~/personal/research-project/.venv`, including packages like `torch`, `datasets`, and `pandas`. The Iron fallback uses the same project `.venv` lookup.

Cells are rendered with compact notebook-style headers, active-cell highlighting, cell numbers, run markers in a two-column sign gutter, Code/Markdown labels, and an `Inline HH:MM:SS` status after a cell is submitted to Molten. Executed cells show a bold green `✔✔` marker in the sign gutter and header. Molten anchors output at the evaluated percent-cell end, so a full-width darker output block stays immediately below the code that produced it instead of crossing into the next cell header. Every text, table, warning, error, and image block starts with a distinct `Output | Run N` header; `N` is the kernel run number, not the EOS cell number. The underlying file still stays editable as plain Python.

Matplotlib plots render through Molten in a dedicated 40% bottom WezTerm pane. The pane opens lazily when the first image is emitted, so running text-only cells does not create an empty terminal. Text, tables, warnings, and errors remain inline below the originating cell, while plots use WezTerm's stable `imgcat` path instead of terminal image placements that can overlap cells or exhaust renderer memory while scrolling. The persistent support tools stay in tmux. A manually launched tmux Neovim falls back to inline `image.nvim` with SIXEL because Molten's WezTerm provider cannot cross tmux. EOS pins all notebook plugins and installs an ImageMagick build with SIXEL support for that fallback. Override the fallback backend for diagnostics:

Use `Ctrl+Shift+J` to focus the plot pane, scroll through multiple figures with the trackpad or mouse, and use `Ctrl+Shift+K` to return to the editor. While the plot pane is focused, `Ctrl+Shift+W` closes only that pane. The shortcut is intentionally harmless in the editor pane, and a later plot recreates the plot pane automatically.

```bash
export EOS_NVIM_IMAGE_BACKEND=kitty
```

Valid values are `kitty`, `sixel`, and `ueberzug`. `magick -list format` must show `SIXEL`; `bootstrap/verify.sh` checks this. tmux handles SIXEL natively in this setup, while EOS keeps `allow-passthrough on` for the other terminal integrations.

The fallback REPL opens in a bottom split with a visible `PYTHON REPL` header and stronger split separator, so output should be visually separate from the notebook buffer.

## Keys

| Key | Action |
| --- | --- |
| `<leader>ji` | initialize inline Jupyter kernel |
| `<leader>jr` | run current `# %%` cell inline |
| `Shift+Enter` | run current cell inline and jump to the next cell |
| `<leader>ja` | run all cells inline |
| `<leader>jn` | jump to next cell |
| `<leader>jp` | jump to previous cell |
| `<leader>jo` | open the current cell's complete scrollable output |
| `<leader>jf` | fallback: run current cell in Iron REPL |
| `<leader>jI` | interrupt inline kernel |
| `<leader>je` | export Molten outputs to current `.ipynb` |
| `<leader>jE` | import outputs from current `.ipynb` |
| `<leader>jh` | hide REPL |
| `<leader>jd` | restart REPL |
| `<leader>jR` | restart inline kernel, restart REPL, and clear outputs/status labels |
| `<leader>jc` | insert code cell below cursor |
| `<leader>jm` | insert markdown cell below cursor |
| `<leader>jx` | clear Molten outputs and cell status labels |

In visual mode, select lines and press `<leader>jr` to run only that selection.

Inline output is intentionally capped so large logs do not overwhelm the notebook. Put the cursor in the executed cell and press `<leader>jo` to open its complete output. Use `j`/`k`, `Ctrl+d`/`Ctrl+u`, `gg`/`G`, the mouse wheel, or trackpad to scroll; press `q` or `Esc` to close it. Live output refreshes preserve the current scroll position.

WezTerm is configured to send Shift+Enter as a CSI-u key sequence, and tmux is configured to preserve extended keys. If Shift+Enter still acts like plain Enter, reload WezTerm and tmux:

```bash
tmux source-file ~/.tmux.conf
```

Commands are also available:

```vim
:NotebookInit
:NotebookRunCell
:NotebookInitKernel
:NotebookRunCellInline
:NotebookRunCellRepl
:NotebookRunAll
:NotebookRunAllInline
:NotebookRunAllRepl
:NotebookInterruptKernel
:NotebookExportOutput
:NotebookImportOutput
:NotebookOpenOutput
:NotebookResetSession
:NotebookRenderCells
```

Save with `:w`; Jupytext writes the edited text back into the `.ipynb` file. Molten outputs are live Neovim state, so use `<leader>je` when you want to export current outputs back into the `.ipynb`. Use `<leader>jE` to import saved notebook outputs into Molten.

Notebook source edits participate in EOS autosave. A change is written after 1.5 seconds of inactivity, on leaving insert mode, or when focus leaves the buffer. Notebook autosave runs `jupytext` asynchronously so the UI does not block on conversion; `Cmd+S` remains available for an immediate save.

Creating `name.ipynb` from the file explorer is supported. EOS initializes an empty file from the Jupytext notebook template before the first save. If a Jupytext `py:percent` script was accidentally given an `.ipynb` extension, EOS opens it as Python and converts it to valid notebook JSON on `Cmd+S` or `:w`.

## Creating Cells

Use normal Python percent-cell markers:

```python
# %%
print("code cell")

# %% [markdown]
# Notes for the next experiment

# %%
result = 1 + 1
result
```

Shortcut configuration lives in `configs/nvim/lua/plugins/notebooks.lua` in the `notebook_keys` table.
