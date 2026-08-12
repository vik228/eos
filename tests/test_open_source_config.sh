#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f "$ROOT/eos.local.example" ]]
[[ -f "$ROOT/LICENSE" ]]
grep -q '^MIT License$' "$ROOT/LICENSE"
grep -q '^\.eos\.local$' "$ROOT/.gitignore"
[[ -f "$ROOT/scripts/lib-eos-config.sh" ]]
[[ -f "$ROOT/scripts/render-local-config" ]]

scan_files=()
while IFS= read -r file; do
  [[ -f "$ROOT/$file" ]] && scan_files+=("$ROOT/$file")
done < <(git -C "$ROOT" ls-files --cached --others --exclude-standard)
private_pattern="/Users/"'vikaspandey|vikas\.pandey@'"gocomet"'\.com|vik\.iiitmg@'"gmail"'\.com|Go'"Comet"'|Go'"Nimbus"'|Uni'"lever"
if rg -n "$private_pattern" "${scan_files[@]}"; then
  echo "private identity or organization data remains in tracked files"
  exit 1
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
env -i HOME="$tmp/home" PATH="$PATH" EOS_ROOT="$ROOT" EOS_CONFIG_FILE="$tmp/missing" EOS_GENERATED_DIR="$tmp/generated" \
  "$ROOT/scripts/render-local-config" >/dev/null
grep -q 'you@company.example' "$tmp/generated/git/gitconfig-work"
grep -q 'you@example.com' "$tmp/generated/git/gitconfig-personal"
! rg -q 'Vikas|backend-project|research-project' "$tmp/generated"

echo "open source config ok"
