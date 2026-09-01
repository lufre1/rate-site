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

# Host health -- see "Host memory" and "Crash forensics"
cat /var/log/rate-site/STATUS                      # last boot clean? disk? swap?
tail -f /var/log/rate-site/memwatch.log            # live memory sampler
ls -t /var/log/rate-site/boot-reports | head -1    # newest crash post-mortem
./ops/check-host.sh                                # disk / swap / guards / API
./ops/dev-down.sh                                  # stop dev to free headroom
docker builder prune -f --filter until=168h        # build cache (was 13.98 GB)
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
- **Multi-item rows**: a row with no `<strong>` whose description cell holds `MULTI_ITEM_MIN_LINES`+ individually priced lines (CGiN's "Heute : Grillfest") is exploded into one dish per line, so each is rateable on its own. Price classifies the type — under `SIDE_PRICE_MAX` (2,00 €) is a `side`, above it a `main` — and the per-item diet word supplies the tag, because the row's single `sp_hin` image describes the whole block and would label the Bratwurst vegan. Prices are stripped; `_extract_and_create_sides` is skipped for these rows (their decimal commas shred a comma split)
- **English is dropped for multi-item rows**: the English page serves Last Minute boilerplate in CGiN's Grillfest slot, so `LAST_MINUTE_RE` rejects it by content and the UI falls back to German. The older `last minute` skip only inspects the type cell

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
- **`mem_limit` / `memswap_limit` / `oom_score_adj` / the backend `healthcheck`
  live in the shared `docker-compose.yml`**, so they apply to *both* stacks;
  `docker-compose.dev.yml` halves the two large ones. Unlike `ports`, `volumes`
  and `env_file` these are scalars that **replace** rather than append, so they
  need no `!override`.
- **`restart: unless-stopped`** on all services. The 2026-08-31 dev outage was a
  host reboot into a new kernel; nothing had a restart policy, so both stacks
  stayed down.

Verify at any time:
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml config | head -1   # -> name: rate-site-dev
docker inspect rate-site-backend-1 --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}'
docker ps --format '{{.Names}}\t{{.Ports}}'   # prod :80 only, dev :8080 only
```

## Host memory and the 2026-08-31 / 2026-09-01 lock-ups

The VM is 3.8 GiB, 4 vCPU, and until 2026-09-01 had **zero swap**. It hard-locked
twice in two days -- SSH gone, site gone, recovered only by a hard reset from the
provider console.

**The evidence, all of it negative in a specific and useful way:**

- `journalctl -b -1` ends at `Sep 01 12:05:28` and `-b -2` at `Aug 31 11:20:43`,
  both mid-sentence. Neither has `shutdown.target`, `systemd-shutdown` or an
  unmount sequence. The only clean shutdown in the whole journal is from June 2025.
- `last -x` records the login sessions as `- crash`. Postgres logged
  `database system was not properly shut down` on the way back up.
- All containers came back with `RestartCount: 0` and `OOMKilled: false`, and
  their `FinishedAt` is stamped *after* the next boot with
  `error unmounting container ... layer not mounted` -- the signature of a kill
  that gave dockerd no chance to record an exit.
- **Not one `oom-kill` line anywhere** in the persistent journal back to June 2025;
  `/proc/vmstat` `oom_kill 0`; every container cgroup `oom_kill 0`.

**Why nothing was recorded, and why that was fixable:** journald's default
`SyncIntervalSec` for persistent storage is **5 minutes**. The proof it was
buffering rather than the machine stopping at 12:05:28 is in the Postgres
container's own log, which has the database alive at **12:10:45** -- five minutes
past journald's last written line. Every crash so far destroyed its own evidence.

**Reading of the failure (revised 2026-09-01 after reading the serial console --
see "Platform risk factors"): CPU starvation via lock-holder preemption is now
the leading candidate, ahead of memory.** The original reading was a swapless
reclaim livelock. With no swap the kernel's
only reclaim target is file-backed memory, including the text pages of running
binaries; it evicts and instantly refaults them, "successfully" reclaims forever,
and never reaches `select_bad_process()`. The kernel OOM killer cannot save you
from this because it is never scheduled -- which is exactly why there is no
oom-kill line. **This is not proven.** A hypervisor-side stop or a virtio-balloon
reclaim would look the same from in here; `psi_full` and `memtotal` in
`ops/memwatch.py` exist to tell those apart next time (see "Crash forensics").

**Measured, 2026-09-01, after the fixes below:** a full fresh frontend build
(`npm install` 68.8s + `npm run build` 10.1s, both uncached) took `MemAvailable`
no lower than **1984 MiB of 3914**, with `psi_full` flat at 0.0 and no earlyoom
kills. So the build *alone* does not explain the lock-ups. Note what else was
resident at crash time: `mcr.microsoft.com/playwright` (2.83 GB image) and
`zenika/alpine-chrome`, i.e. headless browser automation, plus a `docker compose
build`. That combination is a far better fit than the build on its own.

### The rules

- **Never `docker compose up -d --build` by hand.** It is doubly wrong: it deploys
  *prod* (see "Deployment Policy"), and it is what was running before both
  lock-ups. It is the last line of `~/.bash_history` from 2026-08-31.
- Builds go through `ops/dev-up.sh --build` or `ops/pre-deploy.sh --build`. Both
  now call `require_build_headroom()` and **refuse to start below 1500 MiB
  `MemAvailable`** (`MIN_BUILD_MEM_MB` in `ops/lib.sh`).
- `ops/dev-down.sh` stops the dev stack when you need headroom. It uses `stop`,
  never `down` -- see "Never `docker compose down -v`".

### What is in place now

| Guard | Where |
|---|---|
| 2 GiB swap, `vm.swappiness=10`, `vm.watermark_scale_factor=200` | `/swapfile`, `/etc/fstab`, `/etc/sysctl.d/60-rate-site-memory.conf` |
| `earlyoom`, kills before the livelock develops | `/etc/default/earlyoom` |
| Frontend build capped | `frontend/Dockerfile` (`GENERATE_SOURCEMAP=false`, `NODE_OPTIONS=--max-old-space-size=768`) |
| Build context 337 MB -> 2.91 kB | `frontend/.dockerignore` |
| Per-container ceilings + `oom_score_adj` | `docker-compose.yml`, halved in `docker-compose.dev.yml` |
| Build-headroom preflight | `ops/lib.sh`, called from both deploy scripts |

**earlyoom notes, both learned the hard way:** its own `-p` flag *fails* on Debian
(`Could not set priority: Permission denied`) because the shipped unit uses
`DynamicUser=true` and the daemon has already dropped privileges by then --
`ops/systemd/earlyoom-priority.conf` sets `Nice=-20` / `OOMScoreAdjust=-100` from
systemd instead, which works. And the unit is
`ExecStart=/usr/bin/earlyoom $EARLYOOM_ARGS`, which systemd word-splits **without**
shell quote processing, so the `--avoid`/`--prefer` regexes in
`/etc/default/earlyoom` deliberately contain no spaces and no inner quotes.

## Crash forensics

Installed 2026-09-01, because both lock-ups were unexplainable after the fact.
Install or re-install everything with `sudo ./ops/install-host-monitoring.sh`
(idempotent; unit files are version-controlled in `ops/systemd/`).

- **`ops/memwatch.py`** -- a resident sampler, every 5s (1s once `MemAvailable`
  < 900 MiB or `psi_full` > 5). It **forks nothing, never touches the docker
  socket, and `fsync()`s every line**: forking is the operation that fails during
  a livelock, the docker socket is the one that blocks, and a line only in the
  page cache does not survive a hard reset. It `mlockall()`s itself and runs at
  `OOMScoreAdjust=-900` so it is not a victim of what it is recording. Container
  count comes from counting `docker-*.scope` under `/sys/fs/cgroup/system.slice`.
- **`ops/boot-report.sh`** -- runs once per boot, decides whether the *previous*
  boot ended cleanly, and if not writes a full post-mortem to
  `/var/log/rate-site/boot-reports/`.
- **journald now syncs every 10s**, not every 5 minutes
  (`/etc/systemd/journald.conf.d/10-sync.conf`).
- **logrotate** (`/etc/logrotate.d/rate-site`) needs its `su root cloud` line --
  the log directory is `2775 root:cloud` so the cron scripts can write there, and
  logrotate silently refuses group-writable parents without it. It rotates by
  SIGHUP, not `copytruncate`, because memwatch holds an `O_APPEND` fd.

### Reading it after a crash

```bash
cat /var/log/rate-site/STATUS                      # was the last boot clean?
ls -t /var/log/rate-site/boot-reports | head -1    # newest post-mortem
grep -n '^# boot' /var/log/rate-site/memwatch.log  # boot boundaries

# The samples immediately ABOVE the newest '# boot' line are the last
# seconds-to-minutes before the machine died.
awk '/^# boot /{n=NR} {a[NR]=$0} END{for(i=n-60;i<n;i++) print a[i]}' \
    /var/log/rate-site/memwatch.log
```

**The verdict is in the last few samples:**

- `psi_mem_full` climbing (10 -> 40 -> 90), `memavail` collapsing, `majflt_s` in
  the thousands -> **swapless reclaim livelock in the guest.** The guards above
  are the right ones.
- `steal_pct` climbing and/or `psi_cpu` high **while memory is fine** -> **the
  host is starving us of CPU.** This is the leading theory; see "Platform risk
  factors" below. A GWDG conversation, not a repo fix.
- `memtotal` falling between consecutive samples -> **virtio-balloon reclaim**;
  the host took RAM away. Also a hypervisor conversation.
- everything flat and healthy in the final line, then the log just stops -> **the
  VM was stopped or destroyed from outside.**

### Pulling the serial console log

The kernel cmdline carries `console=ttyS0`, so a panic goes to the serial console
and **only GWDG captures it** (Horizon -> Instances -> webserver-1 -> Log).
**Pull it BEFORE hard-resetting** -- the reset wipes the buffer, which is why the
log retrieved on 2026-09-01 covered only the post-crash boot and told us nothing
about either lock-up.

### Platform risk factors (from the serial console, 2026-09-01)

None of these are visible from inside a running guest, and together they are a
better fit for the lock-ups than memory ever was:

- **`kvm-guest: PV spinlocks disabled, no host support`** -- the big one. Without
  paravirtualised spinlocks, a vCPU preempted by the hypervisor while holding a
  kernel spinlock leaves the other three spinning on it. Under all-core load --
  a build -- that lock-holder preemption stalls the entire machine, logs nothing,
  and involves no memory pressure whatsoever. That is exactly the shape of both
  lock-ups, and it explains why the frontend build measured on 2026-09-01 peaked
  at only 1984 MiB `memavail` with `psi_full` flat at 0.0.
- **Steal time is already non-zero** (569 ticks within an hour of boot), so the
  host does take CPU from this guest.
- **`noapic` on the kernel cmdline** -> `ACPI: Skipping IOAPIC probe` and
  `Not enabling interrupt remapping`. Legacy PIC routing on a modern KVM guest is
  unusual and worth questioning.
- **AMD Zen1 EPYC** (family 0x17 model 0x1) with `FPDSS` and `DIV0` errata
  mitigations active, and `tsc: Marking TSC unstable due to TSCs unsynchronized`.
- `kvm_amd` is loaded in the guest with `Nested Paging disabled`, though nothing
  uses it (`usecount 0`).

**What to ask GWDG:** whether the compute host can enable PV spinlocks
(`kvm_amd` / host CPU model exposing the KVM PV feature bits), whether `noapic`
is still needed in the image's cmdline, and whether the host was oversubscribed
or under maintenance during `2026-08-31 11:29-11:34` and `2026-09-01 12:10-12:41`.

## Host and stack health checks

No MTA on this box, so cron mail goes nowhere and `/var/log/rate-site/STATUS` is
the record -- the same pattern as `/home/cloud/backups/STATUS`.
`show_host_status()` in `ops/lib.sh` prints both at the top of every deploy.

- **`ops/check-host.sh`** (cron 09:05) -- disk, swap, build cache, memwatch and
  earlyoom alive, prod `/api/v1/health/db` reachable. Exit 3 + `ALARM` on trouble.
- **`ops/check-stack.sh`** (cron every 5 min) -- **Compose does not restart a
  container just because it is unhealthy**; `restart: unless-stopped` only reacts
  to the process exiting, so a hung uvicorn stays "Up" forever. This closes that
  gap: two consecutive unhealthy observations restart that one container. It
  deliberately ignores `/api/v1/health/db` failures, because restarting the
  backend cannot fix a broken database and would be a restart loop during an outage.
- Both write STATUS through `write_status()` in `ops/lib.sh`, which writes to a
  temp file and renames. A plain `>` fails with "Permission denied" for whichever
  of root (boot-report, at boot) and `cloud` (cron) did not create the file.

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
9. **A bare `docker compose up -d --build` is doubly wrong**: it deploys prod,
   and it is what was running before both host lock-ups. Use the ops scripts.
10. **Docker `log-opts` apply at container *creation*.** Writing
    `/etc/docker/daemon.json` changes nothing until the containers are recreated
    through the ops scripts; `log-driver` also needs a daemon *restart*, not a
    reload. Verify with
    `docker inspect -f '{{json .HostConfig.LogConfig}}' rate-site-backend-1`.
11. **`frontend/.dockerignore` is a separate file from the root one**, because
    `docker-compose.yml` sets `context: ./frontend`. Without it, 337 MB of host
    `node_modules` enters the build context and `COPY . .` overwrites the
    dependencies `npm install` just produced one layer earlier.
12. **`frontend/node_modules` and `frontend/build` on the host are root-owned
    build artefacts** left by a stray containerised build on 2026-09-01. They are
    no longer in the build context, so they are harmless -- but they are not
    yours, and `sudo` is needed to remove them.
13. **PID 1 in a container ignores `kill -STOP 1` sent from inside** (the kernel
    shields a PID namespace's init from unhandled signals from within). To
    simulate a hung backend, SIGSTOP the host-side pid from
    `docker inspect -f '{{.State.Pid}}'`.

## Mobile Behavior

- Viewport: `width=device-width, initial-scale=1.0, maximum-scale=3.0`
- Base font: `16px` (1rem = 16px), uses `rem` throughout
- Buttons ≥ 48px touch targets (`MinWidth: 48` in `StarPicker`)
- No horizontal scroll (`overflow-x: hidden` in `index.css:14`)
