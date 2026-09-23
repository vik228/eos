#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

config="$tmp/eos.local"
printf '%s\n' ': "${TYPESAFE_API_KEY_WORK:=}"' >"$config"

run_env=(env -i HOME="$tmp/home" PATH="$PATH" EOS_ROOT="$ROOT" EOS_CONFIG_FILE="$config" EOS_PROFILE_ROOT="$tmp/profiles")

# A long-lived parent (tmux, agent session) loads config before the key exists,
# then the user adds the key. Child processes must pick it up.
output="$("${run_env[@]}" bash -c '
  source "$EOS_ROOT/scripts/lib-eos-config.sh"
  printf "%s\n" ": \"\${TYPESAFE_API_KEY_WORK:=added-later}\"" >"$EOS_CONFIG_FILE"
  bash -c "source \"\$EOS_ROOT/scripts/lib-eos-config.sh\"; printf %s \"\$TYPESAFE_API_KEY_WORK\""
')"
[[ "$output" == "added-later" ]]

# Sourcing twice in one shell stays a no-op.
output="$("${run_env[@]}" bash -c '
  source "$EOS_ROOT/scripts/lib-eos-config.sh"
  EOS_USER_NAME="changed"
  source "$EOS_ROOT/scripts/lib-eos-config.sh"
  printf %s "$EOS_USER_NAME"
')"
[[ "$output" == "changed" ]]

# eos-jev-filter reads keys from the EOS config file.
printf '%s\n' ': "${TYPESAFE_API_KEY_WORK:=work-key}"' >"$config"
[[ "$("${run_env[@]}" "$ROOT/scripts/eos-jev-filter" status)" == '{"work": true, "personal": false}' ]]

echo "config reload ok"
