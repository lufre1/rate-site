#!/usr/bin/env bash
#
# Restore a dump produced by ops/backup.sh.
#
#   ops/restore.sh                          # restore newest into prod (asks first)
#   ops/restore.sh path/to/x.dump           # restore a specific dump
#   DB_CONTAINER=... DB_NAME=mensa_test \
#       ops/restore.sh path/to/x.dump --force   # restore into the test stack, no prompt
#
# Restoring is destructive: --clean --if-exists drops the existing objects
# first. That is the point, but it means the target must be the one you meant.
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/lib.sh"

DUMP=""
FORCE=0
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        *)       DUMP="$arg" ;;
    esac
done

[ -n "$DUMP" ] || DUMP="$(ls -1t "$BACKUP_ROOT"/db/*.dump 2>/dev/null | head -1 || true)"
[ -n "$DUMP" ] || die "no dump given and none found in $BACKUP_ROOT/db"
[ -f "$DUMP" ] || die "no such dump: $DUMP"

docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null | grep -q true \
    || die "database container '$DB_CONTAINER' is not running"

echo "About to restore into:"
echo "    container : $DB_CONTAINER"
echo "    database  : $DB_NAME"
echo "    from dump : $DUMP ($(stat -c %s "$DUMP")B, $(date -r "$DUMP" -u +%Y-%m-%dT%H:%M:%SZ))"
echo "This DROPS the existing objects in that database first."
if [ "$FORCE" -ne 1 ]; then
    printf 'Type the database name to confirm: '
    read -r reply
    [ "$reply" = "$DB_NAME" ] || die "confirmation did not match -- nothing was changed"
fi

log "restoring..."
docker exec -i "$DB_CONTAINER" pg_restore -U "$DB_USER" -d "$DB_NAME" --clean --if-exists < "$DUMP"
log "restore finished"

# --clean drops and recreates the tables, so any grants they had are gone. A
# dump taken before ops/setup-db-roles.sh ran never had them in the first place.
# Either way the app role would come back with no access and the site would 500
# after an otherwise successful restore -- so re-apply the grants here.
APP_ROLE="${APP_ROLE:-mensa_app}"
if docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -tAc \
       "select 1 from pg_roles where rolname='$APP_ROLE'" | grep -q 1; then
    log "re-applying grants for $APP_ROLE"
    docker exec -i "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -q -v ON_ERROR_STOP=1 <<SQL
GRANT USAGE ON SCHEMA public TO "$APP_ROLE";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA public TO "$APP_ROLE";
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA public TO "$APP_ROLE";
REVOKE CREATE ON SCHEMA public FROM "$APP_ROLE";
SQL
    log "grants re-applied"
fi

docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "\dt"

echo
echo "Photos are NOT restored by this script. If you need them:"
echo "    tar -xzf $BACKUP_ROOT/uploads/uploads_<same-stamp>.tar.gz -C $(dirname "$UPLOADS_DIR")"
