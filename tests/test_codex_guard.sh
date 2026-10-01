#!/usr/bin/env bash
# Plain `codex` must refuse to run for a work directory unless it uses the work
# account home; codex-work and personal directories still pass through.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
tmp="$(cd "$tmp" && pwd -P)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/home/work/repo" "$tmp/home/personal/repo" "$tmp/home/.codex" "$tmp/home/.codex-work" "$tmp/real"

cat > "$tmp/real/codex" <<'STUB'
#!/usr/bin/env bash
printf 'real codex CODEX_HOME=%s args=%s\n' "${CODEX_HOME:-unset}" "$*"
STUB
chmod +x "$tmp/real/codex"

guard() {
  local dir="$1"; shift
  (cd "$dir" && env -u CODEX_HOME -u EOS_ALLOW_PERSONAL_AGENT_IN_WORK -u EOS_WORK_ROOT -u EOS_CODEX_WORK_HOME \
    HOME="$tmp/home" PATH="$ROOT/bin/guards:$tmp/real:/usr/bin:/bin" "$@")
}

fail() { echo "FAIL: $*" >&2; exit 1; }

# 1. plain codex in a work directory is refused.
if out="$(guard "$tmp/home/work/repo" codex exec hi 2>&1)"; then fail "plain codex in work ran: $out"; fi
[[ "$out" == *"must use codex-work"* ]] || fail "missing refusal message: $out"

# 2. plain codex outside work, but --cd pointing into work, is refused.
if out="$(guard "$tmp/home/personal/repo" codex --cd "$tmp/home/work/repo" exec hi 2>&1)"; then fail "--cd into work ran: $out"; fi
if out="$(guard "$tmp/home/personal/repo" codex -C "$tmp/home/work/repo" exec hi 2>&1)"; then fail "-C into work ran: $out"; fi
if out="$(guard "$tmp/home/personal/repo" codex --cd="$tmp/home/work/repo" exec hi 2>&1)"; then fail "--cd= into work ran: $out"; fi

# 3. the personal default home pointed at work is refused too.
if out="$(guard "$tmp/home/work/repo" env CODEX_HOME="$tmp/home/.codex" codex exec hi 2>&1)"; then fail "personal home in work ran: $out"; fi

# 4. the work home passes through to the real binary with arguments intact.
out="$(guard "$tmp/home/work/repo" env CODEX_HOME="$tmp/home/.codex-work" codex exec hi)"
[[ "$out" == "real codex CODEX_HOME=$tmp/home/.codex-work args=exec hi" ]] || fail "work home not passed through: $out"

# 5. personal directories are untouched.
out="$(guard "$tmp/home/personal/repo" codex exec hi)"
[[ "$out" == "real codex CODEX_HOME=unset args=exec hi" ]] || fail "personal dir blocked: $out"

# 6. the explicit override lets a deliberate personal launch through.
out="$(guard "$tmp/home/work/repo" env EOS_ALLOW_PERSONAL_AGENT_IN_WORK=1 codex exec hi)"
[[ "$out" == "real codex CODEX_HOME=unset args=exec hi" ]] || fail "override did not pass: $out"

# 7. codex-work goes through the guard and is allowed.
cat > "$tmp/real/kb" <<'STUB'
#!/usr/bin/env bash
[[ "$1 $2" == "session start" ]] && printf '%s\n' '{"data":{"session_id":"guard-test"}}'
exit 0
STUB
chmod +x "$tmp/real/kb"
mkdir -p "$tmp/home/work/knowledge"
out="$(guard "$tmp/home/work/repo" env EOS_ROOT="$ROOT" EOS_AGENT_DOCTOR=: EOS_KB_BIN="$tmp/real/kb" \
  EOS_WORK_KNOWLEDGE_ROOT="$tmp/home/work/knowledge" "$ROOT/scripts/codex-work" exec hi)"
[[ "$out" == *"real codex CODEX_HOME=$tmp/home/.codex-work"* ]] || fail "codex-work blocked: $out"

echo "codex guard tests passed"
