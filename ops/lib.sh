# Shared config for the ops scripts. Sourced, not executed.
#
# Everything is overridable by environment variable so the scripts can be
# pointed at the test stack for a restore drill.

RATE_SITE_DIR="${RATE_SITE_DIR:-/home/cloud/rate-site}"
BACKUP_ROOT="${BACKUP_ROOT:-/home/cloud/backups}"
DB_CONTAINER="${DB_CONTAINER:-rate-site-db-1}"
UPLOADS_DIR="${UPLOADS_DIR:-$RATE_SITE_DIR/backend/uploads}"

# Read DB name/user from .env if present, else fall back to the compose defaults.
if [ -f "$RATE_SITE_DIR/.env" ]; then
    DB_NAME="${DB_NAME:-$(grep -E '^POSTGRES_DB=' "$RATE_SITE_DIR/.env" | cut -d= -f2-)}"
    DB_USER="${DB_USER:-$(grep -E '^DB_USER=' "$RATE_SITE_DIR/.env" | cut -d= -f2-)}"
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

log()  { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die()  { printf '%s ERROR: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; exit 1; }
