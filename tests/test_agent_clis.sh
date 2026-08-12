#!/usr/bin/env bash
set -euo pipefail

ROOT="${EOS_ROOT:-$HOME/personal/eos}"

[[ -x "$ROOT/bin/claude" ]] || { echo "missing executable shim: $ROOT/bin/claude"; exit 1; }
[[ -x "$ROOT/scripts/install-agent-clis" ]] || { echo "missing executable script: $ROOT/scripts/install-agent-clis"; exit 1; }

bash -n "$ROOT/bin/claude"
bash -n "$ROOT/scripts/install-agent-clis"

grep -q "version_gt" "$ROOT/bin/claude"
grep -q ".nvm/versions/node" "$ROOT/bin/claude"

dry_run="$("$ROOT/scripts/install-agent-clis" --dry-run)"
[[ "$dry_run" == *"npm install -g --force --include=optional @anthropic-ai/claude-code@latest @openai/codex@latest @google/gemini-cli@latest @anthropic-ai/claude-code-darwin-arm64@latest"* ]]
[[ "$dry_run" == *"npm install -g --force --include=optional <codex-native-alias-from-package-json>"* ]]
[[ "$dry_run" == *'node $(npm root -g)/@anthropic-ai/claude-code/install.cjs'* ]]
[[ "$dry_run" == *"agy update"* ]]

grep -q 'EOS_ROOT/scripts:$EOS_ROOT/bin' "$ROOT/configs/shell/zshrc"
grep -q 'install-agent-clis' "$ROOT/bootstrap/bootstrap.sh"

echo "agent CLI updater ok"
