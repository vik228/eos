#!/usr/bin/env bash

source "${EOS_ROOT:-$HOME/personal/eos}/scripts/lib-eos-config.sh"

# Resolved codex binary for the wrappers. Sets AGENT_CODEX_BIN to the EOS
# guard (or EOS_AGENT_BIN when set). The guard itself selects the newest
# installed CLI, so the result does not depend on login vs interactive PATH
# order (nvim panes use `zsh -ic`, the WezTerm launcher and hooks use `zsh
# -lc`, research tmux inherits an interactive shell). Call directly, never via
# $(...): the PATH export must survive in the caller, and command substitution
# would discard it.
AGENT_CODEX_BIN=""
agent_codex_bin() {
  local root="${EOS_ROOT:-$HOME/personal/eos}"
  if [[ -n "${EOS_AGENT_BIN:-}" ]]; then
    AGENT_CODEX_BIN="$EOS_AGENT_BIN"
    return 0
  fi
  local guard="$root/bin/guards/codex"
  if [[ ! -x "$guard" ]]; then
    AGENT_CODEX_BIN="codex"
    return 0
  fi
  case ":$PATH:" in
    *":$root/bin/guards:"*) ;;
    *) export PATH="$root/bin/guards:$PATH" ;;
  esac
  AGENT_CODEX_BIN="$guard"
}

# Start epoch of a rollout, from its session_meta record. Prints nothing when
# the record is missing or unparseable, so such files never win selection.
codex_rollout_start() {
  local iso
  iso="$(jq -r 'select(.type == "session_meta") | .payload.timestamp // .timestamp // empty' "$1" 2>/dev/null | head -n 1 || true)"
  [[ -n "$iso" ]] || return 0
  python3 -c 'import sys,datetime; s=sys.argv[1].replace("Z","+00:00"); print(int(datetime.datetime.fromisoformat(s).timestamp()))' "$iso" 2>/dev/null || true
}

file_mtime() {
  stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null || true
}

# Owning Codex rollout for a cwd. Prints the transcript path, or nothing when
# no session wrote one. A session owns rollouts that started at or after the
# marker left before launch; among those the oldest wins, so concurrent
# sessions in one cwd each resolve to their own rollout. A resumed session
# keeps its old start time, so resume runs ($4 non-empty) instead take the
# newest file written after the marker. Pure selection, no side effects.
codex_latest_transcript() {
  local codex_home="$1" marker="$2" cwd="$3" resume="${4:-}"
  [[ -d "$codex_home/sessions" && -f "$marker" ]] || return 0
  local marker_epoch f meta_cwd start mt best="" best_key=""
  marker_epoch="$(file_mtime "$marker")"
  [[ -n "$marker_epoch" ]] || return 0
  while IFS= read -r f; do
    meta_cwd="$(jq -r 'select(.type == "session_meta") | .payload.cwd // empty' "$f" 2>/dev/null | head -n 1 || true)"
    [[ "$meta_cwd" == "$cwd" ]] || continue
    if [[ -n "$resume" ]]; then
      mt="$(file_mtime "$f")"
      [[ -n "$mt" ]] || continue
      if [[ -z "$best" || "$mt" -gt "$best_key" ]]; then best="$f"; best_key="$mt"; fi
    else
      start="$(codex_rollout_start "$f")"
      [[ -n "$start" ]] || continue
      [[ "$start" -ge "$marker_epoch" ]] || continue
      if [[ -z "$best" || "$start" -lt "$best_key" ]]; then best="$f"; best_key="$start"; fi
    fi
  done < <(find "$codex_home/sessions" -type f -name 'rollout-*.jsonl' -newer "$marker" 2>/dev/null)
  [[ -n "$best" ]] && printf '%s\n' "$best"
  return 0
}

codex_capture_log() {
  local kb_root="$1"
  shift
  [[ -n "$kb_root" ]] || return 0
  mkdir -p "$kb_root/logs" 2>/dev/null || return 0
  printf '%s [codex-capture] %s\n' "$(date -u +%FT%TZ)" "$*" >>"$kb_root/logs/.hook-debug.log" 2>/dev/null || true
}

# Codex equivalent of Claude's SessionEnd capture hook: after the wrapped
# Codex exits, capture its rollout into the pending KB. There is no PreCompact
# equivalent: Codex exposes no compact lifecycle event, and the rollout keeps
# full history anyway, so session-end capture covers everything compact would.
# Runs detached so the interactive shell returns immediately; the capture
# marker inside eos-kb-capture dedupes repeats on identical content.
# $5 is work, personal, or empty for cwd-derived (matches the Claude hooks).
# Set EOS_CODEX_CAPTURE_LOG to a file to observe the capture output (tests).
codex_session_capture() {
  local codex_home="$1" marker="$2" cwd="$3" kb_root="$4" capture_profile="${5:-auto}" resume_hint="${6:-}"
  if [[ -n "${EOS_KB_CAPTURE_RUNNING:-}" ]]; then
    codex_capture_log "$kb_root" "skip: nested capture run"
    return 0
  fi
  local transcript=""
  transcript="$(codex_latest_transcript "$codex_home" "$marker" "$cwd" "$resume_hint" || true)"
  if [[ -z "$transcript" ]]; then
    codex_capture_log "$kb_root" "skip: no rollout for $cwd"
    return 0
  fi
  local root="${EOS_ROOT:-$HOME/personal/eos}"
  local capture="$root/scripts/eos-kb-capture"
  if [[ ! -x "$capture" ]]; then
    codex_capture_log "$kb_root" "skip: capture script missing"
    return 0
  fi
  local log="${EOS_CODEX_CAPTURE_LOG:-/dev/null}"
  EOS_CAPTURE_AGENT=codex EOS_CAPTURE_PROFILE="$capture_profile" \
    EOS_CAPTURE_KB_ROOT="$kb_root" CODEX_CAPTURE_HOME="$codex_home" \
    nohup "$capture" SessionEnd "$transcript" < /dev/null >>"$log" 2>&1 &
  disown 2>/dev/null || true
  return 0
}

agent_session_uuid() {
  if command -v uuidgen >/dev/null 2>&1; then uuidgen | tr '[:upper:]' '[:lower:]'; return; fi
  printf '%s-%s-%s\n' "$(date +%s)" "$$" "${RANDOM:-0}"
}

agent_session_run() {
  local agent="" profile="" cwd="" kb_root="" native_id="" capture="" root="${EOS_ROOT:-$HOME/personal/eos}"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --agent) agent="$2"; shift 2 ;;
      --profile) profile="$2"; shift 2 ;;
      --cwd) cwd="$2"; shift 2 ;;
      --kb) kb_root="$2"; shift 2 ;;
      --native-id) native_id="$2"; shift 2 ;;
      --capture) capture="$2"; shift 2 ;;
      --) shift; break ;;
      *) echo "unknown agent session option: $1" >&2; return 2 ;;
    esac
  done
  [[ -n "$agent" && -n "$profile" && -n "$cwd" && -n "$kb_root" && $# -gt 0 ]] || {
    echo "agent session requires agent, profile, cwd, kb, and command" >&2; return 2;
  }
  [[ -z "$capture" || "$capture" == "codex" ]] || {
    echo "unknown capture agent: $capture" >&2; return 2;
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
    [[ -n "${capture_marker:-}" ]] && rm -f "$capture_marker"
    agent_session_checkpoint
    exit "$signal_status"
  }
  local capture_marker=""
  if [[ -n "$capture" ]]; then
    capture_marker="$(mktemp "${TMPDIR:-/tmp}/eos-codex-capture.XXXXXX" 2>/dev/null || true)"
  fi
  trap 'agent_session_finish' EXIT
  trap 'agent_session_signal 130' INT
  trap 'agent_session_signal 143' TERM
  EOS_AGENT_SESSION_ID="$session_id" \
    EOS_KB_ROOT="$kb_root" \
    EOS_AGENT_PROFILE="$profile" \
    "$@" || AGENT_SESSION_RC=$?
  agent_session_finish
  if [[ "$capture" == "codex" && -n "$capture_marker" ]]; then
    local capture_profile="auto" resume_hint="" arg
    if [[ "$profile" == "work" || "$profile" == "personal" ]]; then
      capture_profile="$profile"
    fi
    for arg in "${command_args[@]}"; do
      if [[ "$arg" == "resume" ]]; then
        resume_hint=1
      fi
    done
    codex_session_capture "${CODEX_HOME:-$HOME/.codex}" "$capture_marker" "$cwd" "$kb_root" "$capture_profile" "$resume_hint"
    rm -f "$capture_marker"
  fi
  trap - EXIT INT TERM
  return "$AGENT_SESSION_RC"
}
