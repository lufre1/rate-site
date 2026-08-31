# Shared config for the ops scripts. Sourced, not executed.
#
# Every script used to default to production unconditionally, and the only
# guard on ops/restore.sh was a "type the database name" prompt -- which asked
# for the same string ("mensa_db") in both environments. Dev's database is now
# `mensa_dev`, and this file selects a whole environment at once:
#
#   ops/backup.sh                 # prod (default -- cron relies on this)
#   RATE_ENV=dev ops/backup.sh    # dev
#
# assert_env_consistent() then checks the chosen container really belongs to the
# chosen environment, so a stray DB_CONTAINER cannot be talked past.

RATE_SITE_DIR="${RATE_SITE_DIR:-/home/cloud/rate-site}"
RATE_ENV="${RATE_ENV:-prod}"

case "$RATE_ENV" in
    prod)
        _DEF_CONTAINER="rate-site-db-1"
        _DEF_PROJECT="rate-site"
        _ENV_FILE="$RATE_SITE_DIR/.env"
        # Unchanged path: the crontab and the existing dumps live here.
        _DEF_BACKUP_ROOT="/home/cloud/backups"
        _DEF_UPLOADS="$RATE_SITE_DIR/backend/uploads"
        ;;
    dev)
        _DEF_CONTAINER="rate-site-dev-db-1"
        _DEF_PROJECT="rate-site-dev"
        _ENV_FILE="$RATE_SITE_DIR/.env.dev"
        _DEF_BACKUP_ROOT="/home/cloud/backups/dev"
        # Dev keeps uploads in the rate-site-dev_dev_uploads volume, not on the
        # host. Empty means "skip the uploads backup"; dev photos are disposable.
        _DEF_UPLOADS=""
        ;;
    *)
        echo "ERROR: RATE_ENV must be 'prod' or 'dev', got '$RATE_ENV'" >&2
        exit 1
        ;;
esac

DB_CONTAINER="${DB_CONTAINER:-$_DEF_CONTAINER}"
BACKUP_ROOT="${BACKUP_ROOT:-$_DEF_BACKUP_ROOT}"
UPLOADS_DIR="${UPLOADS_DIR-$_DEF_UPLOADS}"   # no ':' -- an explicit empty value is honoured

# Database name/user come from the SELECTED environment's file.
if [ -f "$_ENV_FILE" ]; then
    DB_NAME="${DB_NAME:-$(grep -E '^POSTGRES_DB=' "$_ENV_FILE" | cut -d= -f2-)}"
    DB_USER="${DB_USER:-$(grep -E '^DB_USER=' "$_ENV_FILE" | cut -d= -f2-)}"
fi
DB_NAME="${DB_NAME:-mensa_db}"
DB_USER="${DB_USER:-user}"

# Catches a truncated/aborted dump. It deliberately does NOT try to detect a
# wiped database by size -- a schema-only dump of this app is ~25KB, close
# enough to a small real one that any threshold would either false-alarm or
# miss. The row-count comparison in backup.sh does that job instead.
MIN_DUMP_BYTES="${MIN_DUMP_BYTES:-5000}"

# Alarm if a table loses more than this fraction of its rows since the last
# backup. This is the check that would have caught 2026-08-31: the dump itself
# still succeeds and is kept, but the script exits non-zero so cron mails you.
MAX_ROW_DROP_PCT="${MAX_ROW_DROP_PCT:-50}"

# Tables whose contents are irreplaceable (user-generated, not re-scrapable).
WATCHED_TABLES="${WATCHED_TABLES:-ratings side_ratings users comment_votes}"

DAILY_KEEP_DAYS="${DAILY_KEEP_DAYS:-14}"
WEEKLY_KEEP_DAYS="${WEEKLY_KEEP_DAYS:-56}"

log()  { printf '%s [%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$RATE_ENV" "$*"; }
die()  { printf '%s [%s] ERROR: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$RATE_ENV" "$*" >&2; exit 1; }

require_running() {
    docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null | grep -q true \
        || die "database container '$DB_CONTAINER' is not running"
}

# The real guard. Two independent checks, so neither a mistyped DB_CONTAINER nor
# a mistyped DB_NAME can send a destructive operation at the wrong environment.
assert_env_consistent() {
    require_running

    local project
    project="$(docker inspect -f \
        '{{index .Config.Labels "com.docker.compose.project"}}' "$DB_CONTAINER" 2>/dev/null)"
    [ "$project" = "$_DEF_PROJECT" ] || die \
        "container '$DB_CONTAINER' belongs to compose project '$project', but RATE_ENV=$RATE_ENV expects '$_DEF_PROJECT'."

    docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d postgres -tAc \
        "select 1 from pg_database where datname='$DB_NAME'" 2>/dev/null | grep -q 1 \
        || die "container '$DB_CONTAINER' has no database named '$DB_NAME' (RATE_ENV=$RATE_ENV)."
}
