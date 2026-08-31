#!/usr/bin/env bash
#
# Nightly backup of the production database and the uploaded photos.
#
# Written after the 2026-08-31 incident, in which every table was dropped and
# there was no backup of any kind to restore from.
#
# Design notes:
#   * The dump is written to <name>.part and renamed only on success, so a
#     truncated dump can never be mistaken for a good one.
#   * The dump is verified with `pg_restore --list` and rejected if it is
#     suspiciously small or contains no tables.
#   * Photos are backed up too. ratings.photo_url points at files in uploads/,
#     so a database-only restore is half a restore.
#   * Retention prunes only AFTER a new good backup exists.
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/lib.sh"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DB_DIR="$BACKUP_ROOT/db"
UP_DIR="$BACKUP_ROOT/uploads"
WEEKLY_DIR="$BACKUP_ROOT/weekly"
mkdir -p "$DB_DIR" "$UP_DIR" "$WEEKLY_DIR"

docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null | grep -q true \
    || die "database container '$DB_CONTAINER' is not running -- no backup taken"

# ---------------------------------------------------------------- database
DUMP="$DB_DIR/${DB_NAME}_${STAMP}.dump"
log "dumping $DB_NAME from $DB_CONTAINER"
docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc > "$DUMP.part" \
    || { rm -f "$DUMP.part"; die "pg_dump failed"; }

SIZE=$(stat -c %s "$DUMP.part")
[ "$SIZE" -ge "$MIN_DUMP_BYTES" ] \
    || { rm -f "$DUMP.part"; die "dump is only ${SIZE}B (min ${MIN_DUMP_BYTES}B) -- is the database empty?"; }

TABLES=$(docker exec -i "$DB_CONTAINER" pg_restore --list < "$DUMP.part" 2>/dev/null | grep -c ' TABLE ' || true)
[ "$TABLES" -gt 0 ] \
    || { rm -f "$DUMP.part"; die "dump contains no tables -- refusing to keep it"; }

mv "$DUMP.part" "$DUMP"
log "database OK: $(basename "$DUMP") ${SIZE}B, $TABLES tables"

# ---------------------------------------------------------------- uploads
TAR="$UP_DIR/uploads_${STAMP}.tar.gz"
if [ -d "$UPLOADS_DIR" ]; then
    # Photos are append-mostly, so re-compressing ~76MB every night just to
    # store an identical copy wastes disk that grows with the photo count.
    # Fingerprint the directory and hardlink to the previous tarball when
    # nothing changed -- every retained day still resolves to a real file.
    FP=$(find "$UPLOADS_DIR" -type f -printf '%p %s %T@\n' | sort | sha256sum | cut -d' ' -f1)
    PREV_TAR="$(ls -1t "$UP_DIR"/uploads_*.tar.gz 2>/dev/null | head -1 || true)"
    PREV_FP=""
    [ -n "$PREV_TAR" ] && [ -f "$PREV_TAR.fp" ] && PREV_FP="$(cat "$PREV_TAR.fp")"

    if [ -n "$PREV_TAR" ] && [ "$FP" = "$PREV_FP" ]; then
        ln "$PREV_TAR" "$TAR"
        log "uploads unchanged: hardlinked to $(basename "$PREV_TAR")"
    else
        tar -czf "$TAR.part" -C "$(dirname "$UPLOADS_DIR")" "$(basename "$UPLOADS_DIR")" \
            || { rm -f "$TAR.part"; die "uploads tar failed"; }
        mv "$TAR.part" "$TAR"
        log "uploads OK: $(basename "$TAR") $(stat -c %s "$TAR")B, $(ls -1 "$UPLOADS_DIR" | wc -l) files"
    fi
    echo "$FP" > "$TAR.fp"
else
    log "WARNING: uploads dir $UPLOADS_DIR not found, skipped"
fi

# ------------------------------------------------------- row-count tripwire
# Record what we just backed up, and compare against the previous run. A dump
# of a wiped database is a perfectly valid dump -- the only way to notice is to
# see that the rows went away.
COUNTS="$DUMP.counts"
for t in $WATCHED_TABLES; do
    n=$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -tAc \
            "select count(*) from $t" 2>/dev/null || echo "?")
    printf '%s %s\n' "$t" "$n" >> "$COUNTS"
done
log "row counts: $(tr '\n' ' ' < "$COUNTS")"

PREV="$(ls -1t "$DB_DIR"/*.counts 2>/dev/null | grep -v "^$COUNTS$" | head -1 || true)"
ALARM=0
if [ -n "$PREV" ]; then
    while read -r t now; do
        was=$(awk -v k="$t" '$1==k {print $2}' "$PREV")
        case "${was:-?}${now}" in *'?'*) continue ;; esac
        [ "$was" -gt 0 ] 2>/dev/null || continue
        if [ "$(( now * 100 / was ))" -lt "$(( 100 - MAX_ROW_DROP_PCT ))" ]; then
            printf '%s ALARM: table %s went from %s rows to %s since %s\n' \
                "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$t" "$was" "$now" "$(basename "$PREV")" >&2
            ALARM=1
        fi
    done < "$COUNTS"
fi

# ---------------------------------------------------------------- retention
# Keep a Sunday copy for the longer window before pruning the dailies.
if [ "$(date -u +%u)" = "7" ]; then
    cp "$DUMP" "$WEEKLY_DIR/" && log "kept weekly copy"
    [ -f "$TAR" ] && cp "$TAR" "$WEEKLY_DIR/"
fi

find "$DB_DIR"     -name '*.counts'  -mtime "+$DAILY_KEEP_DAYS"  -delete
find "$DB_DIR"     -name '*.dump'    -mtime "+$DAILY_KEEP_DAYS"  -delete
find "$UP_DIR"     -name '*.tar.gz'  -mtime "+$DAILY_KEEP_DAYS"  -delete
find "$UP_DIR"     -name '*.tar.gz.fp' -mtime "+$DAILY_KEEP_DAYS" -delete
find "$WEEKLY_DIR" -type f           -mtime "+$WEEKLY_KEEP_DAYS" -delete
find "$DB_DIR" "$UP_DIR" -name '*.part' -mtime +1 -delete   # stale partials

log "backup complete -- $(ls -1 "$DB_DIR"/*.dump 2>/dev/null | wc -l) daily dumps retained"

# Single-line status anyone can eyeball, since cron mail needs an MTA that may
# not exist on this host.
if [ "$ALARM" -eq 0 ]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) OK $(basename "$DUMP")" > "$BACKUP_ROOT/STATUS"
else
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ALARM row counts collapsed -- see backup.log" > "$BACKUP_ROOT/STATUS"
fi

# The backup is kept either way; a post-disaster snapshot is still worth having
# and the pre-disaster dumps are safe in retention. But make the alarm loud.
if [ "$ALARM" -ne 0 ]; then
    echo "One or more watched tables lost most of their rows. The backup was kept." >&2
    echo "Check the site, then restore with: ops/restore.sh $DB_DIR/<earlier>.dump" >&2
    exit 3
fi
