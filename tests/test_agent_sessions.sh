#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for script in claude-default codex-default claude-work gemini-eos claude-personal codex-work codex-personal antigravity-full; do
  [[ -x "$ROOT/scripts/$script" ]] || { echo "missing wrapper $script"; exit 1; }
  bash -n "$ROOT/scripts/$script"
done

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/kb" "$tmp/bin"
log="$tmp/events"
cat > "$tmp/bin/kb" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${SESSION_LOG:?}"
if [[ "$1 $2" == "session start" ]]; then printf '%s\n' '{"data":{"session_id":"eos-test"}}'; fi
if [[ "$1" == "checkpoint" && -n "${FAIL_FIRST_CHECKPOINT_FILE:-}" && ! -e "$FAIL_FIRST_CHECKPOINT_FILE" ]]; then
  : > "$FAIL_FIRST_CHECKPOINT_FILE"
  exit 1
fi
exit 0
EOF
cat > "$tmp/bin/agent" <<'EOF'
#!/usr/bin/env bash
printf 'agent\n' >> "${SESSION_LOG:?}"
printf 'agent-session=%s\n' "${EOS_AGENT_SESSION_ID:-}" >> "$SESSION_LOG"
printf 'agent-kb=%s\n' "${EOS_KB_ROOT:-}" >> "$SESSION_LOG"
if [[ -n "${HOOK_PATH:-}" ]]; then
  printf '%s' '{"hook_event_name":"Stop","session_id":"claude-native-test"}' | "$HOOK_PATH" Stop >> "${HOOK_OUTPUT:?}"
fi
exit "${AGENT_RC:-0}"
EOF
chmod +x "$tmp/bin/kb" "$tmp/bin/agent"

output="$(HOME="$tmp/home" EOS_ROOT="$ROOT" EOS_AGENT_DOCTOR=: EOS_KB_BIN="$tmp/bin/kb" EOS_KB_ROOT="$tmp/kb" EOS_AGENT_BIN="$tmp/bin/agent" SESSION_LOG="$log" "$ROOT/scripts/claude-default" --dry-run)"
[[ "$output" == *"kb audit"* && "$output" == *"kb session start"* && "$output" == *"--append-system-prompt-file"* ]]

HOME="$tmp/home" EOS_ROOT="$ROOT" EOS_AGENT_DOCTOR=: EOS_KB_BIN="$tmp/bin/kb" EOS_KB_ROOT="$tmp/kb" EOS_AGENT_BIN="$tmp/bin/agent" SESSION_LOG="$log" "$ROOT/scripts/claude-default"
grep -q '^agent$' "$log"
grep -q 'session end' "$log"

workspace="$tmp/workspace"
work_kb="$tmp/work-kb"
mkdir -p "$workspace" "$work_kb"
: > "$log"
HOME="$tmp/home" XDG_STATE_HOME="$tmp/state" EOS_ROOT="$ROOT" \
  EOS_AGENT_DOCTOR=: EOS_KB_BIN="$tmp/bin/kb" EOS_AGENT_BIN="$tmp/bin/agent" \
  EOS_AGENT_CWD="$workspace" EOS_WORK_KNOWLEDGE_ROOT="$work_kb" \
  SESSION_LOG="$log" HOOK_PATH="$ROOT/configs/agents/claude/hooks/eos-agent-hook" \
  HOOK_OUTPUT="$tmp/hook-output" FAIL_FIRST_CHECKPOINT_FILE="$tmp/failed-checkpoint" \
  "$ROOT/scripts/claude-work"
grep -Fxq 'agent-session=eos-test' "$log"
grep -Fxq "agent-kb=$work_kb" "$log"
[[ "$(grep -c '^session start ' "$log")" == 1 ]]
grep -q "checkpoint --kb $work_kb --session eos-test" "$log"
grep -q "session resume eos-test --native-id claude-native-test --kb $work_kb --json" "$log"
grep -q '"continue":true' "$tmp/hook-output"

personal_kb="$tmp/personal-kb"
mkdir -p "$personal_kb"
: > "$log"
: > "$tmp/hook-output"
HOME="$tmp/home" EOS_ROOT="$ROOT" EOS_AGENT_DOCTOR=: \
  EOS_KB_BIN="$tmp/bin/kb" EOS_AGENT_BIN="$tmp/bin/agent" \
  EOS_AGENT_CWD="$workspace" EOS_PERSONAL_KNOWLEDGE_ROOT="$personal_kb" \
  SESSION_LOG="$log" HOOK_PATH="$ROOT/configs/agents/claude/hooks/eos-agent-hook" \
  HOOK_OUTPUT="$tmp/hook-output" "$ROOT/scripts/claude-personal"
grep -Fxq 'agent-session=eos-test' "$log"
grep -Fxq "agent-kb=$personal_kb" "$log"
[[ "$(grep -c '^session start ' "$log")" == 1 ]]
grep -q "checkpoint --kb $personal_kb --session eos-test" "$log"
grep -q '"continue":true' "$tmp/hook-output"
echo "agent sessions ok"
