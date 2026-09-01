#!/usr/bin/env bash
#
# Installs the host-side crash forensics: the memwatch sampler, the boot report,
# log rotation for both, the journald sync interval and the earlyoom priority
# drop-in. Idempotent -- safe to re-run after editing anything in ops/systemd/.
#
# The unit files live in the repo (ops/systemd/) so they are version-controlled
# and reviewable; this script is the only part that needs root. If the VM is ever
# rebuilt, this one command restores the whole arrangement.
#
#   sudo ./ops/install-host-monitoring.sh
#
# It does NOT install earlyoom or the swap file themselves -- see the "Host
# memory" section of AGENTS.md for those two commands.
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/lib.sh"
[ "$(id -u)" = "0" ] || die "run with sudo"

SRC="$RATE_SITE_DIR/ops/systemd"

install -d -o root -g cloud -m 2775 \
    /var/log/rate-site /var/log/rate-site/boot-reports /var/log/rate-site/state
install -d /etc/systemd/journald.conf.d /etc/systemd/system/earlyoom.service.d

install -m 0644 "$SRC/rate-site-memwatch.service"    /etc/systemd/system/
install -m 0644 "$SRC/rate-site-boot-report.service" /etc/systemd/system/
install -m 0644 "$SRC/logrotate-rate-site"           /etc/logrotate.d/rate-site
install -m 0644 "$SRC/journald-sync.conf"            /etc/systemd/journald.conf.d/10-sync.conf
install -m 0644 "$SRC/earlyoom-priority.conf"        /etc/systemd/system/earlyoom.service.d/priority.conf

# certbot renews the files but cannot reload nginx by itself; without this the
# proxy serves the expired certificate until it is restarted. See the script.
install -d /etc/letsencrypt/renewal-hooks/deploy
install -m 0755 "$RATE_SITE_DIR/ops/letsencrypt-deploy-hook.sh" \
    /etc/letsencrypt/renewal-hooks/deploy/reload-rate-site-proxy.sh

systemctl daemon-reload
systemctl enable --now rate-site-memwatch.service
systemctl enable rate-site-boot-report.service
systemctl restart systemd-journald
systemctl is-active --quiet earlyoom && systemctl restart earlyoom

log "installed -- tail -f /var/log/rate-site/memwatch.log"
