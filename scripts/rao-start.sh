#!/usr/bin/env bash
# Start the Rail Access Optimisation stack and its long-running helpers.
#
# Idempotent: running it again only starts what is missing.
#   scripts/rao-start.sh            start stack + tunnel + sleep inhibitor
#   scripts/rao-start.sh --no-build skip the image build
#
# Host settings come from deploy/.env (never printed). Relevant keys:
#   WEB_BIND_ADDRESS, WEB_HOST_PORT   where the UI is served
#   RAO_TUNNEL_TOKEN                  Cloudflare named-tunnel token (preferred)
#   RAO_TUNNEL_TOKEN_FILE             file holding the token
#   RAO_PUBLIC_URL                    optional URL to verify at the end
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${RAO_ENV_FILE:-deploy/.env}"
BUILD=1
for arg in "$@"; do
  case "$arg" in
    --no-build) BUILD=0 ;;
    *) echo "[rao] unknown argument: $arg" >&2; exit 2 ;;
  esac
done

export DOCKER_CONFIG="${DOCKER_CONFIG:-$HOME/.config/rao/docker}"
mkdir -p "$DOCKER_CONFIG"
[ -f "$DOCKER_CONFIG/config.json" ] || printf '{}\n' > "$DOCKER_CONFIG/config.json"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

WEB_BIND="${WEB_BIND_ADDRESS:-127.0.0.1}"
WEB_PORT="${WEB_HOST_PORT:-5173}"
LOCAL_URL="http://$WEB_BIND:$WEB_PORT"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f deploy/docker-compose.yml)

log() { printf '[rao] %s\n' "$*"; }

start_session() {
  local name="$1"
  shift
  if tmux has-session -t "$name" 2>/dev/null; then
    log "tmux session '$name' already running"
    return 0
  fi
  tmux new-session -d -s "$name" "$*"
  log "started tmux session '$name'"
}

# 1. Containers.
log "bringing up containers"
if [ "$BUILD" = "1" ]; then
  "${COMPOSE[@]}" up --build -d
else
  "${COMPOSE[@]}" up -d
fi

log "waiting for $LOCAL_URL/healthz"
for _ in $(seq 1 60); do
  if curl -fsS "$LOCAL_URL/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
if ! curl -fsS "$LOCAL_URL/healthz" >/dev/null 2>&1; then
  log "stack did not become healthy; check 'make logs'"
  exit 1
fi
log "stack healthy at $LOCAL_URL"

# 2. Tunnel. Prefer the named tunnel; fall back to a quick tunnel.
TOKEN="${RAO_TUNNEL_TOKEN:-}"
if [ -z "$TOKEN" ]; then
  TOKEN_FILE="${RAO_TUNNEL_TOKEN_FILE:-/tmp/opencode/cf_token}"
  if [ -s "$TOKEN_FILE" ]; then
    TOKEN="$(cat "$TOKEN_FILE")"
  fi
fi

if [ -n "$TOKEN" ]; then
  # The wrapper reads the token itself, so it stays out of the process argv.
  start_session rao-cf-named "$ROOT/scripts/rao-tunnel.sh"
  log "named tunnel running: ${RAO_PUBLIC_URL:-see the Cloudflare dashboard hostname}"
elif tmux has-session -t rao-cf-named 2>/dev/null; then
  log "named tunnel already running; set RAO_TUNNEL_TOKEN in deploy/.env to manage it from here"
else
  start_session rao-cf-quick \
    "nix run nixpkgs#cloudflared -- tunnel --url $LOCAL_URL"
  log "no RAO_TUNNEL_TOKEN: started a temporary quick tunnel"
fi

# 3. Keep the machine awake for the demo.
start_session rao-awake \
  "systemd-inhibit --what=sleep --who=RAO --why='RAO hosted demo' sleep infinity"

# 4. Optional public check.
if [ -n "${RAO_PUBLIC_URL:-}" ]; then
  if curl -fsS "$RAO_PUBLIC_URL/healthz" >/dev/null 2>&1; then
    log "public check ok: $RAO_PUBLIC_URL/healthz"
  else
    log "public check failed for $RAO_PUBLIC_URL/healthz (may need DNS/tunnel warmup)"
  fi
fi

log "sessions:"
tmux ls 2>/dev/null || true
log "done"
