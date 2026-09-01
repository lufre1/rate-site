#!/usr/bin/env bash
#
# The only sanctioned way to deploy to production.
# Takes a fresh backup first: a dump from twenty minutes ago is worth far more
# than last night's when a schema change goes wrong.
#
#   ops/pre-deploy.sh            # backup, then recreate the prod stack
#   ops/pre-deploy.sh --build    # ...rebuilding images first
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/lib.sh"

BUILD=""
[ "${1:-}" = "--build" ] && BUILD="--build"

show_host_status
# Before backup.sh: no point spending minutes on a dump for a build that will
# then be refused for lack of memory.
# Spelled as an `if` rather than `[ -n "$BUILD" ] && require_build_headroom`
# purely for clarity: under `set -e` the && form is safe (bash exempts the
# left-hand side of an AND list), but the `if` says what it means.
if [ -n "$BUILD" ]; then require_build_headroom; fi

log "pre-deploy backup"
"$(dirname "$(readlink -f "$0")")/backup.sh"

log "deploying prod stack"
cd "$RATE_SITE_DIR"
# Base compose only, explicit project name. Passing docker-compose.dev.yml here
# is what previously made the prod proxy squat dev's port 8080.
docker compose -p rate-site -f docker-compose.yml up -d --force-recreate --remove-orphans $BUILD

log "deploy done -- verifying"
sleep 5 2>/dev/null || true
curl -sf -o /dev/null -w 'api/v1/mensas -> %{http_code}\n' http://localhost/api/v1/mensas \
    || die "prod API is not answering after deploy"
