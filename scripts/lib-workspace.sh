#!/usr/bin/env bash
set -euo pipefail

source "${EOS_ROOT:-$HOME/personal/eos}/scripts/lib-eos-config.sh"

require_tmux() {
  if ! command -v tmux >/dev/null 2>&1; then
    echo "tmux is required but was not found in PATH" >&2
    exit 1
  fi
}

resolve_dir() {
  local primary="$1"
  local fallback="${2:-}"
  if [[ -d "$primary" ]]; then
    printf '%s\n' "$primary"
  elif [[ -n "$fallback" && -d "$fallback" ]]; then
    printf '%s\n' "$fallback"
  else
    echo "Workspace path not found: $primary" >&2
    [[ -n "$fallback" ]] && echo "Fallback path not found: $fallback" >&2
    exit 1
  fi
}

run_workspace() {
  local session="$1"
  local dir="$2"
  shift 2
  local windows=("$@")

  require_tmux

  if [[ "${EOS_DRY_RUN:-0}" == "1" ]]; then
    echo "session=$session"
    echo "directory=$dir"
    printf 'window=%s\n' "${windows[@]}"
    return 0
  fi

  if tmux has-session -t "$session" 2>/dev/null; then
    if [[ "${EOS_NO_ATTACH:-0}" == "1" ]]; then
      echo "tmux session exists: $session"
    else
      tmux attach -t "$session"
    fi
    return 0
  fi

  local first="${windows[0]}"
  local first_name="${first%%:*}"
  local first_cmd="${first#*:}"
  tmux new-session -d -s "$session" -n "$first_name" -c "$dir" "$first_cmd"

  local index=2
  local spec name cmd
  for spec in "${windows[@]:1}"; do
    name="${spec%%:*}"
    cmd="${spec#*:}"
    tmux new-window -t "$session:$index" -n "$name" -c "$dir" "$cmd"
    index=$((index + 1))
  done

  tmux select-window -t "$session:1"

  if [[ "${EOS_NO_ATTACH:-0}" == "1" ]]; then
    echo "created tmux session: $session"
  else
    tmux attach -t "$session"
  fi
}
