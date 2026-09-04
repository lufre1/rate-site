# Mensa Rating System — AGENTS.md

## Architecture

- **Frontend**: React (Create React App, Nginx serve), **Backend**: FastAPI (Python 3.11), **DB**: PostgreSQL 15
- **No router**: views are toggled with boolean state in `App.js` (`showImpressum`, `showDatenschutz`, `showAccount`, `showStats`) via `openView()`, which is what keeps them mutually exclusive — add a view in all four places (state, `goHome`, `openView`, the `<main>` ternary) or it will not close when another opens. Shared helpers (`API`, token storage, `StarPicker`, `formatRelativeDate`) live in `frontend/src/shared.js` so `Account.js` doesn't import from its own parent. `frontend/src/Toast.js` exports `ToastProvider`/`useToast`, and the provider is mounted in `index.js` **above** `<App />` rather than inside it — `App` itself needs `notify` for its own failed fetches, and a component cannot consume a context it provides
- **All API routes under `/api/v1/`**. In every deployed stack the frontend calls them **same-origin** — `REACT_APP_API_URL` is **empty**, so `${API}/api/v1/x` is `/api/v1/x` and the proxy's `location /api/v1` sends it straight to the backend. `http://localhost:8000` is only the `npm start` fallback
- **API URL from env**: `REACT_APP_API_URL`, a build-time Docker arg (`frontend/Dockerfile`), inlined by CRA. **`shared.js` reads it with `??`, not `||`** — the correct deployed value is the empty string, which is falsy, so `||` would silently substitute the localhost fallback and point every request at the visitor's own machine. For the same reason `docker-compose.dev.yml` uses `${REACT_APP_API_URL-/api}`, not `:-`
- **The legal pages are code-checked prose.** `Impressum.js` publishes **no
  postal address** — the site is a private, non-commercial project and so not
  a *geschäftsmäßiges* Telemedium under § 5 DDG; `impressum.natureText` is the
  clause that says why, so do not add an address back without it.
  `Datenschutz.js` describes what the code actually stores, and its header
  comment lists which file to re-check for each claim. Changing the log format,
  a localStorage key, the upload handling or the backup retention makes that
  page wrong.
- **Language support**: Each meal stores `name_de`, `name_en`, `description_de`, `description_en`; API returns `lang` parameter (default `de`)
- **Dev instance**: http://141.5.100.246:8080/ — all development updates applied here first. Start it with `./ops/dev-up.sh`. Dev has its own database (`mensa_dev`), its own uploads volume and its own proxy config; see "How dev and prod are kept apart".

## Database Schema Details (Non-Obvious)

- **Meal deduplication**: `(date, mensa_id, name)` must be unique. `scrape_menus()` deletes stale rows but preserves rows with existing ratings
- **German/English merge**: Scraper pairs DE/EN rows positionally. Missing EN doesn't wipe existing EN data
- **Rating identity**: every rating goes through `rating_identity()` in `main.py`. Signed in -> the real username and a `user_id`; anonymous -> a `generate_funny_name()` string and `user_id = NULL`. All three creation routes (`ratings`, `ratings-with-photo`, `side-ratings`) use it — change it there, not per-route
- **Two vote tables, deliberately**: `comment_votes` rates the review *text*; `photo_votes` rates the *picture*. Only `photo_votes` decides which photo represents a dish (`_top_photo_rating()` in `main.py`, used by both `/meals/{id}/top-photo` and `/stats/top-photo`). Until 2026-09-01 the photo was picked by comment votes, so an upvote on a review silently promoted whatever image was attached to it. `photo_votes` started empty — there was no backfill, and comment votes must never be read back into photo ranking
- **Ties in photo ranking go to the oldest photo** (`ORDER BY score DESC, created_at ASC, id ASC`). Every photo sits at 0 until someone votes, so a newest-wins rule would reshuffle the dish picture on every upload. The old code used Python `max()` over an unordered query and broke ties arbitrarily
- **`photo_votes` has a unique `(rating_id, voter_id)` constraint; `comment_votes` does not** — the older table can hold duplicate rows for one voter and was left alone rather than migrated
- **`ratings-breakdown` lists a row if it has a comment OR a photo.** A photo posted without text used to be invisible and unvotable. The route also pins the current top photo into the list even when it falls outside the 15 most recent, otherwise nobody can vote it back down
- **After a successful submit the frontend RE-FETCHES `ratings-breakdown`; it
  does not splice the POST response into the list.** The POST body carries
  none of `date`, `is_recent`, `score`, `vote_direction`, `photo_score`,
  `photo_vote_direction` — and `is_recent` is a **`Europe/Berlin`** date
  comparison (`main.py`) the browser cannot make: a visitor in another timezone,
  or browsing another day, would render the badge wrong. The same GET also
  returns `recent` and `overall` over the same `(name, mensa_id)` grouping the
  card header uses, so both averages move without a reload. A stars-only rating
  legitimately never appears in the list, so the UI says so explicitly
  (`ui.reviewSavedStarsOnly`) rather than pointing at a list that did not change.
- **Neither POST route declares a `response_model`, and that is load-bearing on
  the CLIENT too.** The full row is serialised; the frontend reads `id` to mark
  the submitter's own row and `photo_url` to decide whether a fresh photo can
  take over the dish picture. Adding a `response_model` breaks the UI as well as
  `backend/test_smoke.py:79-81`. Pinned by
  `test_create_rating_response_carries_the_fields_the_ui_reads`.
- **Comment length is capped at `COMMENT_MAX_LENGTH` (1000) on all four write
  paths**, mirrored by `COMMENT_MAX` in `frontend/src/App.js` so the limit is
  visible while typing instead of a rejection afterwards. The legacy
  `PATCH /ratings/{id}/comment` parses a raw dict, so its check is manual. No
  migration — the column is already `Text`, and lowering the number would not
  invalidate rows already stored above it.
- **Side ratings aggregation**: `side-ratings` are **global per side name** across all meals in a mensa, not per-meal; API returns aggregated stats
- **Deleting a rating deletes its votes first.** `comment_votes.rating_id` and
  `photo_votes.rating_id` are FKs with `NO ACTION` and `Rating` declares no
  `relationship()` to either table, so until 2026-09-02 `DELETE
  /api/v1/ratings/{id}` raised an FK violation → opaque 500 for any review
  someone had voted on. The photo file is also unlinked **after** the commit
  now, not before: the old order left a visible review pointing at a file that
  no longer existed when the commit failed
- **Account deletion anonymises, it does not cascade.** `DELETE /api/v1/me`
  sets `user_id = NULL` and stamps a fresh `generate_funny_name()` on the
  user's `ratings`/`side_ratings`, nulls `user_id` on their vote rows (the
  votes stay — they are counted per `voter_id`, and deleting them would
  reshuffle every dish photo), deletes **all** their `auth_tokens`, then the
  `users` row. Nothing in the schema declares `ON DELETE`, so every
  referencing table must be handled explicitly and in that order

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
- **Frontend unit tests**: `npm test` (default CRA Jest config, looks for
  `*.test.js`, `*.test.jsx`, `translations.test.js`). **This host has no node
  installed**, so run them in a throwaway container — mount the repo
  **read-only** and keep `node_modules` in a named volume, or you leave
  root-owned build artefacts in the working tree (see Common Pitfalls 12):
  ```bash
  docker run --rm -v /home/cloud/rate-site/frontend:/src:ro \
      -v rate-site-fe-test-modules:/app/node_modules -w /app \
      -e CI=true -e NODE_OPTIONS=--max-old-space-size=768 node:20-alpine sh -c '
        cp /src/package.json /app/ && rm -rf /app/src /app/public \
          && cp -r /src/src /src/public /app/ && npm install --no-audit --no-fund
        npx react-scripts test --watchAll=false'   # or: npx react-scripts build
  ```
- **`frontend/Dockerfile` sets `CI=true`, so ANY eslint warning fails the
  production build.** Run the `build` variant above before deploying, not just
  the tests: jest tolerates warnings that `npm run build` rejects. One trap
  found this way — an `// eslint-disable-next-line react-hooks/exhaustive-deps`
  comment **fails the build** ("Definition for rule ... was not found"), because
  the build's resolved eslint config does not register that plugin. Fix the
  dependency array instead of disabling the rule.
- **`App.test.js` was repaired on 2026-09-02 and was failing before that.**
  Four of its five tests clicked a `/Bewertungen/i` button that no longer
  exists, one mocked `/side-ratings` (never called any more), and two matched
  `url.includes('/meals/1/ratings')` — a **substring of
  `/meals/1/ratings-breakdown`**, so the breakdown request was answered with a
  bare array and the list rendered empty either way. Match `'/ratings-breakdown'`
  explicitly. `dates.today` is lowercase `"heute"`, so assert case-insensitively.
- **Tests must render `<ToastProvider><App /></ToastProvider>`**, not `<App />`
  -- that is what `index.js` does, and `useToast()` otherwise falls back to its
  deliberate no-op, so nothing about the toast would be asserted. `App.test.js`
  has a `renderApp()` helper for exactly this.
- **Test files**:
  - `test_scraper_alignment.py` — validates DE/EN row alignment, no duplicates, mensa-name consistency
  - `test_db_integrity.py` — validates DB schema, no duplicates, matches official site
  - `test_api_language.py` — validates API multilingual output, no duplicates
  - `test_for_unused_items.py` — verifies backend code is actually in use
  - `test_auth.py` — register/login/session round-trip, anonymous rating still works, cross-user edit/delete is refused
  - `validate-translations.py` — validates translation files structure

## Request concurrency and the connection pool

The site "hung for about ten seconds and then loaded" until 2026-09-02. Ten
seconds was not a coincidence: it is `pool_timeout` in `database.py`.

- **Never lower the anyio thread limiter below `POOL_CAPACITY`.** Every route is
  a sync `def`, so FastAPI runs it on the anyio worker thread pool — **and it
  runs the cleanup of the sync `get_db` dependency there too**. Releasing a
  connection needs a worker thread exactly like acquiring one does. Capping
  tokens below the pool size deadlocks release: the exit tasks that call
  `db.close()` queue behind pending requests that are blocked in
  `pool.connect()` waiting for a connection only those exits can free, and the
  queue drains only as each waiter times out. Measured on dev while trying this
  "fix": 60 concurrent requests went from ~50 ms each to 30–40 s with 102 of 180
  failing, and every pooled connection sat in `idle in transaction`. `main.py`
  now *asserts* the limiter is `>= POOL_CAPACITY` at startup instead of setting
  it. The default 40 is correct.
- The pool is sized for the concurrency instead (`pool_size=10`,
  `max_overflow=10`). Waiting for a connection is safe when threads are
  plentiful — requests are ~50 ms, so a spike drains well inside `pool_timeout`.
- **A page load costs 2 API requests, not 66.** Each `DishCard` used to fetch
  `/ratings-breakdown` and `/top-photo` on mount; a 33-dish menu meant 66
  requests competing for 10 connections, which is what turned any brief
  contention into the visible stall. `GET /api/v1/meals-summary?ids=…` now
  returns `recent` and the top photo for the whole page in one query each.
  `overall` is deliberately absent from it: `GET /api/v1/meals` already returns
  it as `avg_rating`/`rating_count`, grouped by exactly the same
  `(name, mensa_id)`. The full breakdown loads only when a card is expanded.
- **A successful submit costs POST + one `ratings-breakdown` GET, and that is a
  different budget.** The 66-request problem was *fan-out on mount*: every
  visitor, including passive readers, firing two requests per card at once. This
  is one request, serial, following a POST that already held a connection, once
  per deliberate action, and it cannot fan out. It is the same shape as
  `loadTopPhoto()` after a photo vote, which is already accepted here.
- **Do NOT generalise that to votes.** `handleVote`/`handlePhotoVote` patch
  `reviews.comments` in place precisely because voting is high-frequency;
  `loadTopPhoto()` is the one narrow exception, because a photo vote can change
  which photo wins. Re-fetching the breakdown per vote would reintroduce the
  fan-out on the busiest action in the app.
- `_top_photos_by_dish()` is the batch form of `_top_photo_rating()` and must
  keep the same `ORDER BY score DESC, created_at ASC, id ASC`; it takes the first
  row per dish from that order. Do not reduce it with `max()` — see the
  photo-ranking note above.

## Scraper Behavior

- **Fetch and write are separate, and must stay separate.** `_fetch_day()` does
  the network and parsing with no session open; `_write_day()` opens a session,
  writes one date and commits. Until 2026-09-02 `scrape_menus()` held ONE
  session and ONE transaction across all 7 days of fetches — each up to
  `_fetch`'s 10 s timeout — pinning a pool connection for the whole scrape. Never
  call `SessionLocal()` around anything that does I/O.
- **One transaction per date.** A failure on day 5 no longer discards days 1–4.
  An empty fetch is a no-op: `_reconcile` only runs for a mensa actually
  scraped, so an unreachable site cannot mark the menu unavailable.
- **The first scrape is a scheduled job, not a startup call.** It ran inline in
  `@app.on_event("startup")`, so uvicorn served nothing until up to 14 fetches
  finished — the reason the healthcheck carries `start_period: 180s`. Dev now
  answers in under a second. The scheduler uses a **single-threaded executor**:
  APScheduler's `max_instances` only stops a job overlapping *itself*, so the
  11:30 cron and the 4-hourly refresh could previously run at once, at lunch peak.
- Fetches **next 7 days** inclusive of today
- Two-stage URL fallback: `alle.html` → per-mensas (`ALIAS_MAP` in `scraper.py:43`)
- Skips: `last minute`, `pastabuffet`, `Selbstbedienung` rows; filters to 4 mensas only
- **Description cleanup**: Removes "oder"/"or" separators between ingredients; normalizes whitespace
- **Multi-item rows**: a row with no `<strong>` whose description cell holds `MULTI_ITEM_MIN_LINES`+ individually priced lines (CGiN's "Heute : Grillfest") is exploded into one dish per line, so each is rateable on its own. Price classifies the type — under `SIDE_PRICE_MAX` (2,00 €) is a `side`, above it a `main` — and the per-item diet word supplies the tag, because the row's single `sp_hin` image describes the whole block and would label the Bratwurst vegan. Prices are stripped; `_extract_and_create_sides` is skipped for these rows (their decimal commas shred a comma split)
- **English is dropped for multi-item rows**: the English page serves Last Minute boilerplate in CGiN's Grillfest slot, so `LAST_MINUTE_RE` rejects it by content and the UI falls back to German. The older `last minute` skip only inspects the type cell

## Photo uploads

- **Uploads are metadata-stripped, not re-encoded.** `strip_metadata()` in
  `backend/images.py` walks the JPEG segments / PNG chunks / RIFF chunks and
  drops the metadata ones, copying every other byte through. **No Pillow** —
  no decode means no quality loss and no memory spike on a 3.8 GiB VM, and the
  pixel data stays bit-identical. Anything unparseable is returned unchanged:
  a photo that keeps its EXIF is a privacy bug, a photo mangled by a
  half-understood parser is worse.
- **The JPEG trailer is dropped, and that is the whole point.** An iPhone HDR
  photo appends a *second* JPEG after the primary image's EOI (the gain map)
  carrying its own APP1/XMP. The first version of the stripper copied
  everything after `SOS` verbatim and so republished it — 34 of 55 live files
  kept their XMP that way. `_scan_to_marker()` walks the entropy-coded data
  properly (0xFF 0x00 stuffing, RST markers, fill bytes) so the loop reaches
  EOI and stops there. Measured on the real uploads: 38 of 55 carried
  metadata, 21 had a GPS IFD, and the iPhone files shrink 180-280 KB each.
- **APP0 (JFIF) and APP2 (ICC) are deliberately kept.** Dropping the ICC
  profile visibly shifts the colours of a wide-gamut phone photo.
- **Filenames are a bare `uuid4().hex`.** They used to be prefixed with the
  uploader's own file name, which put it in a public, 30-day-immutable URL.
  Files uploaded before 2026-09-02 still carry the old prefix; their URLs are
  stored in `ratings.photo_url`, so they must not be renamed.
- **The backlog is fixed by `ops/strip-existing-exif.py`** (dry run by default,
  `--apply` to write, atomic rename, preserves mode). Back up first —
  `ops/backup.sh` tars the uploads directory.
- **Anything user-visible about this is also stated in the privacy notice.**
  `frontend/src/Datenschutz.js` claims metadata is removed on upload; if that
  stops being true, that page is then a false statement, not just stale.

## Feedback and UI state

Added 2026-09-02. Users submitted a review and saw nothing happen; several
reported being confused about whether the comment had vanished or been rejected.
The cause was entirely client-side — `submitRating` posted and then did nothing,
and the comment list only ever loaded from the card's expand toggle.

- **There was a 1500 ms `setTimeout` in `submitRating`'s `finally`.** It reset
  `submitted`, `rating`, `comment`, `selectedImage` and `imagePreview`
  **regardless of outcome**, so a *failed* submit destroyed the user's typed
  comment 1.5 s later while the error was still on screen, and a successful one
  replaced the whole form with a badge that then vanished — which is what made a
  saved comment look rejected. It was never cleared either, so it also fired
  `setState` after the card unmounted on a day change. **There is no timer now:**
  the fields reset in the success branch, and the confirmation persists until the
  next deliberate interaction (opening/closing the rate form, or collapsing the
  card). Regression test: "a failed submit keeps the typed comment and explains
  itself" asserts the text is still there 1700 ms later.
- **Errors are never rendered from a server string.** FastAPI's `detail` values
  are English and the UI defaults to German, so `submitErrorMessage()` maps the
  two known 400s onto the existing specific photo messages and gives everything
  else one honest line. The old fallback was `ui.photoError` ("Fehler beim
  Hochladen") *even for a text-only submit*.
- **`Toast.js` is for actions with nowhere to put a message** — vote failures,
  `Account`'s delete/save/logout, `/mensas` and `/meals-summary`. Twelve call
  sites used to swallow their failure entirely; a failed DELETE in Account was
  completely silent and the row simply stayed. **The review confirmation is
  deliberately NOT a toast:** the complaint was locational ("where did my
  comment go"), and a self-dismissing message recreates exactly that. It is
  `.rating-form__status`, inline on the card, next to the list it refers to.
- **A failed request and an empty result are different facts.** `menuError`,
  `searchError`, `reviewsError` and Account's `loadError` exist because the UI
  used to blame the user's date ("Kein Menü für dieses Datum"), query ("0
  Ergebnisse") or history ("Du hast noch nichts bewertet") for a network error.
  `Stats.js` had the sharpest form of this: no `r.ok` check, so an HTTP error
  body was stored *as* the stats object, the error branch never ran, and three
  blank cards rendered. Every one of these fetches now rejects on `!r.ok`.
- **Menu retry needs `menuReload`, not `setDate(d => d)`.** Setting state to the
  value it already holds makes React bail out of the re-render, so the effect
  never re-runs.
- **Two pieces of UI state are in-memory ON PURPOSE**: the "Deine Bewertung"
  marker on rows this visitor submitted (`myReviewIds`), and the filter panel's
  open/closed state. Persisting either needs a new `localStorage` key, and
  `Datenschutz.js` plus `datenschutz.storage*` in both translation files
  enumerate every key — `legal.test.js` asserts that list. Session-scoped costs
  nothing legally and solves the actual problem.
- **Anonymous submits go through a confirm step; signed-in ones do not.**
  `owned_rating()` treats `user_id IS NULL` as owned by nobody, so an anonymous
  review is permanent and public — the preview shows exactly what will be
  published, and the form says so. A signed-in user can edit and delete from
  their profile, so for them the same step would be pure friction. A failed
  submit **stays** on the preview, so retrying is one tap.
- **`aria-live` must not wrap a list.** The menu's wrapper used to be a live
  region containing every dish, so each card expand, vote and skeleton swap
  re-announced the whole menu. It announces only the count now. Live regions
  that carry a message (`.rating-form__status`, `.toast-host`) are mounted
  unconditionally and have their *text* swapped — a region inserted together
  with its content is not reliably announced.
- **`Lightbox` is `aria-modal="true"`, so it has to behave like one**: a
  focusable close button, focus moved in and returned on close, Tab kept inside,
  and `body` scroll locked. Before this it had zero focusable children and the
  only exit was the sliver of backdrop around a 90vw/90vh image whose own
  `onClick` stops propagation.
- **`ErrorBoundary` uses `i18n.isInitialized ? i18n.t(...) : fallback`.** It
  renders outside the i18n-initialised tree (`index.js` wraps `App`, and `App`
  is what calls `init`) and exists to survive a crash that may have happened
  before init ran. `ErrorBoundary.test.js` renders it in isolation, which is
  exactly that case.

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

Prod terminates TLS; **port 80 serves only the ACME challenge and a 301 to
`https://c100-246.cloud.gwdg.de`**. Dev (`nginx-proxy.dev.conf`, port 8080) is
HTTP-only and has no TLS at all, so the two files are no longer near-copies.

- `:443` `/` → `frontend:80`
- `:443` `/api/v1` → `backend:8000`
- `:443` `/uploads` → `backend:8000`
- `:80` `/.well-known/acme-challenge/` → `/var/www/certbot` (must stay ABOVE the
  redirect; certbot renewal fails silently if the 301 swallows it)
- `:80` everything else → `301`

Also set at the `http` level in both files:

- **`http2 on;`** — ALPN negotiated http/1.1 until 2026-09-02, capping a browser
  at 6 concurrent connections to this origin. nginx is 1.31 here, so it is the
  `http2 on;` directive, not the deprecated `listen … http2` form.
- **`gzip on;`** with `gzip_proxied any` — the bundle went out uncompressed
  (237 KB JS, 25 KB CSS). Now 73 KB and 5 KB; API JSON drops 7.5 KB → 1.3 KB.
  **No image types in `gzip_types`** — the uploads are already-compressed JPEG.
- **`/uploads` gets `Cache-Control: public, max-age=2592000, immutable`** — the
  filenames carry a content hash, so a URL never changes content. One explicit
  header rather than `expires` *plus* `add_header`, which emits two competing
  `Cache-Control` lines. `proxy_buffers 16 64k` stops multi-MB photos
  round-tripping through `proxy_temp` on disk.
- Hashed build assets are cached in **`frontend/nginx.conf`** (`location /static/`,
  `expires 1y`) — that is the file the frontend image copies; the repo-root
  `nginx.conf` and `nginx/nginx.conf` are dead. It uses `expires` and **not**
  `add_header`, because a location declaring any `add_header` stops inheriting
  the server-level ones and would silently drop `X-Frame-Options` and friends
  from every JS and CSS response.
- A second `:443` block answers `server_name 141.5.100.246` with a 301 to the
  canonical host. The cert has one SAN and Let's Encrypt will not issue an IP
  SAN, so `https://<ip>` still warns; the point is that clicking through lands on
  the canonical origin rather than a second copy of the app with its own
  `localStorage` (and so its own sessions and voter id).

**Both files log with `log_format proxymain`, which appends `:$server_port
$scheme rt=$request_time urt=$upstream_response_time`.** The stock `main` format omits them, and on 2026-09-01 that turned
"did their HTTPS request even arrive?" into a packet-level argument, because a
request on 80 and one on 443 produced identical log lines. `rt`/`urt` were added
on 2026-09-02 for the same reason: the access log could not answer "was that
request slow, and was it slow upstream?", so diagnosing the 10 s stall needed a
load test rather than a grep. Keep the two formats in step so a log line means
the same thing in either environment.

## TLS / Let's Encrypt

- **Cert**: `c100-246.cloud.gwdg.de`, ECDSA, webroot authenticator, renewed by the
  `certbot.timer` systemd unit. `/etc/letsencrypt` and `/var/www/certbot` are
  bind-mounted into the proxy (`docker-compose.yml`).
- **`ops/letsencrypt-deploy-hook.sh`** → installed to
  `/etc/letsencrypt/renewal-hooks/deploy/` by `ops/install-host-monitoring.sh`.
  **Without it a renewal is invisible to nginx**: certbot rewrites the files, but
  nginx reads its certificate once at startup and keeps it in memory, so the proxy
  serves the *expired* cert until the container happens to restart. The hook runs
  `nginx -t` then `nginx -s reload`, and exits 0 with a message if the container is
  not running (the cert is on disk and correct; the next start picks it up).
- `ops/check-host.sh` reads expiry off the **live socket**, not off disk, precisely
  so it catches a renewal that happened but never reached nginx.
- `certbot renew --dry-run` exercises the challenge path but **not** deploy hooks.
  Test the hook by running it directly.

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
- **`tcpdump` is installed** (2026-09-01). It was not, during an outage that came
  down to whether a client's packets were arriving at all -- there was no way to
  answer that from inside the VM. One SYN per connection attempt:
  ```bash
  sudo tcpdump -nn -l -i any 'tcp port 443 and tcp[tcpflags] & tcp-syn != 0'
  ```
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
  earlyoom alive, prod `/api/v1/health/db` returning **200**, certificate not
  within `CERT_WARN_DAYS` of expiry. Exit 3 + `ALARM` on trouble.
  **Assert the status code, never `curl -f` alone.** This probe was
  `curl -sf http://localhost/api/v1/health/db` and silently stopped testing
  anything the moment port 80 became an HTTPS redirect on 2026-09-01: `curl -f`
  does not treat a 3xx as an error and there was no `-L`, so it exited 0 on the
  301 without ever reaching the backend. It would have reported a healthy host
  with a completely dead API -- the same shape as the backup row-count lesson,
  where a dump of a wiped database is still a perfectly valid dump.
  It probes `https://$SITE_DOMAIN/...` with `--resolve` pinned to `127.0.0.1`
  rather than `-k`, so the real certificate chain is validated on the way past
  and an expired cert fails here instead of only in users' browsers.
  `ops/pre-deploy.sh`'s post-deploy verification had the identical bug and the
  identical fix. `ops/dev-up.sh` was already written this way -- copy that one.
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
4. **Frontend build**: `REACT_APP_API_URL` is a build-time Docker arg and must be **empty** behind the proxy. See the `??`/`:-` notes in Architecture — an empty value is easy to lose to a falsy check.
5. **Database health**: Backend waits for `pg_isready` (see `docker-compose.yml:11-16`); wait ~5-10s after `docker compose up` before API is ready.
5b. **Anything not matched by a `location` falls through to the SPA and returns
   `index.html` as `text/html` with a 200.** That is why `/favicon.ico`,
   `/robots.txt` and `/.git/config` all logged `200 737` — one missing file, not
   three. `frontend/public/` had no favicon at all until 2026-09-02; it holds one
   now, referenced from `index.html`. Read a `200 737` in the access log as "that
   path does not exist".
6. **Frontend dev**: `npm start` needs no `REACT_APP_API_URL`; absent, it falls back to `http://localhost:8000` (the `??` branch).
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

- Viewport: `width=device-width, initial-scale=1` — **no `maximum-scale`**. It
  was dropped deliberately: capping zoom fails WCAG 1.4.4. This file claimed
  `maximum-scale=3.0` until 2026-09-02, which `index.html` never had by then.
- Base font: `16px` (1rem = 16px), uses `rem` throughout
- **Touch targets are `--tap-min`, which is `44px`** (`styles/tokens.css`), not
  48, and there is no `MinWidth: 48` anywhere — `StarPicker` styles from CSS.
  `.btn--quiet` was `min-height: 0` (a ~20px target on the footer links, the
  Account actions and the rate toggle) and `.preview__remove` was 28px; both
  are `--tap-min` now. If you add an interactive element, size it from that
  token rather than a literal.
- No horizontal scroll (`overflow-x: hidden` in `index.css:14`)
- **The filter toolbar is a disclosure.** `.toolbar` is `position: sticky`, so
  everything in it costs screen space on every scroll — it used to stack four
  44px rows plus a checkbox, with an always-open 7-item `.legend` under it,
  ~250px of a 360x640 viewport. Date and search stay out; mensa, sort and
  `includePast` live behind `toolbar__toggle`, and the legend is a `<details>`.
  The collapsed toggle names the active filters, so a forgotten filter is never
  hidden silently.
