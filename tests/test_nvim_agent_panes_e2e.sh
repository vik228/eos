#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/eos-agent-pane.XXXXXX")"
trap 'find "$tmpdir" -type f -delete 2>/dev/null || true; rmdir "$tmpdir" 2>/dev/null || true' EXIT
log="$tmpdir/wezterm.log"
state="$tmpdir/wezterm.state"
: > "$log"

output="$(env -u TMUX PATH="$ROOT/tests/fixtures:$PATH" \
  WEZTERM_PANE=100 \
  WEZTERM_UNIX_SOCKET="$tmpdir/stale-gui-socket" \
  EOS_TEST_ROOT="$ROOT" \
  EOS_TEST_WEZTERM_LOG="$log" \
  EOS_TEST_WEZTERM_STATE="$state" \
  nvim -i NONE --headless -u NONE \
  -c "lua dofile('$ROOT/tests/nvim_agent_panes_e2e.lua')" 2>&1)" || {
  printf '%s\n' "$output" >&2
  exit 1
}

[[ "$(grep -c '^cli split-pane ' "$log")" == 2 ]] || {
  echo "agent pane did not reopen after toggle close" >&2
  exit 1
}
grep -q '^cli split-pane --top-level --right --pane-id 100 --percent 42 ' "$log"
[[ "$(grep -c '^cli kill-pane --pane-id 4242$' "$log")" == 2 ]]

echo "nvim WezTerm agent panes ok"

nested_log="$tmpdir/nested-tmux.log"
nested_state="$tmpdir/nested-tmux.state"
: > "$nested_log"
output="$(PATH="$ROOT/tests/fixtures:$PATH" \
  TMUX=/tmp/fake-tmux \
  TMUX_PANE=%1 \
  EOS_TMUX_BIN="$ROOT/tests/fixtures/tmux" \
  WEZTERM_PANE=100 \
  WEZTERM_UNIX_SOCKET="$tmpdir/stale-gui-socket" \
  EOS_TEST_ROOT="$ROOT" \
  EOS_TEST_TMUX_LOG="$nested_log" \
  EOS_TEST_TMUX_STATE="$nested_state" \
  nvim -i NONE --headless -u NONE \
  -c "lua dofile('$ROOT/tests/nvim_agent_tmux_panes_e2e.lua')" 2>&1)" || {
  printf '%s\n' "$output" >&2
  exit 1
}
grep -q '^split-window -h -d -P -F #{pane_id} -t %1 ' "$nested_log"
[[ "$(grep -c '^kill-pane -t %42$' "$nested_log")" == 2 ]]

echo "nvim nested tmux-window agent panes ok"

tmux_log="$tmpdir/tmux.log"
tmux_state="$tmpdir/tmux.state"
: > "$tmux_log"
output="$(env -u WEZTERM_PANE PATH="$ROOT/tests/fixtures:$PATH" \
  TMUX=/tmp/fake-tmux \
  TMUX_PANE=%1 \
  EOS_TMUX_BIN="$ROOT/tests/fixtures/tmux" \
  EOS_TEST_ROOT="$ROOT" \
  EOS_TEST_TMUX_LOG="$tmux_log" \
  EOS_TEST_TMUX_STATE="$tmux_state" \
  nvim -i NONE --headless -u NONE \
  -c "lua dofile('$ROOT/tests/nvim_agent_tmux_panes_e2e.lua')" 2>&1)" || {
  printf '%s\n' "$output" >&2
  exit 1
}
[[ "$(grep -c '^split-window -h ' "$tmux_log")" == 2 ]] || {
  echo "tmux agent pane did not reopen after toggle close" >&2
  exit 1
}
grep -q '^split-window -h -d -P -F #{pane_id} -t %1 ' "$tmux_log"
[[ "$(grep -c '^kill-pane -t %42$' "$tmux_log")" == 2 ]]

echo "nvim tmux agent panes ok"
