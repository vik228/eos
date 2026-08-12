# Architecture

EOS is organized around ownership boundaries.

## Config Layer

`configs/` holds one directory per tool. Each tool config is modular:

- Shell: `zshrc` composes path, exports, aliases, functions, and completion.
- tmux: a single focused file because tmux has one primary config entrypoint.
- WezTerm: Lua modules split rendering, fonts, keys, launch menu, status, events, and utilities.
- Git: main config plus work and personal identity includes.
- Neovim: LazyVim-compatible structure with lightweight local additions.

## Command Layer

`scripts/` contains commands intended to be on PATH. Workspace commands are real executables, not shell-only functions. `scripts/eos` is a thin command router that leaves room for a future Python CLI.

## Bootstrap Layer

`bootstrap/bootstrap.sh` creates required directories, backs up replaced home files, creates symlinks, makes executables executable, and runs verification.

## Test Layer

`tests/` is intentionally plain shell. The tests verify the workstation contract without requiring a dedicated framework.
