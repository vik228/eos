# Install

1. Confirm the repo is at `~/personal/eos`.
2. Confirm native Homebrew exists at `/opt/homebrew/bin/brew`.
3. Run:

```bash
~/personal/eos/bootstrap/bootstrap.sh
```

4. Reload shell:

```bash
source ~/.zshrc
```

5. Verify:

```bash
eos doctor
```

Bootstrap can be rerun safely.

For deterministic offline repair, skip only Homebrew and agent CLI network
updates while still installing the KB runtime and local configuration:

```bash
EOS_BOOTSTRAP_OFFLINE=1 ~/personal/eos/bootstrap/bootstrap.sh
```

Normal bootstrap treats agent CLI update failure as an error.

To update only agent CLIs without rerunning bootstrap:

```bash
~/personal/eos/scripts/install-agent-clis
```

If `~/.mcp.json` exists, bootstrap also syncs those MCP servers into the work Codex profile at `~/.codex-work/config.toml`.

Work Codex sessions should be launched with `codex-work` so work KB pending-review and propose-only capture behavior is active.
