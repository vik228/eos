# Bootstrap

`bootstrap/bootstrap.sh` is the setup entrypoint.

It:

- checks native Homebrew;
- runs `brew bundle` when available;
- installs latest agent CLIs with npm (`claude`, `codex`, `gemini`) and runs `agy update`;
- creates workstation directories;
- backs up replaced files into `backups/<timestamp>/`;
- creates home-directory symlinks into EOS;
- marks EOS scripts/tests executable;
- runs `bootstrap/verify.sh`.

It does not delete `~/personal/dotfiles`.

## Agent CLI Updates

Bootstrap runs:

```bash
scripts/install-agent-clis
```

This keeps Claude Code, Codex, and Gemini CLI on their latest npm releases. Claude Code is intentionally installed through npm, not the Homebrew cask. Antigravity is updated through its own `agy update` command.

## Recovery

Backups preserve the replaced path under the timestamp directory. To restore a previous `~/.zshrc`, for example:

```bash
cp -a "$EOS_ROOT/backups/<timestamp>$HOME/.zshrc" ~/.zshrc
```
