#!/usr/bin/env bash
set -euo pipefail

ROOT="${EOS_ROOT:-$HOME/personal/eos}"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

source_json="$tmp_dir/.mcp.json"
target_one="$tmp_dir/gemini/config/mcp_config.json"
target_two="$tmp_dir/gemini/antigravity-ide/mcp_config.json"

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

mkdir -p "$(dirname "$target_one")" "$(dirname "$target_two")"
cat >"$target_one" <<'JSON'
{
  "mcpServers": {
    "sequential-thinking": {
      "$typeName": "exa.cascade_plugins_pb.CascadePluginCommandTemplate",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
      "env": {}
    }
  }
}
JSON

cat >"$target_two" <<'JSON'
{
  "mcpServers": {}
}
JSON

SOURCE_MCP_JSON="$source_json" ANTIGRAVITY_MCP_CONFIGS="$target_one:$target_two" "$ROOT/scripts/install-antigravity-mcps" >/dev/null
SOURCE_MCP_JSON="$source_json" ANTIGRAVITY_MCP_CONFIGS="$target_one:$target_two" "$ROOT/scripts/install-antigravity-mcps" >/dev/null

for target in "$target_one" "$target_two"; do
  jq -e '.mcpServers."postgres-local"."$typeName" == "exa.cascade_plugins_pb.CascadePluginCommandTemplate"' "$target" >/dev/null
  jq -e '.mcpServers."postgres-local".command == "uv"' "$target" >/dev/null
  jq -e '.mcpServers."postgres-local".args[0] == "tool"' "$target" >/dev/null
  jq -e '.mcpServers."VisionAgent".command == "npx"' "$target" >/dev/null
  jq -e '.mcpServers."VisionAgent".env.OUTPUT_DIRECTORY == "./output"' "$target" >/dev/null
done

jq -e '.mcpServers."sequential-thinking".command == "npx"' "$target_one" >/dev/null

echo "Antigravity MCPs ok"
