#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
matrix="$ROOT/configs/agents/adherence-matrix.yaml"
fixture="$ROOT/tests/fixtures/agent-adherence/trials.tsv"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

profiles=(claude-default claude-work claude-personal codex-default codex-work codex-personal gemini-cli antigravity-cli antigravity-ide opencode-default opencode-work opencode-personal)
declare -A wrappers=(
  [claude-default]="$ROOT/scripts/claude-default"
  [claude-work]="$ROOT/scripts/claude-work"
  [claude-personal]="$ROOT/scripts/claude-personal"
  [codex-default]="$ROOT/scripts/codex-default"
  [codex-work]="$ROOT/scripts/codex-work"
  [codex-personal]="$ROOT/scripts/codex-personal"
  [gemini-cli]="$ROOT/scripts/gemini-eos"
  [antigravity-cli]="$ROOT/scripts/antigravity-full"
  [antigravity-ide]="$ROOT/scripts/antigravity-full"
  [opencode-default]="$ROOT/scripts/opencode-default"
  [opencode-work]="$ROOT/scripts/opencode-work"
  [opencode-personal]="$ROOT/scripts/opencode-personal"
)

test -s "$matrix"; test -s "$fixture"
while IFS= read -r profile; do
  [[ -n "${wrappers[$profile]-}" ]] || { echo "unsupported required profile: $profile" >&2; exit 1; }
  test -x "${wrappers[$profile]}"
done < <(awk '/^profiles:/{section=1; next} /^rows:/{section=0} section && /^  - /{sub(/^  - /, ""); print}' "$matrix")
mapfile -t rows < <(awk '/^rows:/{section=1; next} section && /^  - /{sub(/^  - /, ""); print}' "$matrix")
[[ "${#rows[@]}" -eq 12 ]] || { echo "matrix must define exactly twelve required rows" >&2; exit 1; }
for row in "${rows[@]}"; do
  awk -F '\t' -v wanted="$row" '$1 == wanted { found=1 } END { exit(found ? 0 : 1) }' "$fixture" || {
    echo "missing deterministic trial fixture for required row: $row" >&2; exit 1;
  }
done

fake_kb="$tmp_dir/fake-kb"; fake_agent="$tmp_dir/fake-agent"; log="$tmp_dir/transports.log"; kb_log="$tmp_dir/kb.log"
cwd="$tmp_dir/workspace"; kb="$tmp_dir/knowledge"
mkdir -p "$cwd" "$kb" "$tmp_dir/home"

cat > "$fake_kb" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${EOS_ADHERENCE_KB_LOG:?}"
case "${1:-}" in
  audit) printf '{"status":"audited","exit_code":0}\n' ;;
  session)
    case "${2:-}" in
      start) printf '{"data":{"session_id":"trial-%s-%s"},"status":"started","exit_code":0}\n' "${EOS_ADHERENCE_PROFILE:?}" "${EOS_ADHERENCE_ROW:?}" ;;
      checkpoint|end) printf '{"status":"ok","exit_code":0}\n' ;;
      *) exit 2 ;;
    esac
    ;;
  *) exit 2 ;;
esac
EOF
cat > "$fake_agent" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\t%s\t%s\t%s\n' "${EOS_ADHERENCE_PROFILE:?}" "${EOS_ADHERENCE_ROW:?}" "${EOS_ADHERENCE_TRANSPORT:?}" "$*" >> "${EOS_ADHERENCE_LOG:?}"
printf 'EOS_TRIAL %s/%s accepted\n' "$EOS_ADHERENCE_PROFILE" "$EOS_ADHERENCE_ROW"
if [[ "$EOS_ADHERENCE_ROW" == bug-reproduction-gate ]]; then
  printf 'HYPOTHESIS bug-candidate-1\n'
fi
EOF
chmod +x "$fake_kb" "$fake_agent"

for profile in "${profiles[@]}"; do
  wrapper="${wrappers[$profile]-}"
  [[ -n "$wrapper" ]] || { echo "unsupported required profile: $profile" >&2; exit 1; }
  for row in "${rows[@]}"; do
    prompt="$(awk -F '\t' -v wanted="$row" '$1 == wanted { print $2; exit }' "$fixture")"
    [[ -n "$prompt" ]] || { echo "empty trial prompt: $row" >&2; exit 1; }
    EOS_ROOT="$ROOT" HOME="$tmp_dir/home" EOS_KB_BIN="$fake_kb" EOS_AGENT_DOCTOR=: \
      EOS_AGENT_BIN="$fake_agent" EOS_ADHERENCE_PROFILE="$profile" EOS_ADHERENCE_ROW="$row" \
      EOS_ADHERENCE_PROMPT="$prompt" EOS_ADHERENCE_TRANSPORT="$wrapper" \
      EOS_ADHERENCE_LOG="$log" EOS_ADHERENCE_KB_LOG="$kb_log" EOS_KB_ROOT="$kb" \
      EOS_DEFAULT_KB_ROOT="$kb" EOS_WORK_KNOWLEDGE_ROOT="$kb" EOS_PERSONAL_KNOWLEDGE_ROOT="$kb" \
      EOS_AGENT_CWD="$cwd" CODEX_WORK_DIR="$cwd" CODEX_PERSONAL_DIR="$cwd" \
      ANTIGRAVITY_ADD_WORK_KB_DIR=0 ANTIGRAVITY_ADD_PERSONAL_KB_DIR=0 \
      "$wrapper" --eos-adherence-prompt "$prompt" >/dev/null
  done
done

expected=$(( ${#profiles[@]} * ${#rows[@]} ))
actual="$(wc -l < "$log" | tr -d ' ')"
[[ "$actual" -eq "$expected" ]] || { echo "transport trial count: expected $expected, got $actual" >&2; exit 1; }
for profile in "${profiles[@]}"; do
  for row in "${rows[@]}"; do
    grep -Fq "$profile"$'\t'"$row"$'\t' "$log" || {
      echo "missing transport evidence for $profile/$row" >&2; exit 1;
    }
  done
done
grep -Fq 'session start' "$kb_log"
grep -Fq 'session checkpoint' "$kb_log"
grep -Fq 'session end' "$kb_log"
grep -Fq 'audit' "$kb_log"
grep -Rqi -- 'Never use the em dash' "$ROOT/configs/agents"
grep -Rqi -- 'Never write in Hindi' "$ROOT/configs/agents"
grep -Rqi -- 'Always use simple, direct language' "$ROOT/configs/agents"
grep -Rqi -- 'reading its `SKILL.md` completely and following it is mandatory' "$ROOT/configs/agents"
grep -Rqi -- 'Trigger `branching-discussion` before the first question' "$ROOT/configs/agents"
grep -Rqi -- 'co-author' "$ROOT/configs/agents"
grep -q -- '--ask-for-approval never' "$ROOT/scripts/codex-default" "$ROOT/scripts/codex-work" "$ROOT/scripts/codex-personal"
grep -q -- 'append-system-prompt-file' "$ROOT/scripts/claude-default" "$ROOT/scripts/claude-work" "$ROOT/scripts/claude-personal"
for skill in branching-discussion bug-investigation knowledge-management; do
  test -s "$ROOT/configs/agents/skills/$skill/SKILL.md"
done

echo "agent policy transport ok: $expected deterministic prompt trials across ${#profiles[@]} profiles and ${#rows[@]} rows"
