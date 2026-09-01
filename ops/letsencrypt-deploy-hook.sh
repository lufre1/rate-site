#!/bin/sh
#
# certbot deploy hook -- runs ONLY when a certificate was actually renewed.
# Installed to /etc/letsencrypt/renewal-hooks/deploy/ by
# ops/install-host-monitoring.sh.
#
# Why this has to exist: certbot renews the files under /etc/letsencrypt, but
# nginx reads its certificate once at startup and keeps it in memory. Without a
# reload the proxy goes on serving the OLD certificate until the container
# happens to restart -- so the cert silently expires in production while
# /etc/letsencrypt looks perfectly healthy. ops/check-host.sh's cert-expiry probe
# reads the cert off the live socket (not off disk) precisely so it catches this.
#
# `nginx -s reload` is a graceful signal: workers finish in-flight requests and
# new ones pick up the new certificate. No restart, no dropped connections.
#
# Kept deliberately quiet on the happy path -- certbot logs hook output, and this
# runs from a systemd timer at 06:14 with no MTA on the host.
set -eu

CONTAINER="${PROXY_CONTAINER:-rate-site-proxy-1}"

# Not an error worth failing the renewal over: the cert is on disk and correct,
# and the next container start will pick it up. Say so loudly instead.
if ! docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true; then
    echo "deploy-hook: $CONTAINER not running; new cert will be used at next start" >&2
    exit 0
fi

# Validate before reloading: a reload with a bad config leaves the old workers
# serving, but failing here makes the reason obvious in the certbot log.
docker exec "$CONTAINER" nginx -t
docker exec "$CONTAINER" nginx -s reload
echo "deploy-hook: reloaded $CONTAINER for renewed certificate"
