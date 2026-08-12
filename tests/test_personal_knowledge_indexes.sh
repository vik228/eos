#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
installer="$ROOT/scripts/install-personal-knowledge-indexes"
profile="$ROOT/knowledge/areas/agent-profile.md"

for file in "$ROOT/personal-knowledge/00-index.md" "$ROOT/personal-knowledge/_pending-kb-updates.md" "$profile" "$installer"; do
  [[ -f "$file" ]] || { echo "missing file: $file"; exit 1; }
done

grep -q 'areas/agent-profile.md' "$ROOT/personal-knowledge/00-index.md"
grep -q 'areas/agent-profile.md' "$installer"
grep -q 'first-principles reasoning' "$profile"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
EOS_ROOT="$ROOT" EOS_PERSONAL_KNOWLEDGE_DIR="$tmp/knowledge" \
  EOS_PERSONAL_KNOWLEDGE_BACKUP_DIR="$tmp/backups" "$installer" >/dev/null

for file in 00-index.md _pending-kb-updates.md areas/agent-profile.md projects/eos/00-index.md projects/eos/_pending-kb-updates.md; do
  [[ -f "$tmp/knowledge/$file" ]] || { echo "installer did not create: $file"; exit 1; }
done

echo "personal knowledge indexes ok"
