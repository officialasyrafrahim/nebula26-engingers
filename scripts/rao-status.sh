#!/usr/bin/env bash
# Show the state of the RAO stack, helpers and public URL.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${RAO_ENV_FILE:-deploy/.env}"
export DOCKER_CONFIG="${DOCKER_CONFIG:-$HOME/.config/rao/docker}"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

WEB_BIND="${WEB_BIND_ADDRESS:-127.0.0.1}"
WEB_PORT="${WEB_HOST_PORT:-5173}"

echo "== containers =="
docker compose --env-file "$ENV_FILE" -f deploy/docker-compose.yml ps \
  --format '{{.Name}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || echo "compose unavailable"

echo
echo "== tmux sessions =="
tmux ls 2>/dev/null || echo "none"

echo
echo "== local health =="
printf 'web  %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "http://$WEB_BIND:$WEB_PORT/healthz" || echo down)"
printf 'api  %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "http://${API_HOST_PORT:-8000}/healthz" || echo down)"

if [ -n "${RAO_PUBLIC_URL:-}" ]; then
  echo
  echo "== public health =="
  printf '%s  %s\n' "$RAO_PUBLIC_URL" \
    "$(curl -s -o /dev/null -w '%{http_code}' "$RAO_PUBLIC_URL/healthz" || echo down)"
fi
