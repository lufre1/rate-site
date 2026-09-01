#!/usr/bin/env bash
#
# Compose reports container health but NEVER acts on it: `restart: unless-stopped`
# only reacts to the process exiting, so a hung uvicorn stays "Up" forever. This
# is the smallest thing that closes that gap -- two consecutive unhealthy
# observations restart that ONE container.
#
# It never runs `docker compose up`, never recreates anything, and never touches
# volumes. Restarting a single container cannot cross the prod/dev boundary.
#
#   ops/check-stack.sh              # prod (cron runs this every 5 minutes)
#   RATE_ENV=dev ops/check-stack.sh # dev
#
# Deliberately does NOT react to /api/v1/health/db failures: restarting the
# backend cannot fix a broken database, and doing so during a DB outage would be
# a restart loop. ops/check-host.sh reports on that instead.
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/lib.sh"

STATE_DIR=/var/log/rate-site/state
mkdir -p "$STATE_DIR" 2>/dev/null || true
C="${_DEF_PROJECT}-backend-1"
F="$STATE_DIR/${C}.unhealthy"

H="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
     "$C" 2>/dev/null || echo missing)"

case "$H" in
    healthy|none)
        # `none` = image predates the healthcheck; nothing to act on.
        rm -f "$F"
        exit 0 ;;
    starting)
        # start_period covers the blocking startup scrape. Not a fault yet.
        exit 0 ;;
esac

N=$(( $(cat "$F" 2>/dev/null || echo 0) + 1 ))
echo "$N" > "$F"
log "$C is $H (consecutive: $N)"

if [ "$N" -ge 2 ]; then
    log "restarting $C"
    if docker restart "$C" >/dev/null; then
        rm -f "$F"
        write_status "ALARM restarted $C after ${N}x $H"
    else
        write_status "ALARM $C is $H and could not be restarted"
    fi
fi
