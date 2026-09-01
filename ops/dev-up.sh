#!/usr/bin/env bash
#
# Bring up the DEV stack on port 8080. Use this instead of assembling the
# compose flags by hand -- getting them wrong is what put prod on port 8080 on
# 2026-08-31.
#
#   ops/dev-up.sh              # start/refresh dev
#   ops/dev-up.sh --build      # rebuild images first (needed after code changes)
#
# docker-compose.dev.yml also pins `name: rate-site-dev` and uses `!override`,
# so even a hand-rolled invocation that forgets -p now lands on dev rather than
# prod. This script is the convenient path, not the only safeguard.
set -euo pipefail
# Must be its own statement: in non-POSIX bash, an assignment prefixing `.` is
# reverted once the source completes, so `RATE_ENV=dev . lib.sh` would not stick.
RATE_ENV=dev
export RATE_ENV
. "$(dirname "$(readlink -f "$0")")/lib.sh"

BUILD=""
[ "${1:-}" = "--build" ] && BUILD="--build"

show_host_status
# Spelled as an `if` rather than `[ -n "$BUILD" ] && require_build_headroom`
# purely for clarity: under `set -e` the && form is safe (bash exempts the
# left-hand side of an AND list), but the `if` says what it means.
if [ -n "$BUILD" ]; then require_build_headroom; fi

PORT="$(grep -E '^PROXY_PORT=' "$RATE_SITE_DIR/.env.dev" | cut -d= -f2-)"
PORT="${PORT:-8080}"

cd "$RATE_SITE_DIR"
log "starting dev stack on port $PORT"
docker compose -p rate-site-dev --env-file .env.dev \
    -f docker-compose.yml -f docker-compose.dev.yml \
    up -d --remove-orphans $BUILD

log "waiting for the dev API"
# The sleep is load-bearing: without it this loop fired all 30 curls inside a
# second and declared failure while the backend was still starting. The backend
# blocks on scrape_menus() during startup (up to 14 HTTP fetches at a 10s
# timeout), so give it a real minute.
for _ in $(seq 1 30); do
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$PORT/api/v1/mensas" || true)"
    [ "$code" = "200" ] && break
    sleep 2
done
[ "${code:-}" = "200" ] || die "dev API did not come up on port $PORT (last status: ${code:-none})"
log "dev API OK on http://localhost:$PORT"

# Cheap tripwire against the failure mode this whole split exists to prevent.
prod_ports="$(docker inspect rate-site-proxy-1 --format '{{json .NetworkSettings.Ports}}' 2>/dev/null || echo '')"
case "$prod_ports" in
    *\"$PORT\"*) die "prod's proxy is ALSO publishing $PORT -- the stacks are crossed" ;;
esac
log "prod proxy is not publishing $PORT -- stacks are cleanly separated"
