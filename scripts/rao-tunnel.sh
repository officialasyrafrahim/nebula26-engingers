#!/usr/bin/env bash
# Run the Cloudflare Tunnel connector for RAO.
#
# Reads the tunnel token from the environment, deploy/.env or a token file and
# passes it to cloudflared through the TUNNEL_TOKEN environment variable, so the
# secret never appears in a process argument list.
#
# Token resolution order:
#   1. RAO_TUNNEL_TOKEN
#   2. RAO_TUNNEL_TOKEN_FILE (default /tmp/opencode/cf_token)
#   3. deploy/.env (sourced above)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${RAO_ENV_FILE:-$ROOT/deploy/.env}"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

TOKEN="${RAO_TUNNEL_TOKEN:-}"
if [ -z "$TOKEN" ]; then
  TOKEN_FILE="${RAO_TUNNEL_TOKEN_FILE:-/tmp/opencode/cf_token}"
  if [ -s "$TOKEN_FILE" ]; then
    TOKEN="$(cat "$TOKEN_FILE")"
  fi
fi

if [ -z "$TOKEN" ]; then
  echo "[rao-tunnel] no tunnel token found; set RAO_TUNNEL_TOKEN in deploy/.env" >&2
  exit 1
fi

export TUNNEL_TOKEN="$TOKEN"
exec nix run nixpkgs#cloudflared -- tunnel --no-autoupdate run
