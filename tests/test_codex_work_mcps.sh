#!/usr/bin/env bash
set -euo pipefail

ROOT="${EOS_ROOT:-$HOME/personal/eos}"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

source_json="$tmp_dir/.mcp.json"
codex_config="$tmp_dir/config.toml"

cat >"$source_json" <<'JSON'
{
  "mcpServers": {
    "postgres-local": {
      "command": "uv",
      "args": [
        "tool",
        "run",
        "--python",
        "3.12",
        "--from",
        "postgres-mcp",
        "postgres-mcp",
        "postgresql://nova:nova@127.0.0.1:5432/nova_agent",
        "--access-mode",
        "unrestricted"
      ]
    },
    "VisionAgent": {
      "command": "npx",
      "args": ["vision-tools-mcp"],
      "env": {
        "OUTPUT_DIRECTORY": "./output",
        "IMAGE_DISPLAY_ENABLED": "true"
      }
    }
  }
}
JSON

cat >"$codex_config" <<'TOML'
model = "gpt-5.5"

[projects."$HOME/work/backend-project"]
trust_level = "trusted"
TOML

SOURCE_MCP_JSON="$source_json" CODEX_CONFIG_TOML="$codex_config" "$ROOT/scripts/install-codex-work-mcps" >/dev/null
SOURCE_MCP_JSON="$source_json" CODEX_CONFIG_TOML="$codex_config" "$ROOT/scripts/install-codex-work-mcps" >/dev/null

grep -q 'model = "gpt-5.5"' "$codex_config"
grep -q '\[projects."$HOME/work/backend-project"\]' "$codex_config"
grep -q '# BEGIN EOS WORK MCP SERVERS' "$codex_config"
grep -q '# END EOS WORK MCP SERVERS' "$codex_config"
grep -q '\[mcp_servers."postgres-local"\]' "$codex_config"
grep -q 'command = "uv"' "$codex_config"
grep -q 'args = \["tool", "run", "--python", "3.12", "--from", "postgres-mcp", "postgres-mcp", "postgresql://nova:nova@127.0.0.1:5432/nova_agent", "--access-mode", "unrestricted"\]' "$codex_config"
grep -q '\[mcp_servers."VisionAgent"\]' "$codex_config"
grep -q '\[mcp_servers."VisionAgent".env\]' "$codex_config"
grep -q '"OUTPUT_DIRECTORY" = "./output"' "$codex_config"

marker_count="$(grep -c '# BEGIN EOS WORK MCP SERVERS' "$codex_config")"
[[ "$marker_count" == "1" ]]

echo "codex work MCPs ok"
