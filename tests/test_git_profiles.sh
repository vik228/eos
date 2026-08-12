#!/usr/bin/env bash
set -euo pipefail

ROOT="${EOS_ROOT:-$HOME/personal/eos}"
source "$ROOT/scripts/lib-eos-config.sh"
GENERATED="${EOS_GENERATED_DIR:-$HOME/.config/eos/generated}"

"$ROOT/scripts/render-local-config" >/dev/null
grep -Fq "gitdir:$EOS_WORK_ROOT/" "$GENERATED/git/gitconfig"
grep -Fq "gitdir:$EOS_PERSONAL_ROOT/" "$GENERATED/git/gitconfig"
grep -Fq "gitdir:$EOS_RESEARCH_ROOT/" "$GENERATED/git/gitconfig"
grep -Fq "gitdir:$EOS_TOOLS_ROOT/" "$GENERATED/git/gitconfig"
grep -Fq "name = $EOS_USER_NAME" "$GENERATED/git/gitconfig-work"
grep -Fq "email = $EOS_WORK_GIT_EMAIL" "$GENERATED/git/gitconfig-work"
grep -Fq "email = $EOS_PERSONAL_GIT_EMAIL" "$GENERATED/git/gitconfig-personal"

echo "git profiles ok"
