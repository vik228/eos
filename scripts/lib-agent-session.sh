#!/usr/bin/env bash

source "${EOS_ROOT:-$HOME/personal/eos}/scripts/lib-eos-config.sh"

agent_session_uuid() {
  if command -v uuidgen >/dev/null 2>&1; then uuidgen | tr '[:upper:]' '[:lower:]'; return; fi
  printf '%s-%s-%s\n' "$(date +%s)" "$$" "${RANDOM:-0}"
}

agent_session_run() {
  local agent="" profile="" cwd="" kb_root="" native_id="" root="${EOS_ROOT:-$HOME/personal/eos}"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --agent) agent="$2"; shift 2 ;;
      --profile) profile="$2"; shift 2 ;;
      --cwd) cwd="$2"; shift 2 ;;
      --kb) kb_root="$2"; shift 2 ;;
      --native-id) native_id="$2"; shift 2 ;;
      --) shift; break ;;
      *) echo "unknown agent session option: $1" >&2; return 2 ;;
    esac
  done
  [[ -n "$agent" && -n "$profile" && -n "$cwd" && -n "$kb_root" && $# -gt 0 ]] || {
    echo "agent session requires agent, profile, cwd, kb, and command" >&2; return 2;
  }
  local kb_bin="${EOS_KB_BIN:-$root/scripts/kb}"
  local doctor="${EOS_AGENT_DOCTOR:-$root/scripts/eos doctor}"
  local command_args=("$@") dry_run=0 filtered_args=() arg
  for arg in "${command_args[@]}"; do
    if [[ "$arg" == "--dry-run" ]]; then dry_run=1; else filtered_args+=("$arg"); fi
  done
  if [[ "$dry_run" == 1 ]]; then
    printf 'doctor=%s\n' "$doctor"
    printf 'kb audit --kb %q --source-root %q --json\n' "$kb_root" "$cwd"
    printf 'kb session start --cwd %q --kb %q --agent %q --profile %q --native-id %q --json\n' "$cwd" "$kb_root" "$agent" "$profile" "${native_id:-<uuid>}"
    printf 'launch='; printf '%s ' "${filtered_args[@]}"; printf '\n'
    printf 'trap=kb checkpoint then kb session end; exit-code preserved\n'
    return 0
  fi
  [[ -d "$cwd" && -w "$cwd" ]] || {
    echo "Agent workspace is missing or not writable: $cwd. Repair its permissions before launching." >&2
    return 1
  }
  [[ -d "$kb_root" && -w "$kb_root" ]] || {
    echo "KB is missing or not writable: $kb_root. Set the profile KB root or repair its permissions before launching." >&2
    return 1
  }
  [[ -x "$kb_bin" ]] || { echo "KB CLI is missing: $kb_bin. Run scripts/setup-kb." >&2; return 1; }
  if ! eval "$doctor"; then
    echo "EOS agent doctor failed; refusing to launch $agent" >&2
    return 1
  fi
  "$kb_bin" audit --kb "$kb_root" --source-root "$cwd" --json >/dev/null || {
    echo "KB audit failed; refusing to launch $agent" >&2; return 1;
  }
  local start_output session_id
  local start_args=(session start --cwd "$cwd" --kb "$kb_root" --agent "$agent" --profile "$profile")
  native_id="${native_id:-${EOS_AGENT_NATIVE_ID:-}}"
  [[ -n "$native_id" ]] && start_args+=(--native-id "$native_id")
  start_args+=(--json)
  start_output="$($kb_bin "${start_args[@]}")" || {
    echo "KB session start failed; refusing to launch $agent" >&2; return 1;
  }
  session_id="$(printf '%s' "$start_output" | python3 -c 'import json,sys
try:
 d=json.load(sys.stdin); print(d.get("data",{}).get("session_id") or d.get("data",{}).get("id") or "")
except Exception: print("")')"
  session_id="${session_id:-${native_id:-$(agent_session_uuid)}}"
  AGENT_SESSION_FINISHED=0
  AGENT_SESSION_CHECKPOINTED=0
  AGENT_SESSION_RC=0
  agent_session_checkpoint() {
    [[ "$AGENT_SESSION_CHECKPOINTED" == 1 ]] && return 0
    AGENT_SESSION_CHECKPOINTED=1
    "$kb_bin" audit --kb "$kb_root" --source-root "$cwd" --json >/dev/null 2>&1 || true
    "$kb_bin" session checkpoint "$session_id" --kb "$kb_root" --json >/dev/null 2>&1 || true
  }
  agent_session_finish() {
    [[ "$AGENT_SESSION_FINISHED" == 1 ]] && return 0
    AGENT_SESSION_FINISHED=1
    agent_session_checkpoint
    "$kb_bin" audit --kb "$kb_root" --source-root "$cwd" --json >/dev/null 2>&1 || true
    "$kb_bin" session end "$session_id" --kb "$kb_root" --exit-code "$AGENT_SESSION_RC" --json >/dev/null 2>&1 || true
  }
  agent_session_signal() {
    signal_status="$1"
    agent_session_checkpoint
    exit "$signal_status"
  }
  trap 'agent_session_finish' EXIT
  trap 'agent_session_signal 130' INT
  trap 'agent_session_signal 143' TERM
  EOS_AGENT_SESSION_ID="$session_id" \
    EOS_KB_ROOT="$kb_root" \
    EOS_AGENT_PROFILE="$profile" \
    "$@" || AGENT_SESSION_RC=$?
  agent_session_finish
  trap - EXIT INT TERM
  return "$AGENT_SESSION_RC"
}
