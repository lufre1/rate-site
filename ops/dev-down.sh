#!/usr/bin/env bash
#
# Stop the DEV stack, freeing its share of the host's 3.8 GiB.
#
#   ops/dev-down.sh
#
# Use this before a large prod rebuild, or whenever you are not actively
# developing. `ops/dev-up.sh` brings it straight back.
#
# `stop`, never `down`: `down` removes containers and networks, and `down -v`
# would take the dev postgres volume with it. Stopping keeps everything and is
# reversible. See "Never `docker compose down -v`" in AGENTS.md.
set -euo pipefail
RATE_ENV=dev
export RATE_ENV
. "$(dirname "$(readlink -f "$0")")/lib.sh"

cd "$RATE_SITE_DIR"
before=$(awk '/^MemAvailable:/ {print int($2/1024)}' /proc/meminfo)
log "stopping dev stack"
docker compose -p rate-site-dev --env-file .env.dev \
    -f docker-compose.yml -f docker-compose.dev.yml stop
after=$(awk '/^MemAvailable:/ {print int($2/1024)}' /proc/meminfo)
log "dev stopped -- MemAvailable ${before} MiB -> ${after} MiB"
