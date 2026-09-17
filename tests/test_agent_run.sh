#!/usr/bin/env bash
# agent-run: dry-run and bookkeeping behaviour, without launching any agent.
set -euo pipefail

ROOT="${EOS_ROOT:-$HOME/personal/eos}"
script="$ROOT/scripts/agent-run"
[[ -f "$script" ]] || { echo "missing script: $script"; exit 1; }
[[ -x "$script" ]] || { echo "script not executable: $script"; exit 1; }
bash -n "$script"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
export EOS_AGENT_RUNS_DIR="$tmp/runs"
export EOS_WORK_KNOWLEDGE_ROOT="$tmp/kb" EOS_PERSONAL_KNOWLEDGE_ROOT="$tmp/kb"
mkdir -p "$tmp/kb/logs"
brief="$tmp/kb/logs/brief.md"
printf '# brief\n\n## Acceptance\n1. tests pass\n' > "$brief"

# a throwaway repo with one commit, and an existing worktree
repo="$tmp/repo"
git init -q "$repo"
git -C "$repo" -c user.name=t -c user.email=t@example.com commit -q --allow-empty -m "init"
base="$(git -C "$repo" rev-parse --short HEAD)"
git -C "$repo" worktree add -q "$repo/.claude/worktrees/existing" -b feat/existing "$base"

"$script" --help >/dev/null
"$script" list >/dev/null                                   # empty runs dir must not crash
[[ -z "$("$script" list | tail -n +2)" ]]

# implement template, existing worktree, generic db template by default
out="$("$script" start --dry-run --agent codex --model m1 --profile work \
  --brief "$brief" --worktree "$repo/.claude/worktrees/existing" --db app_x \
  --subject "feat: X do the thing" --tag x)"
[[ "$out" == *"[dry-run] run id would be: "*"-codex-x"* ]]
[[ "$out" == *"codex-work"*" exec "*"-m"*"m1"* ]]
[[ "$out" == *"Implement the brief at $brief in full."* ]]
[[ "$out" == *"on branch feat/existing at HEAD $base"* ]]
[[ "$out" == *"export DATABASE_URL=postgresql://localhost:5432/app_x"* ]]
[[ "$out" == *"Commit subject exactly: feat: X do the thing"* ]]
[[ "$out" == *"no trailer lines of any kind"* ]]
[[ "$out" == *"acceptance items verbatim"* ]]

# db env/template are configurable
out="$(AGENT_RUN_DB_ENV=MY_DB AGENT_RUN_DB_URL_TEMPLATE='sqlite:///{db}.db' "$script" start --dry-run \
  --agent codex --brief "$brief" --worktree "$repo/.claude/worktrees/existing" --db app_y)"
[[ "$out" == *"export MY_DB=sqlite:///app_y.db"* ]]

# review template, antigravity command shape, raised print timeout
out="$("$script" start --dry-run --agent antigravity --model m2 --effort low --review "$base..HEAD" \
  --brief "$brief" --worktree "$repo/.claude/worktrees/existing")"
[[ "$out" == *"antigravity-full"*"--print"* ]]
[[ "$out" == *"--print-timeout"*"8h"* ]]
[[ "$out" == *"--model"*"m2"* ]]
[[ "$out" == *"--effort"*"low"* ]]
[[ "$out" == *"Review the changes in git range $base..HEAD"* ]]
[[ "$out" != *"Implement the brief"* ]]

# claude command shape
out="$("$script" start --dry-run --agent claude --model m3 --profile personal \
  --brief "$brief" --worktree "$repo/.claude/worktrees/existing")"
[[ "$out" == *"claude-personal"*" -p "* ]]

# --new-worktree in dry-run must not create anything
out="$("$script" start --dry-run --agent codex --brief "$brief" \
  --new-worktree feat/new-one --base "$base" --repo "$repo")"
[[ "$out" == *"would: git -C $repo worktree add $repo/.claude/worktrees/feat-new-one -b feat/new-one $base"* ]]
[[ ! -e "$repo/.claude/worktrees/feat-new-one" ]]
[[ "$out" == *"on branch feat/new-one at HEAD $base"* ]]

# dry-run leaves no run directory behind
[[ -z "$(ls -A "$EOS_AGENT_RUNS_DIR" 2>/dev/null)" ]]

# argument validation
! "$script" start --dry-run --brief "$brief" --worktree "$repo" >/dev/null 2>&1          # missing --agent
! "$script" start --dry-run --agent codex --worktree "$repo" >/dev/null 2>&1              # missing --brief
! "$script" start --dry-run --agent codex --brief "$tmp/nope.md" --worktree "$repo" >/dev/null 2>&1
! "$script" start --dry-run --agent nosuch --brief "$brief" --worktree "$repo" >/dev/null 2>&1
! "$script" status nosuch >/dev/null 2>&1

echo "agent-run tests passed"
