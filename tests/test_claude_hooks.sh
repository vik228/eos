#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
