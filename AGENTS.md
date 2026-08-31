# Mensa Rating System — AGENTS.md

## Architecture

- **Frontend**: React (Create React App, Nginx serve), **Backend**: FastAPI (Python 3.11), **DB**: PostgreSQL 15
- **No router**: views are toggled with boolean state in `App.js` (`showImpressum`, `showAccount`). Shared helpers (`API`, token storage, `StarPicker`, `formatRelativeDate`) live in `frontend/src/shared.js` so `Account.js` doesn't import from its own parent
- **All API routes under `/api/v1/`** — frontend calls `http://localhost:8000` by default, but in prod through nginx on `/api/v1`
- **API URL from env**: `REACT_APP_API_URL` (set at build time in `frontend/Dockerfile:4`)
- **Language support**: Each meal stores `name_de`, `name_en`, `description_de`, `description_en`; API returns `lang` parameter (default `de`)
- **Dev instance**: http://141.5.100.246:8080/ — all development updates applied here first. Start it with `./ops/dev-up.sh`. Dev has its own database (`mensa_dev`), its own uploads volume and its own proxy config; see "How dev and prod are kept apart".

## Database Schema Details (Non-Obvious)

- **Meal deduplication**: `(date, mensa_id, name)` must be unique. `scrape_menus()` deletes stale rows but preserves rows with existing ratings
- **German/English merge**: Scraper pairs DE/EN rows positionally. Missing EN doesn't wipe existing EN data
- **Rating identity**: every rating goes through `rating_identity()` in `main.py`. Signed in -> the real username and a `user_id`; anonymous -> a `generate_funny_name()` string and `user_id = NULL`. All three creation routes (`ratings`, `ratings-with-photo`, `side-ratings`) use it — change it there, not per-route
- **Side ratings aggregation**: `side-ratings` are **global per side name** across all meals in a mensa, not per-meal; API returns aggregated stats

## Key Commands

> **Never run pytest inside the `backend` container.** The suite drops and
> recreates tables against whatever `DATABASE_URL` is in scope, and in that
> container it is production. This destroyed the prod database on 2026-08-31.
> `conftest.py` now aborts if you try, but use the test stack below.

```bash
# Deploy to PROD (takes a backup first, then recreates the stack)
./ops/pre-deploy.sh            # add --build to rebuild images

# Run the whole test suite -- own compose project, own throwaway Postgres
docker compose -p rate-site-test -f docker-compose.test.yml run --rm tests

# Run one test file
docker compose -p rate-site-test -f docker-compose.test.yml run --rm tests \
    python -m pytest tests/test_db_integrity.py -v

# Start / refresh DEV on port 8080
./ops/dev-up.sh                # add --build after code changes

# Backups -- default to PROD; RATE_ENV=dev switches the whole environment
./ops/backup.sh                # manual backup (cron runs this at 03:15 UTC)
RATE_ENV=dev ./ops/backup.sh   # dev, into /home/cloud/backups/dev
./ops/check-backups.sh         # is the newest dump recent and sane?
./ops/restore.sh               # restore newest dump, asks for confirmation
cat /home/cloud/backups/STATUS # one-line result of the last backup

# Update menu data manually (e.g. after DB reset)
docker compose exec backend python -c "from scraper import scrape_menus; scrape_menus()"
```

**Note**: Backend lint (ruff) and frontend tests/build require local development setup — not configured in the Docker images. Frontend build happens during `docker compose build` (uses `REACT_APP_API_URL` Docker arg).

## Testing

- **Where tests run**: always `docker-compose.test.yml`. It uses its own compose
  project, a Postgres named `mensa_test` on tmpfs, and no `.env`, so the prod
  `DATABASE_URL` is never in scope.
- **The safety rail**: `conftest.py` assigns `DATABASE_URL` itself (it never
  inherits one) and calls `assert_disposable()`, which accepts only SQLite or a
  database name ending in `_test`. Anything else aborts at import, before any
  connection is opened. Point `TEST_DATABASE_URL` at a `*_test` database to run
  integration tests; leave it unset and each run gets a private temp SQLite file.
- **Backend unit tests**: `test_auth.py` / `test_api_ratings.py` take a fresh
  per-test SQLite database from the `sqlite_db` fixture. They no longer call
  `drop_all` — isolation comes from the database being new, not from wiping a
  shared one. Do not reintroduce that pattern.
- **Backend integration tests**: need a running backend (`API_BASE_URL`) or the
  `mensa_test` Postgres from the test stack.
- **Frontend unit tests**: Run via `npm test` (default CRA Jest config, looks for `*.test.js`, `*.test.jsx`, `translations.test.js`)
- **Test files**:
  - `test_scraper_alignment.py` — validates DE/EN row alignment, no duplicates, mensa-name consistency
  - `test_db_integrity.py` — validates DB schema, no duplicates, matches official site
  - `test_api_language.py` — validates API multilingual output, no duplicates
  - `test_for_unused_items.py` — verifies backend code is actually in use
  - `test_auth.py` — register/login/session round-trip, anonymous rating still works, cross-user edit/delete is refused
  - `validate-translations.py` — validates translation files structure

## Scraper Behavior

- Fetches **next 7 days** inclusive of today
- Two-stage URL fallback: `alle.html` → per-mensas (`ALIAS_MAP` in `scraper.py:43`)
- Skips: `last minute`, `pastabuffet`, `Selbstbedienung` rows; filters to 4 mensas only
- **Description cleanup**: Removes "oder"/"or" separators between ingredients; normalizes whitespace

## Accounts (Non-Obvious)

- **Optional by design**: login is never required. `ratings.user_id` / `side_ratings.user_id` are nullable, so anonymous rating works exactly as before and every pre-accounts row stays valid
- **No auth dependencies**: passwords use stdlib `hashlib.scrypt` (`backend/auth.py`), tokens use `secrets.token_urlsafe`. No passlib/bcrypt/JWT library — don't add one
- **Bearer tokens, not cookies**: sent as `Authorization: Bearer <token>`, held in `localStorage`. This is what lets the CORS config stay `allow_origins=["*"]` / `allow_credentials=False`. Switching to cookies means rewriting CORS
- **Tokens never expire** — `auth_tokens` rows live until logout. See the `ponytail:` note in `auth.py`
- **`auth.optional_user`** returns the user or `None` (rating routes); **`auth.current_user`** 401s (`/me*`, ownership routes)
- **Ownership**: `owned_rating()` in `main.py` treats `user_id IS NULL` as owned by nobody, so anonymous rows can't be edited via the authenticated routes. The legacy `PATCH /ratings/{id}/comment` predates accounts and stays open for anonymous rows only
- **Favourites are derived, not stored**: there is no favourites table. The UI calls `GET /api/v1/me/ratings?min_rating=4&sort=rating`
- **`get_db` lives in `database.py`** (not `main.py`) so `auth.py` can share it without a circular import
- **Login is not a username oracle**: unknown-user and wrong-password both return the same 401 body. Keep it that way

## Language Resolution (main.py:56)

Priority for each dish (when `lang` param is `en`):
1. `name_en` → `name_de` → `name`  
For `de`:
1. `name_de` → `name`

Same fallback applies to descriptions.

## Nginx Proxy Routes (`nginx-proxy.conf`)

- `/` → `frontend:80`
- `/api/v1` → `backend:8000`

**Note**: The frontend's `nginx.conf` strips `/api/` prefix before proxying to backend (see `location ~ ^/api/(.*)` on line 9).

## Deployment Policy

- When developing a feature, **always test it on the dev/test instance first** — never push to prod.
- **Always ask the user to push to prod**; never deploy to production yourself.
- **Dev instance URL**: http://141.5.100.246:8080/ — all updates must be applied here first during development.
- **Carefully update the docker container** on the dev instance, not the prod container, during development.

Use exactly these invocations — mixing them is what made the prod proxy squat
dev's port 8080 on 2026-08-31:

```bash
./ops/pre-deploy.sh    # PROD  (port 80)  -- backs up first, then deploys
./ops/dev-up.sh        # DEV   (port 8080)
```

Both wrappers hardcode the correct flags. The raw equivalents:

```bash
docker compose -p rate-site -f docker-compose.yml up -d --force-recreate --remove-orphans
docker compose -p rate-site-dev --env-file .env.dev \
    -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

**Never `docker compose down -v`** — `-v` deletes the `postgres_data` volume.

## How dev and prod are kept apart

Merging the dev override into the prod project (forgetting `-p`) is what made the
prod proxy publish 8080 on 2026-08-31. That is now prevented by mechanism, not
by remembering:

- **`docker-compose.dev.yml` pins `name: rate-site-dev`.** A `name:` in the last
  `-f` file wins, so even a `-p`-less invocation lands on the dev project. An
  explicit `-p` still overrides, as it should.
- **`!override` on `ports`, `env_file` and `volumes`.** Compose *appends* these
  keys by default, which is the actual mechanism behind all three old bugs:
  dev's port was added to prod's; `.env.dev` was read after `.env` so it could
  only shadow prod keys (prod's owner credential was reaching the dev db
  container); and dev's uploads mount was added to the shared bind mount.
- **Dev has its own database name, `mensa_dev`.** Both were `mensa_db`, so
  `ops/restore.sh`'s type-the-name confirmation asked for the same string in
  either environment and could not discriminate.
- **Dev has its own uploads volume** (`rate-site-dev_dev_uploads`). Previously
  both stacks bind-mounted `./backend/uploads`, and `main.py:999` deletes photos
  with `os.remove()` — so a delete in dev removed a real production photo while
  prod's database row survived, leaving a silently broken image.
- **Dev has its own proxy config**, `nginx-proxy.dev.conf`. One shared file meant
  editing it to try something in dev changed prod's config on the next reload.
- **`.dockerignore` excludes `backend/uploads/`.** `COPY backend/ .` was baking
  the 50 real user photos into every image, and Docker seeds a fresh named
  volume from the image — which is how dev's new uploads volume came up holding
  copies of production photos.
- **`ops/lib.sh` selects an environment** via `RATE_ENV` (default `prod`), and
  `assert_env_consistent()` aborts unless the target container's compose project
  *and* its database both match. A stray `DB_CONTAINER` cannot be talked past.
- **`restart: unless-stopped`** on all services. The 2026-08-31 dev outage was a
  host reboot into a new kernel; nothing had a restart policy, so both stacks
  stayed down.

Verify at any time:
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml config | head -1   # -> name: rate-site-dev
docker inspect rate-site-backend-1 --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}'
docker ps --format '{{.Names}}\t{{.Ports}}'   # prod :80 only, dev :8080 only
```

## Backups

Added 2026-08-31, after the production database was dropped with no backup in
existence. Scripts live in `ops/`, config in `ops/lib.sh`.

- **Environments**: all `ops/` scripts default to prod. `RATE_ENV=dev` switches
  container, env file and backup root together. Dev dumps go to
  `/home/cloud/backups/dev`; dev's uploads live in a docker volume and are not
  backed up (they are disposable).
- **Schedule** (user crontab): `backup.sh` 03:15 UTC daily, `check-backups.sh` 09:00. Prod only.
- **What is kept**: `pg_dump -Fc` of `mensa_db` plus a tarball of
  `backend/uploads/` — `ratings.photo_url` points into it, so a DB-only restore
  is half a restore. 14 dailies, Sunday copies kept 8 weeks, in `/home/cloud/backups`.
- **Written safely**: dumped to `.part` and renamed only after `pg_restore --list`
  confirms it parses and contains tables. Unchanged uploads are hardlinked to the
  previous tarball instead of re-archived.
- **Row-count tripwire**: each dump records row counts for `ratings`,
  `side_ratings`, `users`, `comment_votes`. If a table loses >50% of its rows
  since the last backup, the script still keeps the dump (a post-incident
  snapshot is worth having) but exits 3 and writes `ALARM` to
  `/home/cloud/backups/STATUS`. **This is the check that would have caught the
  2026-08-31 incident** — a dump of a wiped database is a perfectly valid dump,
  and size alone cannot tell it apart from a small healthy one.
- **No MTA on this host**, so cron mail goes nowhere. `STATUS`, `backup.log` and
  `check.log` in `/home/cloud/backups` are the actual record — check them.
- **Restore drill**: `ops/restore.sh <dump> --force` with `DB_CONTAINER` /
  `DB_NAME` pointed at the test stack. Repeat after any schema change; an
  untested backup is not a backup.

## Common Pitfalls

1. **Duplicate rows**: After DB reset, call `scrape_menus()` to regenerate. Stale rows with ratings are preserved.
2. **English data loss**: Scraper never overwrites existing `name_en` if new EN source is empty — protects against temporary page outages.
3. **Port conflict**: Host port 80 must be free (`sudo systemctl stop nginx` if needed).
4. **Frontend build**: `REACT_APP_API_URL` must be set at build time via Docker arg (default `http://localhost:8000`).
5. **Database health**: Backend waits for `pg_isready` (see `docker-compose.yml:11-16`); wait ~5-10s after `docker compose up` before API is ready.
6. **Frontend dev**: `npm start` needs `REACT_APP_API_URL` set; defaults to `http://localhost:8000`.
7. **Running tests in the prod container destroys the database.** See "Key
   Commands". The rail in `conftest.py` blocks it now; do not weaken it, and
   never restore `os.environ.setdefault("DATABASE_URL", ...)` — `setdefault`
   yields to the ambient value, which is exactly how prod got dropped.
8. **Backups are local-only** (`/home/cloud/backups`, same disk as the DB).
   They cover a bad command, not the loss of the VM.

## Mobile Behavior

- Viewport: `width=device-width, initial-scale=1.0, maximum-scale=3.0`
- Base font: `16px` (1rem = 16px), uses `rem` throughout
- Buttons ≥ 48px touch targets (`MinWidth: 48` in `StarPicker`)
- No horizontal scroll (`overflow-x: hidden` in `index.css:14`)
