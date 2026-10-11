#!/usr/bin/env bash
# Codex session-end capture: the wrapper selects the owning rollout for its
# cwd and captures it into the pending KB, the Claude SessionEnd equivalent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/lib-agent-session.sh"

tmp="$(mktemp -d)"
tmp="$(cd "$tmp" && pwd -P)"
trap 'rm -rf "$tmp"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

codex_home="$tmp/codex-home"
sessions="$codex_home/sessions/2026/01/02"
mkdir -p "$sessions"
work_repo="$tmp/work-repo"
other_repo="$tmp/other-repo"
mkdir -p "$work_repo" "$other_repo"

write_rollout() {
  local file="$1" cwd="$2" sid="$3" ts="$4" stamp="$5" text="$6"
  cat >"$file" <<JSONL
{"type":"session_meta","payload":{"cwd":"$cwd","session_id":"$sid","timestamp":"$ts"}}
{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"$text"}]}}
JSONL
  touch -t "$stamp" "$file"
}

write_rollout "$sessions/rollout-2026-01-01-a.jsonl" "$work_repo" "sid-a" "2026-01-01T00:00:00Z" "202601100000" "first session"
write_rollout "$sessions/rollout-2026-02-01-b.jsonl" "$work_repo" "sid-b" "2026-02-01T00:00:00Z" "202602100000" "second session"
write_rollout "$sessions/rollout-2026-03-01-other.jsonl" "$other_repo" "sid-other" "2026-03-01T00:00:00Z" "202603100000" "other repo"
marker_early="$tmp/marker-early"
marker_mid="$tmp/marker-mid"
touch -t "201901010000" "$marker_early"
touch -t "202601150000" "$marker_mid"

# 1. concurrent sessions in one cwd resolve to their own rollout: the oldest
# session started at or after the marker.
selected="$(codex_latest_transcript "$codex_home" "$marker_early" "$work_repo")"
[[ "$selected" == "$sessions/rollout-2026-01-01-a.jsonl" ]] || fail "wrong transcript for early marker: $selected"
selected="$(codex_latest_transcript "$codex_home" "$marker_mid" "$work_repo")"
[[ "$selected" == "$sessions/rollout-2026-02-01-b.jsonl" ]] || fail "wrong transcript for mid marker: $selected"

# 2. overlap: an older session still writing after the marker must not win.
# rollout-x started before marker-overlap but has the newest mtime.
write_rollout "$sessions/rollout-2025-12-01-x.jsonl" "$work_repo" "sid-x" "2025-12-01T00:00:00Z" "202603010000" "stale writer"
marker_overlap="$tmp/marker-overlap"
touch -t "202601150000" "$marker_overlap"
selected="$(codex_latest_transcript "$codex_home" "$marker_overlap" "$work_repo")"
[[ "$selected" == "$sessions/rollout-2026-02-01-b.jsonl" ]] || fail "overlap picked stale session: $selected"

# 3. resume runs take the newest file written after the marker.
selected="$(codex_latest_transcript "$codex_home" "$marker_mid" "$work_repo" 1)"
[[ "$selected" == "$sessions/rollout-2025-12-01-x.jsonl" ]] || fail "resume picked wrong file: $selected"

# 4. nothing started after a fresh marker.
fresh_marker="$tmp/fresh-marker"
touch -t "202701010000" "$fresh_marker"
[[ -z "$(codex_latest_transcript "$codex_home" "$fresh_marker" "$work_repo")" ]] || fail "expected empty for fresh marker"

# 5. cwd mismatch selects nothing.
[[ -z "$(codex_latest_transcript "$codex_home" "$marker_early" "$tmp/elsewhere")" ]] || fail "expected empty for cwd mismatch"

# 6. missing sessions dir or marker selects nothing.
[[ -z "$(codex_latest_transcript "$tmp/nope" "$marker_early" "$work_repo")" ]] || fail "expected empty for missing sessions"
[[ -z "$(codex_latest_transcript "$codex_home" "$tmp/no-marker" "$work_repo")" ]] || fail "expected empty for missing marker"

# 7. helper launches the capture detached: DRY_RUN output lands in the log.
kb="$tmp/knowledge"
mkdir -p "$kb/logs"
capture_log="$tmp/capture.log"
EOS_ROOT="$ROOT" DRY_RUN=1 EOS_CODEX_CAPTURE_LOG="$capture_log" \
  EOS_CAPTURE_WORKSPACE_ROOT="$tmp" \
  codex_session_capture "$codex_home" "$marker_mid" "$work_repo" "$kb" "work"
found=0
for _ in $(seq 1 50); do
  if grep -q "would run: agent=codex profile=work" "$capture_log" 2>/dev/null \
    && grep -q "rollout-2026-02-01-b.jsonl" "$capture_log" 2>/dev/null \
    && grep -q "$kb" "$capture_log" 2>/dev/null; then
    found=1
    break
  fi
  sleep 0.1
done
[[ "$found" == 1 ]] || fail "detached capture did not run: $(cat "$capture_log" 2>/dev/null)"

# 8. dry-run wrappers never capture, even with a qualifying future transcript.
mkdir -p "$tmp/future-home/sessions/2026/01/02"
write_rollout "$tmp/future-home/sessions/2026/01/02/rollout-2030-05-05.jsonl" "$work_repo" "sid-future" "2030-05-05T00:00:00Z" "203001010000" "future work"
dry_log="$tmp/dry-run-capture.log"
env -u EOS_KB_ROOT -u EOS_CAPTURE_KB_ROOT -u EOS_BACKEND_DIR -u EOS_KB_CAPTURE_RUNNING \
  EOS_ROOT="$ROOT" EOS_WORK_KNOWLEDGE_ROOT="$kb" CODEX_HOME="$tmp/future-home" CODEX_WORK_DIR="$work_repo" \
  EOS_CODEX_CAPTURE_LOG="$dry_log" "$ROOT/scripts/codex-work" --dry-run >/dev/null
[[ ! -e "$dry_log" ]] || fail "codex-work --dry-run captured"
env -u EOS_KB_ROOT -u EOS_CAPTURE_KB_ROOT -u EOS_BACKEND_DIR -u EOS_KB_CAPTURE_RUNNING \
  EOS_ROOT="$ROOT" EOS_PERSONAL_KNOWLEDGE_ROOT="$kb" CODEX_HOME="$tmp/future-home" CODEX_PERSONAL_DIR="$work_repo" \
  EOS_CODEX_CAPTURE_LOG="$dry_log" "$ROOT/scripts/codex-personal" --dry-run >/dev/null
[[ ! -e "$dry_log" ]] || fail "codex-personal --dry-run captured"

# 9. a failing session still captures, and its exit code is preserved.
mkdir -p "$tmp/fail-home/sessions/2026/01/02" "$tmp/fail-kb/logs" "$tmp/fail-repo"
write_rollout "$tmp/fail-home/sessions/2026/01/02/rollout-2030-04-01-f.jsonl" "$tmp/fail-repo" "sid-f" "2030-04-01T00:00:00Z" "203001010000" "failed work"
cat >"$tmp/fake-fail" <<'STUB'
#!/usr/bin/env bash
exit 3
STUB
chmod +x "$tmp/fake-fail"
cat >"$tmp/fake-kb" <<'STUB'
#!/usr/bin/env bash
[[ "$1 $2" == "session start" ]] && printf '%s\n' '{"data":{"session_id":"kb-test"}}'
exit 0
STUB
chmod +x "$tmp/fake-kb"
fail_log="$tmp/fail-capture.log"
fail_rc=0
env -u EOS_KB_ROOT -u EOS_CAPTURE_KB_ROOT -u EOS_BACKEND_DIR -u EOS_KB_CAPTURE_RUNNING \
  EOS_ROOT="$ROOT" EOS_WORK_KNOWLEDGE_ROOT="$tmp/fail-kb" CODEX_HOME="$tmp/fail-home" \
  CODEX_WORK_DIR="$tmp/fail-repo" EOS_AGENT_BIN="$tmp/fake-fail" EOS_KB_BIN="$tmp/fake-kb" \
  EOS_AGENT_DOCTOR=: EOS_CAPTURE_WORKSPACE_ROOT="$tmp" \
  DRY_RUN=1 EOS_CODEX_CAPTURE_LOG="$fail_log" \
  "$ROOT/scripts/codex-work" exec hi >/dev/null 2>&1 || fail_rc=$?
[[ "$fail_rc" == 3 ]] || fail "exit code not preserved: $fail_rc"
found=0
for _ in $(seq 1 50); do
  grep -q "would run: agent=codex profile=work" "$fail_log" 2>/dev/null && { found=1; break; }
  sleep 0.1
done
[[ "$found" == 1 ]] || fail "failed session did not capture"

# 10. session_id falls back to the rollout session_meta, repeat exits dedupe,
# and a resumed (grown) transcript captures again.
mkdir -p "$tmp/stubbin"
cat >"$tmp/stubbin/codex" <<'STUB'
#!/usr/bin/env bash
printf 'stub codex args=%s\n' "$*" >>"${STUB_CODEX_LOG:?}"
STUB
chmod +x "$tmp/stubbin/codex"
kb2="$tmp/knowledge2"
mkdir -p "$kb2/logs"
capture_twice() {
  env -i PATH="$tmp/stubbin:/usr/bin:/bin" HOME="$tmp/home" EOS_ROOT="$ROOT" EOS_CAPTURE_PROFILE=work \
    EOS_WORK_KNOWLEDGE_ROOT="$kb2" EOS_CAPTURE_WORKSPACE_ROOT="$tmp" EOS_CAPTURE_AGENT=codex \
    STUB_CODEX_LOG="$tmp/stub-codex.log" \
    "$ROOT/scripts/eos-kb-capture" SessionEnd "$sessions/rollout-2026-02-01-b.jsonl" >/dev/null
}
export STUB_CODEX_LOG="$tmp/stub-codex.log"
capture_twice
markers() { find "$kb2/logs" -maxdepth 1 -type d -name '.capture-seen-SessionEnd-sid-b-*' | wc -l | tr -d ' '; }
[[ "$(markers)" == 1 ]] || fail "missing capture marker for sid-b"
grep -q "stub codex args=" "$STUB_CODEX_LOG" || fail "headless capture agent did not run"
capture_twice
[[ "$(markers)" == 1 ]] || fail "identical repeat was not deduped"
grep -q "skip event already captured" "$kb2/logs/.hook-debug.log" || fail "repeat capture was not deduped"
printf '%s\n' '{"type":"event_msg","payload":{"type":"task_started"}}' >>"$sessions/rollout-2026-02-01-b.jsonl"
capture_twice
[[ "$(markers)" == 2 ]] || fail "resumed transcript did not capture again"
[[ "$(grep -c "stub codex args=" "$STUB_CODEX_LOG")" == 2 ]] || fail "resumed capture agent did not run"

echo "codex session capture ok"
