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
[[ "$out" == *"brief's commit policy"* ]]
[[ "$out" == *"squash into one commit only when the brief gives none"* ]]
[[ "$out" == *"--no-verify"* ]]
[[ "$out" != *"Finish with ONE squashed commit"* ]]

# --extra text is appended to the prompt
out_extra="$("$script" start --dry-run --agent codex \
  --brief "$brief" --worktree "$repo/.claude/worktrees/existing" --extra "EXTRA-MARKER-123")"
[[ "$out_extra" == *"EXTRA-MARKER-123"* ]]

# db env/template are configurable
out="$(AGENT_RUN_DB_ENV=MY_DB AGENT_RUN_DB_URL_TEMPLATE='sqlite:///{db}.db' "$script" start --dry-run \
  --agent codex --brief "$brief" --worktree "$repo/.claude/worktrees/existing" --db app_y)"
[[ "$out" == *"export MY_DB=sqlite:///app_y.db"* ]]

# review template, antigravity command shape, raised print timeout (personal profile)
out="$("$script" start --dry-run --agent antigravity --profile personal --model m2 --effort low --review "$base..HEAD" \
  --brief "$brief" --worktree "$repo/.claude/worktrees/existing")"
[[ "$out" == *"antigravity-full"*"--print"* ]]
[[ "$out" == *"--print-timeout"*"8h"* ]]
[[ "$out" == *"--model"*"m2"* ]]
[[ "$out" == *"--effort"*"low"* ]]
[[ "$out" == *"Review the changes in git range $base..HEAD"* ]]
[[ "$out" != *"Implement the brief"* ]]
[[ "$out" == *"logs/"* ]]
[[ "$out" == *"Log frontmatter"* ]]
[[ "$out" == *"title"* ]]
[[ "$out" == *"type Log"* ]]
[[ "$out" == *"date"* ]]
[[ "$out" == *"status"* ]]
[[ "$out" == *"freshness: historical"* ]]
[[ "$out" != *"stale_after"* ]]

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

# --dir + --no-commit for non-code briefs: plain dir, report-only prompt
mkdir -p "$tmp/scratch"
out="$("$script" start --dry-run --agent claude --profile personal \
  --brief "$brief" --dir "$tmp/scratch" --no-commit)"
[[ "$out" == *"[no-commit]"* ]]
[[ "$out" == *"Do not commit anything"* ]]
[[ "$out" != *"Commit work in progress"* ]]
[[ "$out" != *"squash into one commit"* ]]
[[ "$out" == *"acceptance items verbatim"* ]]
# --dir refuses worktree combos and missing dirs
! "$script" start --dry-run --agent codex --brief "$brief" --dir "$tmp/scratch" --worktree "$repo" >/dev/null 2>&1
! "$script" start --dry-run --agent codex --brief "$brief" --dir "$tmp/nope" >/dev/null 2>&1

# opencode runs personal-only
out="$("$script" start --dry-run --agent opencode --profile personal \
  --brief "$brief" --worktree "$repo/.claude/worktrees/existing")"
[[ "$out" == *"opencode-personal"*run* ]]
[[ "$out" == *"OPENCODE_PERMISSION_MODE=auto"* ]]
[[ "$out" != *"Finish with ONE squashed"* ]]
! "$script" start --dry-run --agent opencode --profile work \
  --brief "$brief" --worktree "$repo" >/dev/null 2>&1
[[ "$("$script" start --dry-run --agent opencode --profile work \
  --brief "$brief" --worktree "$repo" 2>&1 || true)" == *"personal"* ]]
EOS_ALLOW_PERSONAL_AGENT_IN_WORK=1 "$script" start --dry-run --agent opencode --profile work \
  --brief "$brief" --worktree "$repo" >/dev/null 2>&1

# antigravity is refused in the work profile too (default profile is work)
! "$script" start --dry-run --agent antigravity --brief "$brief" --worktree "$repo" >/dev/null 2>&1
[[ "$("$script" start --dry-run --agent antigravity --brief "$brief" --worktree "$repo" 2>&1 || true)" == *"use codex or claude"* ]]
EOS_ALLOW_PERSONAL_AGENT_IN_WORK=1 "$script" start --dry-run --agent antigravity --profile work \
  --brief "$brief" --worktree "$repo" >/dev/null 2>&1
# ---- single-account work-tree guards (stubs so a guard regression can never launch a real agent) ----
work_tree="$tmp/work/proj"; mkdir -p "$work_tree"
work_tree_phys="$(cd "$work_tree" && pwd -P)"
stub_agent="$tmp/stub-agent"; stub_kb="$tmp/stub-kb"; stub_home="$tmp/home"
mkdir -p "$stub_home"
cat > "$stub_agent" <<'EOF'
#!/usr/bin/env bash
printf 'LAUNCHED %s\n' "$*" >> "${STUB_AGENT_LOG:?}"
EOF
cat > "$stub_kb" <<'EOF'
#!/usr/bin/env bash
printf '{"data":{"session_id":"stub"},"status":"ok","exit_code":0}\n'
EOF
chmod +x "$stub_agent" "$stub_kb"
export STUB_AGENT_LOG="$tmp/stub-agent.log"
: > "$STUB_AGENT_LOG"
mkdir -p "$tmp/personal-kb/logs" "$tmp/work-kb/logs" "$tmp/scratch"
# guard_env must precede every direct wrapper invocation below: isolated HOME
# and KB roots, stub agent/kb bins, no real doctor, so a guard regression
# launches the stub instead of a real agent session.
guard_env=(env "EOS_ROOT=$ROOT" "HOME=$stub_home" "EOS_AGENT_DOCTOR=:" "EOS_AGENT_BIN=$stub_agent" "EOS_KB_BIN=$stub_kb"
  "EOS_PERSONAL_KNOWLEDGE_ROOT=$tmp/personal-kb" "EOS_WORK_KNOWLEDGE_ROOT=$tmp/work-kb" "EOS_KB_ROOT=$tmp/personal-kb")

# antigravity-full refuses inside the work tree and names the path
if out="$("${guard_env[@]}" EOS_WORK_ROOT="$tmp/work" EOS_AGENT_CWD="$work_tree" "$ROOT/scripts/antigravity-full" --print "hello" 2>&1)"; then
  echo "antigravity-full should refuse the work tree"; exit 1
fi
[[ "$out" == *"must not run from the work tree"* ]]
[[ "$out" == *"$work_tree_phys"* ]]
[[ ! -s "$STUB_AGENT_LOG" ]]
# trailing slash in EOS_WORK_ROOT must not bypass the guard
! "${guard_env[@]}" EOS_WORK_ROOT="$tmp/work/" EOS_AGENT_CWD="$work_tree" "$ROOT/scripts/antigravity-full" --print "hello" >/dev/null 2>&1
[[ ! -s "$STUB_AGENT_LOG" ]]
# a symlinked path into the work tree must not bypass the guard
ln -s "$tmp/work" "$tmp/wlink"
! "${guard_env[@]}" EOS_WORK_ROOT="$tmp/work" EOS_AGENT_CWD="$tmp/wlink/proj" "$ROOT/scripts/antigravity-full" --print "hello" >/dev/null 2>&1
[[ ! -s "$STUB_AGENT_LOG" ]]
# the work KB root also refuses from a personal cwd
if out="$("${guard_env[@]}" EOS_WORK_ROOT="$tmp/work" EOS_AGENT_CWD="$tmp/scratch" EOS_KB_ROOT="$tmp/work-kb" "$ROOT/scripts/antigravity-full" --print "hello" 2>&1)"; then
  echo "antigravity-full should refuse the work KB"; exit 1
fi
[[ "$out" == *"must not run from the work tree"* ]]
[[ ! -s "$STUB_AGENT_LOG" ]]
# single-KB setup (same path for both KBs): the KB clause is skipped, cwd decides
"${guard_env[@]}" EOS_WORK_ROOT="$tmp/work" EOS_AGENT_CWD="$tmp/scratch" EOS_KB_ROOT="$tmp/kb" \
  EOS_PERSONAL_KNOWLEDGE_ROOT="$tmp/kb" EOS_WORK_KNOWLEDGE_ROOT="$tmp/kb" \
  "$ROOT/scripts/antigravity-full" --print "hello" >/dev/null 2>&1
grep -q LAUNCHED "$STUB_AGENT_LOG"
: > "$STUB_AGENT_LOG"
# dry-run is exempt anywhere in args and must exit 0
"${guard_env[@]}" EOS_WORK_ROOT="$tmp/work" EOS_AGENT_CWD="$work_tree" "$ROOT/scripts/antigravity-full" --dry-run >/dev/null 2>&1
"${guard_env[@]}" EOS_WORK_ROOT="$tmp/work" EOS_AGENT_CWD="$work_tree" "$ROOT/scripts/antigravity-full" --model m1 --dry-run --print "hello" >/dev/null 2>&1
[[ ! -s "$STUB_AGENT_LOG" ]]
# the documented override works for the wrapper
"${guard_env[@]}" EOS_WORK_ROOT="$tmp/work" EOS_AGENT_CWD="$work_tree" EOS_ALLOW_PERSONAL_AGENT_IN_WORK=1 \
  "$ROOT/scripts/antigravity-full" --print "hello" >/dev/null 2>&1
grep -q LAUNCHED "$STUB_AGENT_LOG"
: > "$STUB_AGENT_LOG"

# opencode-personal refuses inside the work tree too and names the path
if out="$("${guard_env[@]}" EOS_WORK_ROOT="$tmp/work" EOS_AGENT_CWD="$work_tree" "$ROOT/scripts/opencode-personal" run "hello" 2>&1)"; then
  echo "opencode-personal should refuse the work tree"; exit 1
fi
[[ "$out" == *"must not run from the work tree"* ]]
[[ "$out" == *"$work_tree_phys"* ]]
[[ ! -s "$STUB_AGENT_LOG" ]]
! "${guard_env[@]}" EOS_WORK_ROOT="$tmp/work/" EOS_AGENT_CWD="$work_tree" "$ROOT/scripts/opencode-personal" run "hello" >/dev/null 2>&1
! "${guard_env[@]}" EOS_WORK_ROOT="$tmp/work" EOS_AGENT_CWD="$tmp/wlink/proj" "$ROOT/scripts/opencode-personal" run "hello" >/dev/null 2>&1
[[ ! -s "$STUB_AGENT_LOG" ]]
"${guard_env[@]}" EOS_WORK_ROOT="$tmp/work" EOS_AGENT_CWD="$work_tree" "$ROOT/scripts/opencode-personal" --dry-run >/dev/null 2>&1
"${guard_env[@]}" EOS_WORK_ROOT="$tmp/work" EOS_AGENT_CWD="$work_tree" EOS_ALLOW_PERSONAL_AGENT_IN_WORK=1 \
  "$ROOT/scripts/opencode-personal" run "hello" >/dev/null 2>&1
grep -q LAUNCHED "$STUB_AGENT_LOG"
: > "$STUB_AGENT_LOG"

# opencode-work stays hard-refuse by default but honors the documented override
! "${guard_env[@]}" EOS_WORK_ROOT="$tmp/work" EOS_AGENT_CWD="$tmp/scratch" "$ROOT/scripts/opencode-work" run "hello" >/dev/null 2>&1
[[ ! -s "$STUB_AGENT_LOG" ]]
"${guard_env[@]}" EOS_WORK_ROOT="$tmp/work" EOS_AGENT_CWD="$tmp/scratch" "$ROOT/scripts/opencode-work" --dry-run >/dev/null 2>&1
"${guard_env[@]}" EOS_WORK_ROOT="$tmp/work" EOS_AGENT_CWD="$tmp/scratch" EOS_ALLOW_PERSONAL_AGENT_IN_WORK=1 \
  "$ROOT/scripts/opencode-work" run "hello" >/dev/null 2>&1
grep -q LAUNCHED "$STUB_AGENT_LOG"
: > "$STUB_AGENT_LOG"

# agent-run refuses --agent antigravity|opencode with a worktree under the work
# root even for --profile personal (dry-run is in the check path, creates nothing)
for wt_agent in antigravity opencode; do
  if out="$(EOS_WORK_ROOT="$tmp/work" "$script" start --dry-run --agent "$wt_agent" --profile personal \
      --brief "$brief" --worktree "$work_tree" 2>&1)"; then
    echo "agent-run should refuse $wt_agent in the work tree"; exit 1
  fi
  [[ "$out" == *"must not run inside the work tree"* ]]
  [[ "$out" == *"$work_tree_phys"* ]]
  # trailing slash and symlinked worktree variants refuse too
  ! EOS_WORK_ROOT="$tmp/work/" "$script" start --dry-run --agent "$wt_agent" --profile personal \
    --brief "$brief" --worktree "$work_tree" >/dev/null 2>&1
  ! EOS_WORK_ROOT="$tmp/work" "$script" start --dry-run --agent "$wt_agent" --profile personal \
    --brief "$brief" --worktree "$tmp/wlink/proj" >/dev/null 2>&1
  # the documented override lets the dry-run through
  EOS_WORK_ROOT="$tmp/work" EOS_ALLOW_PERSONAL_AGENT_IN_WORK=1 "$script" start --dry-run --agent "$wt_agent" --profile personal \
    --brief "$brief" --worktree "$work_tree" >/dev/null 2>&1
done

# dry-run leaves no run directory behind
[[ -z "$(ls -A "$EOS_AGENT_RUNS_DIR" 2>/dev/null)" ]]

# argument validation
! "$script" start --dry-run --brief "$brief" --worktree "$repo" >/dev/null 2>&1          # missing --agent
! "$script" start --dry-run --agent codex --worktree "$repo" >/dev/null 2>&1              # missing --brief
! "$script" start --dry-run --agent codex --brief "$tmp/nope.md" --worktree "$repo" >/dev/null 2>&1
! "$script" start --dry-run --agent nosuch --brief "$brief" --worktree "$repo" >/dev/null 2>&1
! "$script" status nosuch >/dev/null 2>&1

echo "agent-run tests passed"
