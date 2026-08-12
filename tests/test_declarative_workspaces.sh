#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
profile_root="$tmp/profiles"
project="$tmp/project"
mkdir -p "$profile_root/custom/workspaces" "$project"

cat >"$profile_root/custom/workspaces/backend.yaml" <<'YAML'
extends: backend
session: custom-backend
directory: $EOS_TEST_PROJECT
windows:
  - { name: editor, command: 'nvim "$EOS_TEST_PROJECT"' }
  - { name: database, command: pgcli }
  - { name: shell, command: zsh }
YAML

common=(EOS_ROOT="$ROOT" EOS_CONFIG_FILE="$tmp/missing" EOS_PROFILE_ROOT="$profile_root" EOS_PROFILE=custom EOS_TEST_PROJECT="$project")
env "${common[@]}" "$ROOT/scripts/eos-workspace" backend --validate | grep -q 'workspace valid'
preview="$(env "${common[@]}" "$ROOT/scripts/eos-workspace" backend --preview)"
[[ "$preview" == *"session=custom-backend"* ]]
[[ "$preview" == *"directory=$project"* ]]
[[ "$preview" == *"window=database:pgcli"* ]]
[[ "$preview" != *"window=claude:"* ]]

cat >"$profile_root/custom/workspaces/broken.yaml" <<'YAML'
schema_version: 1
session: broken
directory: $EOS_TEST_PROJECT
mode: tmux
windows:
  - { name: shell, command: zsh }
  - { name: shell, command: bash }
YAML
if env "${common[@]}" "$ROOT/scripts/eos-workspace" broken --validate >/dev/null 2>&1; then
  echo "duplicate windows should fail validation"
  exit 1
fi

echo "declarative workspaces ok"
