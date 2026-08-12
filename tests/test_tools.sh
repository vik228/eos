#!/usr/bin/env bash
set -euo pipefail

ROOT="${EOS_ROOT:-$HOME/personal/eos}"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:$ROOT/scripts:$ROOT/bin:$PATH"

required=(git zsh tmux nvim starship uv node python3 mise)
missing=()

if [[ ! -x /opt/homebrew/bin/brew ]]; then
  missing+=("/opt/homebrew/bin/brew")
fi

for tool in "${required[@]}"; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    missing+=("$tool")
  fi
done

if ((${#missing[@]})); then
  printf 'missing required tools:\n'
  printf '  %s\n' "${missing[@]}"
  exit 1
fi

echo "required tools ok"
