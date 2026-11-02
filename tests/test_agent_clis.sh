#!/usr/bin/env bash
set -euo pipefail

ROOT="${EOS_ROOT:-$HOME/personal/eos}"

[[ -x "$ROOT/bin/claude" ]] || { echo "missing executable shim: $ROOT/bin/claude"; exit 1; }
[[ -x "$ROOT/scripts/install-agent-clis" ]] || { echo "missing executable script: $ROOT/scripts/install-agent-clis"; exit 1; }

bash -n "$ROOT/bin/claude"
bash -n "$ROOT/scripts/install-agent-clis"

grep -q "version_gt" "$ROOT/bin/claude"
grep -q ".nvm/versions/node" "$ROOT/bin/claude"
grep -q "sed -nE" "$ROOT/bin/opencode"
grep -Fq '\.[0-9]+' "$ROOT/bin/opencode"

tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/eos-opencode-shim.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT
mkdir -p "$tmpdir/bin"
cat >"$tmpdir/bin/opencode" <<'STUB'
#!/usr/bin/env bash
if [[ "${1:-}" == "--version" ]]; then
  echo "opencode v9.9.9"
else
  printf '%s\n' "$*" >"$EOS_OPENCODE_SHIM_ARGS"
fi
STUB
chmod +x "$tmpdir/bin/opencode"
EOS_OPENCODE_SHIM_ARGS="$tmpdir/args" NVM_BIN="$tmpdir/bin" "$ROOT/bin/opencode" --auto --version >/dev/null
EOS_OPENCODE_SHIM_ARGS="$tmpdir/args" NVM_BIN="$tmpdir/bin" "$ROOT/bin/opencode" --auto .
[[ "$(cat "$tmpdir/args")" == "--auto ." ]] || { echo "OpenCode shim did not pass through to the newest v2 CLI" >&2; exit 1; }

dry_run="$("$ROOT/scripts/install-agent-clis" --dry-run)"
[[ "$dry_run" == *"npm uninstall -g opencode-ai"* ]]
[[ "$dry_run" == *"npm install -g --force --include=optional @anthropic-ai/claude-code@latest @openai/codex@latest @google/gemini-cli@latest @anthropic-ai/claude-code-darwin-arm64@latest"* ]]
[[ "$dry_run" == *"npm install -g --include=optional @opencode/cli@latest"* ]]
[[ "$dry_run" == *"npm install -g --force --include=optional <codex-native-alias-from-package-json>"* ]]
[[ "$dry_run" == *'node $(npm root -g)/@anthropic-ai/claude-code/install.cjs'* ]]
[[ "$dry_run" == *"agy update"* ]]

grep -q 'EOS_ROOT/scripts:$EOS_ROOT/bin' "$ROOT/configs/shell/zshrc"
grep -q 'install-agent-clis' "$ROOT/bootstrap/bootstrap.sh"

echo "agent CLI updater ok"
