#!/usr/bin/env bash
#
# Split the single all-powerful database role in two:
#
#   owner    (existing, e.g. `user`)  -- owns the tables, runs init_db()
#   app role (mensa_app)              -- SELECT/INSERT/UPDATE/DELETE only
#
# The request path connects as the app role, so DDL against production fails at
# the database with "must be owner of table" no matter what the application or
# a stray test does. The safety rail in backend/tests/conftest.py is a
# convention; this is enforcement.
#
# Idempotent -- re-run it after adding tables.
#
#   ops/setup-db-roles.sh <app_password>
#   DB_CONTAINER=... DB_NAME=... DB_USER=... ops/setup-db-roles.sh <app_password>
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/lib.sh"

APP_ROLE="${APP_ROLE:-mensa_app}"
APP_PASSWORD="${1:-}"
[ -n "$APP_PASSWORD" ] || die "usage: $0 <password-for-$APP_ROLE>"
case "$APP_ROLE" in *[!a-zA-Z0-9_]*) die "APP_ROLE must be alphanumeric/underscore" ;; esac

docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null | grep -q true \
    || die "database container '$DB_CONTAINER' is not running"

log "granting $APP_ROLE DML-only access to $DB_NAME (owner: $DB_USER)"

# The password goes in via -v / :'apppw' so psql quotes it; everything else is
# an identifier we control.
docker exec -i "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 \
    -v apppw="$APP_PASSWORD" <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$APP_ROLE') THEN
        CREATE ROLE "$APP_ROLE" LOGIN;
    END IF;
END \$\$;
ALTER ROLE "$APP_ROLE" LOGIN PASSWORD :'apppw';

GRANT CONNECT ON DATABASE "$DB_NAME" TO "$APP_ROLE";

-- Nobody gets the schema by default; the app gets USAGE but never CREATE.
REVOKE ALL    ON SCHEMA public FROM PUBLIC;
GRANT  USAGE  ON SCHEMA public TO   "$APP_ROLE";
REVOKE CREATE ON SCHEMA public FROM "$APP_ROLE";

-- Data yes, structure no. No CREATE, no TRUNCATE, no ownership.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA public TO "$APP_ROLE";
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA public TO "$APP_ROLE";

-- Tables the owner adds later (create_all / the CREATE TABLE in init_db)
-- inherit these, so a new table is never silently unreadable.
ALTER DEFAULT PRIVILEGES FOR ROLE "$DB_USER" IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "$APP_ROLE";
ALTER DEFAULT PRIVILEGES FOR ROLE "$DB_USER" IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO "$APP_ROLE";
SQL

log "grants applied"
docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -tAc \
    "select grantee||': '||string_agg(distinct privilege_type, ',' order by privilege_type)
       from information_schema.role_table_grants
      where table_schema='public' and grantee='$APP_ROLE' group by grantee;"
