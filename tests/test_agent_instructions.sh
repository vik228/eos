#!/usr/bin/env bash
set -euo pipefail

ROOT="${EOS_ROOT:-$HOME/personal/eos}"
agent_dir="$ROOT/configs/agents"
profile="$ROOT/knowledge/areas/agent-profile.md"

for file in "$agent_dir/common-knowledge.md" "$agent_dir/AGENTS.md" "$agent_dir/CLAUDE.md" "$agent_dir/GEMINI.md" "$profile"; do
  [[ -f "$file" ]] || { echo "missing file: $file"; exit 1; }
done

for file in "$agent_dir/AGENTS.md" "$agent_dir/CLAUDE.md" "$agent_dir/GEMINI.md"; do
  grep -q 'Never use the em dash' "$file"
  grep -q 'Preferred language is English or natural English-dominant Hinglish' "$file"
  grep -q 'shared knowledge bases' "$file"
  grep -q 'proposal, review, and promotion lifecycle' "$file"
  grep -q 'branching-discussion' "$file"
done

grep -q 'first-principles reasoning' "$profile"
grep -q 'one question at a time' "$profile"
grep -q 'EOS_RENDER_OUTPUT_DIR' "$ROOT/scripts/render-agent-instructions"
grep -q 'EOS_LOCAL_AGENT_CONTEXT' "$ROOT/scripts/render-agent-instructions"

echo "agent instructions ok"
