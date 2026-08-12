#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

home="$tmp/home"
mkdir -p "$home"

run_bootstrap() {
  HOME="$home" \
    EOS_ROOT="$ROOT" \
    EOS_KB_HOME="$tmp/kb-runtime" \
    EOS_WORK_KNOWLEDGE_DIR="$home/work/knowledge" \
    EOS_PERSONAL_KNOWLEDGE_DIR="$home/personal/knowledge" \
    EOS_BOOTSTRAP_OFFLINE=1 \
    EOS_BOOTSTRAP_SKIP_VERIFY=1 \
    EOS_SKIP_LAUNCHCTL=1 \
    "$ROOT/bootstrap/bootstrap.sh" >/dev/null
}

snapshot() {
  find "$home" -path "$home/.cache" -prune -o \( -type f -o -type l \) -print | while IFS= read -r path; do
    case "$path" in
      "$tmp/kb-runtime"/*) continue ;;
    esac
    if [[ -L "$path" ]]; then
      printf 'L %s %s\n' "${path#$home/}" "$(readlink "$path")"
    else
      shasum -a 256 "$path" | sed "s|  $home/|  |"
    fi
  done | LC_ALL=C sort
}

backup_count() {
  if [[ -d "$ROOT/backups" ]]; then
    find "$ROOT/backups" -type f | wc -l | tr -d ' '
  else
    printf '0\n'
  fi
}

run_bootstrap
snapshot > "$tmp/first.snapshot"
backup_count_before="$(backup_count)"
run_bootstrap
snapshot > "$tmp/second.snapshot"
backup_count_after="$(backup_count)"

cmp "$tmp/first.snapshot" "$tmp/second.snapshot"
[[ "$backup_count_before" == "$backup_count_after" ]]

grep -Fq '"${EOS_AGENT_CLI_INSTALLER:-$ROOT/scripts/install-agent-clis}"' "$ROOT/bootstrap/bootstrap.sh"
if grep -F 'install-agent-clis' "$ROOT/bootstrap/bootstrap.sh" | grep -Fq '||'; then
  echo "agent CLI installation must fail bootstrap" >&2
  exit 1
fi

echo "bootstrap idempotence ok"
