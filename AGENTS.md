# Mensa Rating System — AGENTS.md

## Architecture

- **Frontend**: React (Create React App, Nginx serve), **Backend**: FastAPI (Python 3.11), **DB**: PostgreSQL 15
- **No router**: views are toggled with boolean state in `App.js` (`showImpressum`, `showAccount`). Shared helpers (`API`, token storage, `StarPicker`, `formatRelativeDate`) live in `frontend/src/shared.js` so `Account.js` doesn't import from its own parent
- **All API routes under `/api/v1/`** — frontend calls `http://localhost:8000` by default, but in prod through nginx on `/api/v1`
- **API URL from env**: `REACT_APP_API_URL` (set at build time in `frontend/Dockerfile:4`)
- **Language support**: Each meal stores `name_de`, `name_en`, `description_de`, `description_en`; API returns `lang` parameter (default `de`)

## Database Schema Details (Non-Obvious)

- **Meal deduplication**: `(date, mensa_id, name)` must be unique. `scrape_menus()` deletes stale rows but preserves rows with existing ratings
- **German/English merge**: Scraper pairs DE/EN rows positionally. Missing EN doesn't wipe existing EN data
- **Rating identity**: every rating goes through `rating_identity()` in `main.py`. Signed in -> the real username and a `user_id`; anonymous -> a `generate_funny_name()` string and `user_id = NULL`. All three creation routes (`ratings`, `ratings-with-photo`, `side-ratings`) use it — change it there, not per-route
- **Side ratings aggregation**: `side-ratings` are **global per side name** across all meals in a mensa, not per-meal; API returns aggregated stats

## Key Commands

```bash
# Full stack rebuild & start
docker compose down && docker compose up -d --build

# Run backend tests (parse-only, no DB needed)
docker compose exec backend python -m pytest tests/

# Run DB integration tests (needs Postgres)
docker compose exec backend python -m pytest tests/test_db_integrity.py -v

# Update menu data manually (e.g. after DB reset)
docker compose exec backend python -c "from scraper import scrape_menus; scrape_menus()"
```

**Note**: Backend lint (ruff) and frontend tests/build require local development setup — not configured in the Docker images. Frontend build happens during `docker compose build` (uses `REACT_APP_API_URL` Docker arg).

## Testing

- **Backend unit tests**: Parse-only, no DB required (`os.environ.setdefault("DATABASE_URL", "sqlite:///./test_parse_only.db")` in `conftest.py:18`)
- **Backend integration tests**: Require running backend (`API_BASE_URL`) or Postgres (`DATABASE_URL` with `postgres` in URL)
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

## Common Pitfalls

1. **Duplicate rows**: After DB reset, call `scrape_menus()` to regenerate. Stale rows with ratings are preserved.
2. **English data loss**: Scraper never overwrites existing `name_en` if new EN source is empty — protects against temporary page outages.
3. **Port conflict**: Host port 80 must be free (`sudo systemctl stop nginx` if needed).
4. **Frontend build**: `REACT_APP_API_URL` must be set at build time via Docker arg (default `http://localhost:8000`).
5. **Database health**: Backend waits for `pg_isready` (see `docker-compose.yml:11-16`); wait ~5-10s after `docker compose up` before API is ready.
6. **Frontend dev**: `npm start` needs `REACT_APP_API_URL` set; defaults to `http://localhost:8000`.

## Mobile Behavior

- Viewport: `width=device-width, initial-scale=1.0, maximum-scale=3.0`
- Base font: `16px` (1rem = 16px), uses `rem` throughout
- Buttons ≥ 48px touch targets (`MinWidth: 48` in `StarPicker`)
- No horizontal scroll (`overflow-x: hidden` in `index.css:14`)
