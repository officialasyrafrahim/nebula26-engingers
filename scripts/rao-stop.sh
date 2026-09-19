#!/usr/bin/env bash
# Stop the Rail Access Optimisation helpers started by scripts/rao-start.sh.
#
#   scripts/rao-stop.sh            stop the tmux helpers only
#   scripts/rao-stop.sh --stack    also stop and remove the containers
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${RAO_ENV_FILE:-deploy/.env}"
export DOCKER_CONFIG="${DOCKER_CONFIG:-$HOME/.config/rao/docker}"

STACK=0
for arg in "$@"; do
  case "$arg" in
    --stack) STACK=1 ;;
    *) echo "[rao] unknown argument: $arg" >&2; exit 2 ;;
  esac
done

for session in rao-cf-named rao-cf-quick rao-awake; do
  if tmux kill-session -t "$session" 2>/dev/null; then
    echo "[rao] stopped tmux session '$session'"
  fi
done

if [ "$STACK" = "1" ]; then
  docker compose --env-file "$ENV_FILE" -f deploy/docker-compose.yml down
  echo "[rao] containers stopped"
fi
