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
#
# Deliberately no --force-recreate. The proxy container is the sole holder of the
# host's :80 and :443, so recreating it unconditionally took the site off the air
# for the length of every deploy -- a refused connection rather than a 502,
# because nothing at all was listening. Compose recreates the containers whose
# resolved config actually changed, so a code-only deploy now leaves the proxy
# listening the whole way through.
#
# What that gives up: Compose hashes image, env and mounts, but not the *contents*
# of a bind-mounted file, so an edit to nginx-proxy.conf no longer recreates the
# proxy by itself. The reload below is what covers that, and is why it is
# unconditional rather than something the operator has to remember.
docker compose -p rate-site -f docker-compose.yml up -d --remove-orphans $BUILD

log "deploy done -- verifying"
sleep 5 2>/dev/null || true

# Pick up any nginx-proxy.conf edit that Compose's change detection cannot see
# (see above). `nginx -s reload` keeps the listening sockets open and cycles the
# workers underneath them, so the site never stops accepting connections.
#
# Not quite free, though: measured against this stack, each reload loses exactly
# one in-flight HTTP/2 connection (curl exits 16, CURLE_HTTP2) as a draining
# worker sends GOAWAY. Browsers retry a GOAWAY on a new connection and show
# nothing; curl does not. That is the cost of a reload here -- one connection,
# against the ~15s of refused connections that --force-recreate used to cost.
#
# Gated on `nginx -t` so a config that does not parse is caught here, with the
# old one still serving, instead of at the next restart when nothing is.
log "reloading proxy config"
docker compose -p rate-site -f docker-compose.yml exec -T proxy nginx -t \
  || die "proxy config is invalid -- previous config left running, nothing reloaded"
docker compose -p rate-site -f docker-compose.yml exec -T proxy nginx -s reload \
  || die "proxy config validated but the reload failed"

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
