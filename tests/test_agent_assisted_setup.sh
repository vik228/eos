#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/home" "$tmp/bin"

cat >"$tmp/bin/codex" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "$tmp/bin/codex"

output="$(env -i HOME="$tmp/home" PATH="$tmp/bin:$PATH" EOS_ROOT="$ROOT" EOS_CONFIG_FILE="$tmp/local" EOS_SETUP_LOCAL_CONFIG="$tmp/local" EOS_SETUP_AGENT=codex EOS_SETUP_DRY_RUN=1 "$ROOT/scripts/eos-setup")"
[[ -f "$tmp/local" ]]
[[ "$output" == *"agent=codex"* ]]
[[ "$output" == *'$branching-discussion'* ]]
[[ "$output" == *'$configure-eos-workspace'* ]]
[[ "$output" == *"one exploratory question at a time"* ]]
[[ "$output" == *"explicit approval before applying"* ]]
[[ -f "$tmp/home/work/knowledge/00-index.md" ]]
[[ -f "$tmp/home/personal/knowledge/00-index.md" ]]
[[ -L "$tmp/home/.codex-personal/skills/configure-eos-workspace" ]]
[[ -f "$tmp/home/.codex-personal/skills/configure-eos-workspace/references/workspace-schema.md" ]]
[[ -L "$tmp/home/.codex-personal/skills/branching-discussion" ]]

echo "agent-assisted setup ok"
