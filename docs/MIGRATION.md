# Migration

EOS was created from the existing `~/personal/dotfiles` v1 layout.

## Source

Existing files were inspected under:

```text
~/personal/dotfiles
```

The old directory was not deleted and remains available as a reference.

## Changes

- Shell config moved from `dotfiles/shell/` to `configs/shell/`.
- Starship moved from `dotfiles/shell/starship.toml` to `configs/starship/starship.toml`.
- tmux moved from `dotfiles/tmux/` to `configs/tmux/`.
- Git moved from `dotfiles/git/` to `configs/git/`.
- WezTerm moved from `dotfiles/wezterm/` to modular `configs/wezterm/`.
- The old `backend` script became one of several semantic workspace commands in `scripts/`.

## Backups

Bootstrap backs up each replaced home path under:

```text
~/personal/eos/backups/<timestamp>/
```

## Neovim

EOS prepares `configs/nvim/` but does not overwrite `~/.config/nvim`.
