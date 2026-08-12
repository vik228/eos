#!/usr/bin/env bash

if [[ -n "${EOS_CONFIG_LOADED:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi
export EOS_CONFIG_LOADED=1

EOS_ROOT="${EOS_ROOT:-$HOME/personal/eos}"
EOS_CONFIG_FILE="${EOS_CONFIG_FILE:-$EOS_ROOT/.eos.local}"

if [[ -f "$EOS_CONFIG_FILE" ]]; then
  # This file is user-owned shell configuration and is intentionally local.
  # shellcheck source=/dev/null
  source "$EOS_CONFIG_FILE"
fi

EOS_PROFILE="${EOS_PROFILE:-default}"
EOS_PROFILE_ROOT="${EOS_PROFILE_ROOT:-$HOME/.config/eos/profiles}"
EOS_PROFILE_CONFIG="$EOS_PROFILE_ROOT/$EOS_PROFILE/config"
if [[ -f "$EOS_PROFILE_CONFIG" ]]; then
  # Named profiles are user-owned shell overlays loaded after machine defaults.
  # shellcheck source=/dev/null
  source "$EOS_PROFILE_CONFIG"
fi

export EOS_ROOT
export EOS_PROFILE
export EOS_PROFILE_ROOT
export EOS_USER_NAME="${EOS_USER_NAME:-Your Name}"
export EOS_WORK_GIT_EMAIL="${EOS_WORK_GIT_EMAIL:-you@company.example}"
export EOS_PERSONAL_GIT_EMAIL="${EOS_PERSONAL_GIT_EMAIL:-you@example.com}"
export EOS_WORK_ROOT="${EOS_WORK_ROOT:-$HOME/work}"
export EOS_PERSONAL_ROOT="${EOS_PERSONAL_ROOT:-$HOME/personal}"
export EOS_RESEARCH_ROOT="${EOS_RESEARCH_ROOT:-$HOME/research}"
export EOS_TOOLS_ROOT="${EOS_TOOLS_ROOT:-$HOME/tools}"
export EOS_WORK_KNOWLEDGE_ROOT="${EOS_WORK_KNOWLEDGE_ROOT:-$EOS_WORK_ROOT/knowledge}"
export EOS_PERSONAL_KNOWLEDGE_ROOT="${EOS_PERSONAL_KNOWLEDGE_ROOT:-$EOS_PERSONAL_ROOT/knowledge}"
export EOS_BACKEND_DIR="${EOS_BACKEND_DIR:-$EOS_WORK_ROOT/backend}"
export EOS_WORK_PROJECT_SLUG="${EOS_WORK_PROJECT_SLUG:-backend}"
export EOS_RESEARCH_DIR="${EOS_RESEARCH_DIR:-$EOS_PERSONAL_ROOT/research-project}"
export EOS_RESEARCH_PROJECT_SLUG="${EOS_RESEARCH_PROJECT_SLUG:-research}"
export EOS_ALGO_DIR="${EOS_ALGO_DIR:-$EOS_PERSONAL_ROOT/leetcode}"
export EOS_AGENT_PROFILE_NAME="${EOS_AGENT_PROFILE_NAME:-User}"
export EOS_LOCAL_AGENT_CONTEXT="${EOS_LOCAL_AGENT_CONTEXT:-$EOS_PROFILE_ROOT/$EOS_PROFILE/context.md}"
export EOS_KB_REGISTRY="${EOS_KB_REGISTRY:-${EOS_GENERATED_DIR:-$HOME/.config/eos/generated}/kb/workspaces.yaml}"
