#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/home/personal/eos" "$tmp/bin"
ln -s "$ROOT/configs" "$tmp/home/personal/eos/configs"
ln -s "$ROOT/scripts" "$tmp/home/personal/eos/scripts"
cat > "$tmp/bin/kb" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$EOS_TEST_LOG"
[[ "$*" != *"work/knowledge"* || "${EOS_FAIL_WORK:-0}" != "1" ]]
SH
chmod +x "$tmp/bin/kb"
export HOME="$tmp/home" EOS_ROOT="$tmp/home/personal/eos" EOS_KB_COMMAND="$tmp/bin/kb" EOS_TEST_LOG="$tmp/audits.log" EOS_SKIP_LAUNCHCTL=1
"$ROOT/scripts/install-kb-audit"
plist="$HOME/Library/LaunchAgents/com.vikas.eos-kb-audit.plist"
plutil -lint "$plist" >/dev/null
grep -q '<integer>21600</integer>' "$plist"
"$ROOT/scripts/kb-audit-all"
grep -q 'audit --kb.*/work/knowledge' "$EOS_TEST_LOG"
grep -q 'audit --kb.*/personal/knowledge' "$EOS_TEST_LOG"
: > "$EOS_TEST_LOG"
if EOS_FAIL_WORK=1 "$ROOT/scripts/kb-audit-all"; then
  echo "expected combined audit failure" >&2
  exit 1
fi
[[ "$(wc -l < "$EOS_TEST_LOG" | tr -d ' ')" == "2" ]]
