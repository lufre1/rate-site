#!/usr/bin/env bash
#
# Disk, swap, memory-guard and stack sanity for the HOST itself.
#
# There is no MTA on this box (see AGENTS.md, "Backups"), so cron mail goes
# nowhere and /var/log/rate-site/STATUS is the actual record -- the same pattern
# ops/backup.sh uses for /home/cloud/backups/STATUS. ops/lib.sh's
# show_host_status() prints it at the top of every deploy so it is seen.
#
# Exits 3 on a problem, so cron's stderr still carries the detail if anyone ever
# does add an MTA.
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/lib.sh"

DISK_WARN_PCT="${DISK_WARN_PCT:-80}"
DISK_WARN_FREE_G="${DISK_WARN_FREE_G:-6}"
CACHE_WARN_G="${CACHE_WARN_G:-20}"
PROBLEMS=""

USED=$(df --output=pcent / | tail -1 | tr -dc 0-9)
FREE_G=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
[ "${USED:-0}" -ge "$DISK_WARN_PCT" ]     && PROBLEMS="$PROBLEMS disk=${USED}%"
[ "${FREE_G:-0}" -le "$DISK_WARN_FREE_G" ] && PROBLEMS="$PROBLEMS free=${FREE_G}G"

# The swap added on 2026-09-01 is load-bearing: without it the kernel has no
# reclaim cushion and earlyoom's -s threshold never becomes meaningful.
SWAP_TOTAL=$(awk '/^SwapTotal:/ {print int($2/1024)}' /proc/meminfo)
[ "${SWAP_TOTAL:-0}" -lt 1024 ] && PROBLEMS="$PROBLEMS swap=${SWAP_TOTAL}MiB(expected 2048)"

systemctl is-active --quiet rate-site-memwatch || PROBLEMS="$PROBLEMS memwatch=down"
systemctl is-active --quiet earlyoom           || PROBLEMS="$PROBLEMS earlyoom=down"

CACHE="$(docker system df --format '{{.Type}}\t{{.Size}}' 2>/dev/null \
         | awk -F'\t' '/Build Cache/{print $2}')"
CACHE_G="$(printf '%s' "${CACHE:-0}" | tr -dc 0-9.)"
case "${CACHE:-}" in
    *GB) awk -v c="${CACHE_G:-0}" -v w="$CACHE_WARN_G" 'BEGIN{exit !(c>w)}' \
             && PROBLEMS="$PROBLEMS buildcache=${CACHE}" ;;
esac

# Readiness of the prod API. Reported, never acted on -- restarting the backend
# cannot fix a broken database, and doing so on a DB outage is a restart loop.
#
# Assert the status code explicitly. This probe used to be
#     curl -sf -m 5 -o /dev/null http://localhost/api/v1/health/db
# and it silently stopped testing anything the moment port 80 became a redirect
# to HTTPS on 2026-09-01: `curl -f` does not treat a 3xx as an error and there is
# no -L, so it exited 0 on the 301 without ever reaching the backend. It would
# have reported a healthy host with a completely dead API. Same shape as the
# backup tripwire's lesson -- a check that cannot fail is not a check.
#
# --resolve rather than -k so the real certificate chain is validated too; an
# expired or mismatched cert fails here instead of only in users' browsers.
API_CODE=$(curl -s -m 5 -o /dev/null -w '%{http_code}' \
           --resolve "${SITE_DOMAIN}:443:127.0.0.1" \
           "https://${SITE_DOMAIN}/api/v1/health/db" 2>/dev/null) || API_CODE="000"
[ "$API_CODE" = "200" ] || PROBLEMS="$PROBLEMS prod-db-health=$API_CODE"

# Certificate expiry. certbot renews at 30 days remaining, so anything below
# CERT_WARN_DAYS means a renewal is stuck -- or renewed on disk but never
# reloaded into nginx, which serves the old cert until the container restarts.
CERT_END=$(echo | openssl s_client -connect 127.0.0.1:443 -servername "$SITE_DOMAIN" 2>/dev/null \
           | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
if [ -n "${CERT_END:-}" ]; then
    CERT_DAYS=$(( ( $(date -d "$CERT_END" +%s) - $(date +%s) ) / 86400 ))
    [ "$CERT_DAYS" -ge "$CERT_WARN_DAYS" ] || PROBLEMS="$PROBLEMS cert-expiry=${CERT_DAYS}d"
else
    CERT_DAYS="?"
    PROBLEMS="$PROBLEMS cert-read=fail"
fi

log "disk ${USED}% (${FREE_G}G free), swap ${SWAP_TOTAL}MiB, build cache ${CACHE:-?}, cert ${CERT_DAYS}d"

if [ -n "$PROBLEMS" ]; then
    write_status "ALARM$PROBLEMS"
    echo "host check found:$PROBLEMS" >&2
    exit 3
fi
write_status "OK disk ${USED}% swap ${SWAP_TOTAL}MiB cache ${CACHE:-?}"
