# EOS Productivity Guide

EOS is built around a simple loop: open the right workspace, keep persistent work in tmux, use agents deliberately, and verify before switching context.

## Start of Day

1. Open WezTerm.
2. Run:

```bash
eos doctor
```

3. Start the main work session:

```bash
backend
```

This creates or attaches the `backend` tmux session at `~/work/backend-project` with windows for editor, Claude, Codex, Antigravity, shell, and logs.
The editor window launches Neovim with the backend directory explicitly, so the project root is not inferred from recent-project state.

To change the backend project for one launch:

```bash
EOS_BACKEND_DIR="$HOME/work/other-backend" backend
```

For a permanent change, add this to `configs/shell/exports.zsh`:

```bash
export EOS_BACKEND_DIR="$HOME/work/other-backend"
```

## Use One Workspace Per Intent

Use semantic commands instead of manually rebuilding terminal layouts:

```bash
backend   # work backend
research  # research implementation
paper     # reading and experiments
algo      # algorithmic coding
write     # knowledge and writing
agents    # cross-agent control room
```

Use `--dry-run` when checking what a workspace will open:

```bash
backend --dry-run
```

Named profiles may replace a built-in layout with declarative YAML. Validate or
preview one without creating tmux state:

```bash
EOS_PROFILE=work eos workspace validate backend
EOS_PROFILE=work eos workspace preview backend
```

## tmux First

Keep long-running project state inside tmux:

- `Ctrl+a` then `h/j/k/l` to move between panes.
- `Ctrl+a` then `c` for a new window in the current directory.
- `Ctrl+a` then `z` to zoom the active pane.
- `Ctrl+a` then `r` after editing tmux config.

Use WezTerm splits for short-lived terminal splits. Use tmux for anything you expect to survive tab changes, app restarts, or context switches.

## Agent Workflow

Use agents for different jobs:

- Claude for architecture, discussion, and implementation planning.
- Codex for implementation in the repo.
- Antigravity for Gemini-backed debugging and walkthroughs.

Work and personal Claude/Codex profiles are separated:

```bash
CLAUDE_CONFIG_DIR=$HOME/.claude-work ~/personal/eos/bin/claude --permission-mode auto; exec zsh
claude-personal; exec zsh
CODEX_HOME=$HOME/.codex-work codex-work; exec zsh
codex-personal; exec zsh
```

`codex-work` and `codex-personal` are intentionally different from raw `codex`: they start in the right workspace, use full local sandbox access so Git metadata stays writable, keep network access enabled, and add the relevant knowledge-base directory as context. `codex-work` also prints pending work KB proposals before a backend-project session and runs a propose-only KB capture after the Codex process exits.

Claude and Codex share the same EOS-owned capture behavior. Proposed changes
are filed in the pending queue that owns the target path, even when the session
was launched from another project directory. SessionStart reminders are scoped
to the active profile: work sees work queues, personal sees personal queues.

The trailing `exec zsh` keeps the tmux window open after `/exit`, so you can restart the agent from the same window.

### Delegating a brief to another agent: `agent-run`

`scripts/agent-run` launches Codex, Antigravity or Claude **non-interactively and detached** on a
brief that lives in the knowledge base, through the same per-agent wrappers as above (so the KB
session lifecycle, doctor and audit still apply), and manages the run afterwards. It exists so a
coordinating agent can hand implementation to one model and review to another without re-typing
the working contract every time.

```bash
# implement a brief in a fresh worktree, own database, fixed commit subject
agent-run start --agent codex --model <model> --profile work \
  --brief "$EOS_WORK_KNOWLEDGE_ROOT/logs/<brief>.md" \
  --new-worktree feat/<slug> --base <sha> --repo "$EOS_WORK_ROOT/<repo>" \
  --db <app>_<slug> --subject "feat: <ticket> <what changed>" --tag <slug>

# review a range with a different model
agent-run start --agent codex --model <review-model> --review <sha>..HEAD \
  --brief "<same brief>" --worktree "$EOS_WORK_ROOT/<repo>/.claude/worktrees/feat-<slug>" --tag <slug>-review

agent-run list | status <id> | log <id> [-f] | wait <id> | stop <id>
```

`--db` tells the agent to create and use its own database; the exported variable name and URL
shape come from `AGENT_RUN_DB_ENV` (default `DATABASE_URL`) and `AGENT_RUN_DB_URL_TEMPLATE`
(default `postgresql://localhost:5432/{db}`), so set both once per project in your shell profile.

The composed prompt codifies the standing rules: work only in the named worktree, never push,
never touch `.env`, never bare-stash, own database only, WIP commits per work-list item, one
squashed hook-clean commit with the given subject and a plain body, and the brief's acceptance
items printed verbatim at the end. `--review RANGE` swaps in a findings-first review template.
`--dry-run` prints the command and prompt without launching. Runs live under
`~/.config/eos/agent-runs/<run-id>/` (`meta.json`, `prompt.txt`, `output.log`, `pid`, `exit`).
Antigravity's print mode defaults to a 5-minute timeout; `agent-run` raises it via
`AGENT_RUN_TIMEOUT` (default `8h`). Codex's wrapper reads stdin when it is not a terminal, so
`agent-run` always closes stdin.

Antigravity launches through `antigravity-full`, which wraps the `agy` CLI with `--dangerously-skip-permissions` and adds the current workspace plus work/personal KB directories. Set `ANTIGRAVITY_SKIP_PERMISSIONS=0` for one launch if you want prompts back. The old Gemini CLI OAuth path is no longer supported for Gemini Code Assist individual accounts.

## Recommended Backend Flow

1. Open:

```bash
backend
```

2. Use window 1 for Neovim.
3. Use the Claude window for architecture questions.
4. Use the Codex window for code implementation.
5. Use the Antigravity window for debugging or walkthroughs.
6. Use shell/logs windows for tests, servers, and logs.

Keep one shell window clean for commands you want to copy into notes or commits.

## Research Flow

Use:

```bash
research
```

Default path is `~/personal/research-project`, falling back to `~/research`.
The editor window launches Neovim with the resolved research directory explicitly, so recent-project state does not decide the project root.

Suggested loop:

1. Read paper notes in `notes`.
2. Implement in `editor`.
3. Run experiments in `python` or `shell`.
4. Ask Claude for architecture and Antigravity for walkthrough/debugging.
5. Commit small research checkpoints.

For notebook prototyping, open any `.ipynb` in Neovim. EOS loads it as Python `# %%` cells, runs cells through an inline Jupyter kernel with Molten, and gives notebook actions under `<leader>j`. See [Notebooks](NOTEBOOKS.md).

## Algorithmic Coding Flow

Use:

```bash
algo
```

This opens an `algo` tmux session. It uses `~/personal/leetcode` when present and falls back to `~/personal`.

Suggested loop:

1. Use `editor` for the solution.
2. Use `tests` for repeated runs.
3. Use `python` for quick REPL checks.
4. Use `notes` for patterns and mistakes.

## Writing Flow

Use:

```bash
write
```

This opens `~/personal/knowledge` with editor, notes, and shell windows.

Keep writing separate from implementation work. It reduces accidental context switching and makes notes easier to find later.

## Daily Maintenance

Run these when something feels off:

```bash
eos doctor
~/personal/eos/bootstrap/verify.sh
```

After changing EOS:

```bash
~/personal/eos/tests/test_workspace_scripts.sh
~/personal/eos/bootstrap/verify.sh
git status --short
```

## Recovery

Bootstrap backs up replaced home files under:

```text
~/personal/eos/backups/<timestamp>/
```

To restore a backed-up file, copy it from the timestamped backup path to its original location.
