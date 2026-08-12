#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
tmp="$(cd "$tmp" && pwd -P)"
trap 'chmod 700 "$tmp/workspace" 2>/dev/null || true; rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/home" "$tmp/workspace" "$tmp/knowledge"

cat > "$tmp/bin/kb" <<'EOF'
#!/usr/bin/env bash
if [[ "$1 $2" == "session start" ]]; then
  printf '%s\n' '{"data":{"session_id":"personal-write-test"}}'
fi
exit 0
EOF

cat > "$tmp/bin/codex" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "CODEX_HOME=${CODEX_HOME:?}" > "${AGENT_LOG:?}"
printf '%s\n' "$@" >> "$AGENT_LOG"
printf 'workspace-write\n' > "${CODEX_PERSONAL_DIR:?}/.codex-write-test"
printf 'kb-write\n' > "${EOS_PERSONAL_KNOWLEDGE_ROOT:?}/.codex-write-test"
EOF
chmod +x "$tmp/bin/kb" "$tmp/bin/codex"

run_codex() {
  HOME="$tmp/home" \
    CODEX_HOME= \
    EOS_ROOT="$ROOT" \
    EOS_AGENT_DOCTOR=: \
    EOS_KB_BIN="$tmp/bin/kb" \
    EOS_AGENT_BIN="$tmp/bin/codex" \
    CODEX_PERSONAL_DIR="$tmp/workspace" \
    EOS_PERSONAL_KNOWLEDGE_ROOT="$tmp/knowledge" \
    AGENT_LOG="$tmp/agent.log" \
    "$ROOT/scripts/codex-personal"
}

run_codex
grep -q '^workspace-write$' "$tmp/workspace/.codex-write-test"
grep -q '^kb-write$' "$tmp/knowledge/.codex-write-test"
grep -q "^CODEX_HOME=$tmp/home/.codex-personal$" "$tmp/agent.log"
grep -qx -- '--cd' "$tmp/agent.log"
grep -qx -- "$tmp/workspace" "$tmp/agent.log"
grep -qx -- '--add-dir' "$tmp/agent.log"
grep -qx -- "$tmp/knowledge" "$tmp/agent.log"
grep -qx -- '--sandbox' "$tmp/agent.log"
grep -qx -- 'danger-full-access' "$tmp/agent.log"
grep -q -- 'sandbox_workspace_write.network_access=true' "$tmp/agent.log"
grep -qx -- '--ask-for-approval' "$tmp/agent.log"
grep -qx -- 'never' "$tmp/agent.log"

rm -f "$tmp/agent.log"
chmod 500 "$tmp/workspace"
if run_codex >/dev/null 2>&1; then
  echo "codex-personal launched with a non-writable workspace" >&2
  exit 1
fi
[[ ! -e "$tmp/agent.log" ]] || {
  echo "codex agent was invoked after workspace preflight failed" >&2
  exit 1
}
chmod 700 "$tmp/workspace"

chmod 500 "$tmp/knowledge"
if run_codex >/dev/null 2>&1; then
  echo "codex-personal launched with a non-writable KB" >&2
  exit 1
fi
[[ ! -e "$tmp/agent.log" ]]
chmod 700 "$tmp/knowledge"

mv "$tmp/workspace" "$tmp/workspace-missing"
if run_codex >/dev/null 2>&1; then
  echo "codex-personal launched with a missing workspace" >&2
  exit 1
fi
[[ ! -e "$tmp/agent.log" ]]
mv "$tmp/workspace-missing" "$tmp/workspace"

mv "$tmp/knowledge" "$tmp/knowledge-missing"
if run_codex >/dev/null 2>&1; then
  echo "codex-personal launched with a missing KB" >&2
  exit 1
fi
[[ ! -e "$tmp/agent.log" ]]
mv "$tmp/knowledge-missing" "$tmp/knowledge"

echo "codex personal writes ok"
