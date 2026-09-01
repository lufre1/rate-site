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

# Assert the code. This was `curl -sf ... http://localhost/api/v1/mensas`, which
# stopped verifying anything when port 80 became an HTTPS redirect on 2026-09-01:
# `curl -f` does not treat a 3xx as an error and there is no -L, so a deploy that
# left the API dead would still have printed a cheerful "-> 301" and exited 0.
# Same bug, same day, as the one in ops/check-host.sh.
#
# --resolve rather than -k so the certificate chain is validated on the way past.
CODE=$(curl -s -m 10 -o /dev/null -w '%{http_code}' \
       --resolve "${SITE_DOMAIN}:443:127.0.0.1" \
       "https://${SITE_DOMAIN}/api/v1/mensas" 2>/dev/null) || CODE="000"
printf 'api/v1/mensas -> %s\n' "$CODE"
[ "$CODE" = "200" ] || die "prod API is not answering after deploy (got $CODE)"
