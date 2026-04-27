#!/usr/bin/env bash
# Wrapper that loads .env, then launches the Freebeat MCP server.
# Referenced from .mcp.json so Claude Code can spawn it with the right env.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$HERE/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$HERE/.env"
  set +a
fi
if [ -z "${FREEBEAT_API_KEY:-}" ]; then
  echo "FREEBEAT_API_KEY not set — add it to $HERE/.env" >&2
  exit 1
fi
exec npx -y freebeat-mcp
