#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Hermetic: a launcher-exported EOS_* profile must not steer hook routing.
while IFS= read -r name; do unset "$name"; done < <(compgen -e | grep '^EOS_' || true)
HOOK="$ROOT/configs/agents/claude/hooks/eos-agent-hook"
[[ -x "$HOOK" ]]
em_dash="$(printf '\342\200\224')"
! LC_ALL=C grep -q "$em_dash" "$HOOK"
! rg -n '[\x{0900}-\x{097F}]' "$HOOK"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
log="$tmp/kb.log"
cat > "$tmp/kb" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${HOOK_TEST_LOG:?}"
if [[ "$*" == *"bug status"* ]]; then
  printf '%s\n' '{"data":{"checkpoint_complete":true,"investigation_required":false}}'
else
  printf '%s\n' '{"status":"ok"}'
fi
EOF
chmod +x "$tmp/kb"

event() {
  printf '%s' "$2" | EOS_KB_BIN="$tmp/kb" HOOK_TEST_LOG="$log" EOS_KB_ROOT="$tmp/kb-root" EOS_PERSONAL_KNOWLEDGE_DIR="$tmp/kb-root" EOS_AGENT_SESSION_ID=s1 "$HOOK" "$1"
}

event InstructionsLoaded '{"hook_event_name":"InstructionsLoaded"}' | grep -q '"continue":true'
event SessionStart '{"hook_event_name":"SessionStart"}' | grep -q 'Every discussion uses the global interaction contract'
mkdir -p "$tmp/kb-root/projects/eos"
printf '%s\n' '# Pending' '' '- [ ] Review me.' >"$tmp/kb-root/projects/eos/_pending-kb-updates.md"
session_start="$(event SessionStart '{"hook_event_name":"SessionStart"}')"
grep -q 'pending personal KB proposal' <<<"$session_start"
grep -q 'Every discussion uses the global interaction contract' <<<"$session_start"
mkdir -p "$tmp/work-kb/projects/nova"
printf '%s\n' '# Pending' '' '- [ ] Work only.' >"$tmp/work-kb/projects/nova/_pending-kb-updates.md"
work_start="$(printf '%s' '{"hook_event_name":"SessionStart"}' | \
  EOS_KB_BIN="$tmp/kb" HOOK_TEST_LOG="$log" EOS_KB_ROOT="$tmp/work-kb" \
  EOS_WORK_KNOWLEDGE_ROOT="$tmp/work-kb" EOS_PERSONAL_KNOWLEDGE_DIR="$tmp/kb-root" \
  EOS_AGENT_PROFILE=work EOS_AGENT_SESSION_ID=s1 "$HOOK" SessionStart)"
grep -q 'pending work KB proposal' <<<"$work_start"
grep -q 'projects/nova/_pending-kb-updates.md' <<<"$work_start"
! grep -q 'projects/eos/_pending-kb-updates.md' <<<"$work_start"
event UserPromptSubmit '{"hook_event_name":"UserPromptSubmit","prompt":"fix this regression"}' | grep -q 'kb bug start'
event UserPromptSubmit '{"hook_event_name":"UserPromptSubmit","prompt":"lets discuss evaluation strategy"}' | grep -q 'Branching discussion detected'
event UserPromptSubmit '{"hook_event_name":"UserPromptSubmit","prompt":"lets discuss a plan for this regression"}' | grep -q 'branching-discussion/SKILL.md and bug-investigation/SKILL.md'
blocked="$(event PreToolUse '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"git commit -m x --trailer Co-authored-by: agent"}}')"
grep -q '"decision": "block"' <<<"$blocked"
event PreToolUse '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"git show | grep attribution"}}' | grep -q '"continue":true'
session_block="$(event PreToolUse '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"git commit -m x session_url=https://example.com/s/1"}}')"
grep -q '"decision": "block"' <<<"$session_block"
attribution_commit="$(event PreToolUse '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"git commit -m fix attribution trailer"}}')"
grep -q '"decision": "block"' <<<"$attribution_commit"
agy_allow="$(event PreToolUse "{\"hookEventName\":\"PreToolUse\",\"cwd\":\"$tmp\",\"toolCall\":{\"name\":\"exec\",\"args\":{\"CommandLine\":\"git show | grep attribution\"}}}")"
grep -q '"decision": "allow"' <<<"$agy_allow"
agy_deny="$(event PreToolUse "{\"hookEventName\":\"PreToolUse\",\"cwd\":\"$tmp\",\"toolCall\":{\"name\":\"exec\",\"args\":{\"CommandLine\":\"git commit -m x session_url=https://example.com/s/1\"}}}")"
grep -q '"decision": "deny"' <<<"$agy_deny"
event PreToolUse '{"hook_event_name":"PreToolUse","turn_id":"t1","tool_name":"Bash","tool_input":{"command":"git show | grep attribution"}}' | grep -q '"continue":true'
codex_session_block="$(event PreToolUse '{"hook_event_name":"PreToolUse","turn_id":"t1","tool_name":"Bash","tool_input":{"command":"git commit -m x session_url=https://example.com/s/1"}}')"
grep -q '"decision": "block"' <<<"$codex_session_block"
kb_write="$(event PreToolUse "{\"hook_event_name\":\"PreToolUse\",\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$tmp/kb-root/projects/eos/stable.md\"}}")"
grep -q '"decision": "block"' <<<"$kb_write"
event PreToolUse "{\"hook_event_name\":\"PreToolUse\",\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$tmp/kb-root/projects/eos/_pending-kb-updates.md\"}}" | grep -q '"continue":true'
event PreToolUse "{\"hook_event_name\":\"PreToolUse\",\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$tmp/kb-root/logs/session.md\"}}" | grep -q '"continue":true'
event PreToolUse "{\"hook_event_name\":\"PreToolUse\",\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$tmp/kb-root/logs/2026/08/nested/session.md\"}}" | grep -q '"continue":true'
deep_write="$(event PreToolUse "{\"hook_event_name\":\"PreToolUse\",\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$tmp/kb-root/projects/eos/deep/stable.md\"}}")"
grep -q '"decision": "block"' <<<"$deep_write"
event PostToolUse '{"hook_event_name":"PostToolUse","tool_name":"Bash","tool_input":{"command":"git status"}}' | grep -q '"continue":true'
event PreCompact '{"hook_event_name":"PreCompact"}' | grep -q '"continue":true'
event PostCompact '{"hook_event_name":"PostCompact"}' | grep -q 'Every discussion uses the global interaction contract'
event Stop '{"hook_event_name":"Stop","stop_hook_active":false}' | grep -q '"continue":true'
invalid_response="$(event Stop '{"hook_event_name":"Stop","last_assistant_message":"bad \u2014 response"}')"
grep -q '"decision": "block"' <<<"$invalid_response"
urdu_response="$(event Stop '{"hook_event_name":"Stop","last_assistant_message":"yeh \u067e\u0648\u0631\u0627 galat hai"}')"
grep -q '"decision": "block"' <<<"$urdu_response"
devanagari_response="$(event Stop '{"hook_event_name":"Stop","last_assistant_message":"yeh \u091c\u093e\u0928\u0947 galat hai"}')"
grep -q '"decision": "block"' <<<"$devanagari_response"
cat > "$tmp/kb-fail" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == *"checkpoint"* ]]; then
  printf '%s\n' '{"command":"checkpoint","exit_code":5,"message":"freshness audit blocked lifecycle: concept X is stale","status":"validation_failure"}' >&2
  exit 5
fi
printf '%s\n' '{"status":"ok"}'
EOF
chmod +x "$tmp/kb-fail"
fail_stop="$(printf '%s' '{"hook_event_name":"Stop","stop_hook_active":false}' | EOS_KB_BIN="$tmp/kb-fail" HOOK_TEST_LOG="$log" EOS_KB_ROOT="$tmp/kb-root" EOS_PERSONAL_KNOWLEDGE_DIR="$tmp/kb-root" EOS_AGENT_SESSION_ID=s1 "$HOOK" Stop)"
grep -q '"decision": "block"' <<<"$fail_stop"
grep -q 'Checkpoint is required before completion' <<<"$fail_stop"
grep -q 'freshness audit blocked lifecycle: concept X is stale' <<<"$fail_stop"
cat > "$tmp/kb-fail-empty" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == *"checkpoint"* ]]; then
  exit 5
fi
printf '%s\n' '{"status":"ok"}'
EOF
chmod +x "$tmp/kb-fail-empty"
empty_stop="$(printf '%s' '{"hook_event_name":"Stop","stop_hook_active":false}' | EOS_KB_BIN="$tmp/kb-fail-empty" HOOK_TEST_LOG="$log" EOS_KB_ROOT="$tmp/kb-root" EOS_PERSONAL_KNOWLEDGE_DIR="$tmp/kb-root" EOS_AGENT_SESSION_ID=s1 "$HOOK" Stop)"
grep -q 'Checkpoint is required before completion' <<<"$empty_stop"
! grep -q 'Detail:' <<<"$empty_stop"

# Claude hook output contract: Claude Code reads only documented output
# fields. Context must arrive as hookSpecificOutput.additionalContext on
# SessionStart (every source, including clear and compact, with an empty
# queue) and UserPromptSubmit; other events use systemMessage. An unknown key
# such as "message" is silently dropped, so it must never be emitted.
cat >"$tmp/claude_json.py" <<'PY'
import json, sys
mode, ev, needle = sys.argv[1], sys.argv[2], sys.argv[3]
out = json.loads(sys.stdin.read())
assert "message" not in out, out
if mode == "context":
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == ev, out
    assert needle in hso["additionalContext"], out
else:
    assert needle in out["systemMessage"], out
    assert "hookSpecificOutput" not in out, out
PY
claude_json() { python3 "$tmp/claude_json.py" "$@"; }
empty_kb="$tmp/empty-kb"
mkdir -p "$empty_kb"
for source in startup resume clear compact; do
  printf '%s' "{\"hook_event_name\":\"SessionStart\",\"source\":\"$source\",\"session_id\":\"c1\",\"transcript_path\":\"$tmp/t.jsonl\",\"cwd\":\"$tmp\"}" | \
    EOS_KB_BIN="$tmp/kb" HOOK_TEST_LOG="$log" EOS_KB_ROOT="$empty_kb" EOS_AGENT_PROFILE=work \
    EOS_WORK_KNOWLEDGE_ROOT="$empty_kb" EOS_AGENT_SESSION_ID=s1 "$HOOK" SessionStart | \
    claude_json context SessionStart 'Every discussion uses the global interaction contract'
done
event SessionStart '{"hook_event_name":"SessionStart","source":"clear"}' | \
  claude_json context SessionStart 'pending personal KB proposal'
event UserPromptSubmit '{"hook_event_name":"UserPromptSubmit","prompt":"fix this regression"}' | \
  claude_json context UserPromptSubmit 'kb bug start'
event UserPromptSubmit '{"hook_event_name":"UserPromptSubmit","prompt":"lets discuss evaluation strategy"}' | \
  claude_json context UserPromptSubmit 'Branching discussion detected'
event PostCompact '{"hook_event_name":"PostCompact","trigger":"manual"}' | \
  claude_json system PostCompact 'Every discussion uses the global interaction contract'

# Antigravity hook contract tests
agy_transcript="$tmp/agy-transcript.jsonl"
printf '%s\n' \
  '{"step_index":0,"type":"USER_INPUT","content":"explain batch norm"}' \
  '{"step_index":1,"type":"PLANNER_RESPONSE","content":"yeh \u091c\u093e\u0928\u0947 aur \u067e\u0648\u0631\u0627 galat hai"}' \
  >"$agy_transcript"
agy_stop_bad="$(event Stop "{\"hookEventName\":\"Stop\",\"cwd\":\"$tmp\",\"transcriptPath\":\"$agy_transcript\"}")"
grep -q '"decision": "continue"' <<<"$agy_stop_bad"

printf '%s\n' \
  '{"step_index":0,"type":"USER_INPUT","content":"explain batch norm"}' \
  '{"step_index":1,"type":"PLANNER_RESPONSE","content":"Clean Hinglish response with plain - dash."}' \
  >"$agy_transcript"
agy_stop_ok="$(event Stop "{\"hookEventName\":\"Stop\",\"cwd\":\"$tmp\",\"transcriptPath\":\"$agy_transcript\"}")"
grep -q '"decision": "allow"' <<<"$agy_stop_ok"

agy_kb_block="$(event PreToolUse "{\"hookEventName\":\"PreToolUse\",\"cwd\":\"$tmp\",\"toolCall\":{\"name\":\"write_file\",\"args\":{\"Path\":\"$tmp/kb-root/projects/eos/stable.md\"}}}")"
grep -q '"decision": "deny"' <<<"$agy_kb_block"
agy_kb_allow="$(event PreToolUse "{\"hookEventName\":\"PreToolUse\",\"cwd\":\"$tmp\",\"toolCall\":{\"name\":\"edit_file\",\"args\":{\"Path\":\"$tmp/kb-root/projects/eos/_pending-kb-updates.md\"}}}")"
grep -q '"decision": "allow"' <<<"$agy_kb_allow"
agy_pre_inv="$(event PreInvocation '{"hookEventName":"PreInvocation","lastUserInput":"lets discuss evaluation strategy"}')"
grep -q '"injectSteps"' <<<"$agy_pre_inv"

# Codex hook contract tests
codex_stop_bad="$(event Stop '{"hook_event_name":"Stop","turn_id":"t1","last_assistant_message":"bad \u067e\u0648\u0631\u0627 response"}')"
grep -q '"decision": "block"' <<<"$codex_stop_bad"
! grep -q '"continue": false' <<<"$codex_stop_bad"
codex_kb_block="$(event PreToolUse "{\"hook_event_name\":\"PreToolUse\",\"turn_id\":\"t1\",\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$tmp/kb-root/projects/eos/stable.md\"}}")"
grep -q '"decision": "block"' <<<"$codex_kb_block"
! grep -q '"continue": false' <<<"$codex_kb_block"
codex_post_compact="$(event PostCompact '{"hook_event_name":"PostCompact","turn_id":"t1","trigger":"auto"}')"
grep -q '"systemMessage"' <<<"$codex_post_compact"
! grep -q '"message"' <<<"$codex_post_compact"

event SessionEnd '{"hook_event_name":"SessionEnd"}' | grep -q '"continue":true'

before_starts="$(grep -c '^session start ' "$log" || true)"
printf '%s' '{"hook_event_name":"Stop","session_id":"direct-claude"}' | \
  EOS_KB_BIN="$tmp/kb" HOOK_TEST_LOG="$log" "$HOOK" Stop | grep -q '"continue":true'
after_starts="$(grep -c '^session start ' "$log" || true)"
[[ "$before_starts" == "$after_starts" ]]

grep -q 'audit' "$log"

install_home="$tmp/install-home"
mkdir -p "$install_home"/.claude "$install_home"/.claude-work "$install_home"/.claude-personal "$install_home"/.codex "$install_home"/.codex-work "$install_home"/.codex-personal "$install_home"/.gemini
printf '%s\n' '{"auth":"keep","hooks":{"Custom":[]}}' > "$install_home/.claude/settings.json"
HOME="$install_home" EOS_ROOT="$ROOT" "$ROOT/scripts/install-agent-instructions" >/dev/null
first="$(cat "$install_home/.claude/settings.json")"
HOME="$install_home" EOS_ROOT="$ROOT" "$ROOT/scripts/install-agent-instructions" >/dev/null
[[ "$first" == "$(cat "$install_home/.claude/settings.json")" ]]
python3 - "$install_home" <<'PY'
import json, pathlib, sys
home = pathlib.Path(sys.argv[1])
settings = json.loads((home / ".claude/settings.json").read_text())
assert settings["auth"] == "keep"
assert settings["attribution"] == {"commit": "", "pr": "", "sessionUrl": False}
assert all(event in settings["hooks"] for event in ("InstructionsLoaded", "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PreCompact", "PostCompact", "Stop", "SessionEnd"))
assert any("scripts/eos-kb-capture" in hook["command"] for entry in settings["hooks"]["PreCompact"] for hook in entry["hooks"])
assert any("scripts/eos-kb-capture" in hook["command"] for entry in settings["hooks"]["SessionEnd"] for hook in entry["hooks"])
agy_hooks = json.loads((home / ".gemini/config/hooks.json").read_text())
assert "eos" in agy_hooks
assert all(event in agy_hooks["eos"] for event in ("SessionStart", "PreInvocation", "PreToolUse", "PostToolUse", "Stop"))
for codex_profile in (".codex", ".codex-work", ".codex-personal"):
    codex_hooks = json.loads((home / codex_profile / "hooks.json").read_text())
    assert all(event in codex_hooks["hooks"] for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PreCompact", "PostCompact", "Stop", "SessionEnd"))
    assert "InstructionsLoaded" not in codex_hooks["hooks"]
for relative in (
    ".gemini/skills/knowledge-management",
    ".gemini/antigravity-ide/skills/bug-investigation",
    ".config/antigravity/skills/knowledge-management",
    ".config/agy/skills/bug-investigation",
    ".antigravity/skills/knowledge-management",
):
    skill = home / relative
    assert skill.is_symlink(), relative
    assert (skill / "SKILL.md").is_file(), relative
PY
echo "claude hooks ok"
