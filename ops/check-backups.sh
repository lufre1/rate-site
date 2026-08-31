#!/usr/bin/env bash
#
# Fail loudly if the backups have quietly stopped working.
# An unmonitored backup is a backup you find out about during a restore.
# Run from cron: non-zero exit + stderr output makes cron mail the user.
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/lib.sh"

MAX_AGE_HOURS="${MAX_AGE_HOURS:-36}"
DB_DIR="$BACKUP_ROOT/db"

NEWEST="$(ls -1t "$DB_DIR"/*.dump 2>/dev/null | head -1 || true)"
[ -n "$NEWEST" ] || die "no database dump found in $DB_DIR"

AGE_S=$(( $(date +%s) - $(stat -c %Y "$NEWEST") ))
AGE_H=$(( AGE_S / 3600 ))
[ "$AGE_H" -le "$MAX_AGE_HOURS" ] \
    || die "newest dump $(basename "$NEWEST") is ${AGE_H}h old (max ${MAX_AGE_HOURS}h)"

SIZE=$(stat -c %s "$NEWEST")
[ "$SIZE" -ge "$MIN_DUMP_BYTES" ] \
    || die "newest dump is only ${SIZE}B (min ${MIN_DUMP_BYTES}B)"

log "OK: $(basename "$NEWEST") ${AGE_H}h old, ${SIZE}B, $(ls -1 "$DB_DIR"/*.dump | wc -l) dumps retained"
