#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

HOME="$tmp/home" EOS_ROOT="$ROOT" EOS_CONFIG_FILE="$tmp/missing" EOS_PROFILE_ROOT="$tmp/profiles" "$ROOT/scripts/eos-profile" init work >/dev/null
[[ -f "$tmp/profiles/work/config" ]]
[[ -f "$tmp/profiles/work/context.md" ]]
printf '%s\n' 'EOS_USER_NAME="Profile User"' 'EOS_BACKEND_DIR="$HOME/profile-backend"' >"$tmp/profiles/work/config"

output="$(HOME="$tmp/home" EOS_ROOT="$ROOT" EOS_CONFIG_FILE="$tmp/missing" EOS_PROFILE_ROOT="$tmp/profiles" EOS_PROFILE=work bash -c 'source "$EOS_ROOT/scripts/lib-eos-config.sh"; printf "%s|%s" "$EOS_USER_NAME" "$EOS_BACKEND_DIR"')"
[[ "$output" == "Profile User|$tmp/home/profile-backend" ]]
[[ "$(HOME="$tmp/home" EOS_ROOT="$ROOT" EOS_CONFIG_FILE="$tmp/missing" EOS_PROFILE_ROOT="$tmp/profiles" "$ROOT/scripts/eos-profile" list)" == "work" ]]

echo "profiles ok"
