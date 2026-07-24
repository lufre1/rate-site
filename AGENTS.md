# Mensa Rating System — AGENTS.md

## Architecture

- **Frontend**: React (Create React App, Nginx serve), **Backend**: FastAPI (Python 3.11), **DB**: PostgreSQL 15
- **All API routes under `/api/v1/`** — frontend calls `http://localhost:8000` by default, but in prod through nginx on `/api/v1`
- **API URL from env**: `REACT_APP_API_URL` (set at build time in `frontend/Dockerfile:4`)
- **Language support**: Each meal stores `name_de`, `name_en`, `description_de`, `description_en`; API returns `lang` parameter (default `de`)

## Database Schema Details (Non-Obvious)

- **Meal deduplication**: `(date, mensa_id, name)` must be unique. `scrape_menus()` deletes stale rows but preserves rows with existing ratings
- **German/English merge**: Scraper pairs DE/EN rows positionally. Missing EN doesn't wipe existing EN data
- **Autofilled funny usernames**: `generate_funny_name()` in `main.py:106` — every rating has a generated `user_name`; don't expect user accounts
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
  - `validate-translations.py` — validates translation files structure

## Scraper Behavior

- Fetches **next 7 days** inclusive of today
- Two-stage URL fallback: `alle.html` → per-mensas (`ALIAS_MAP` in `scraper.py:43`)
- Skips: `last minute`, `pastabuffet`, `Selbstbedienung` rows; filters to 4 mensas only
- **Description cleanup**: Removes "oder"/"or" separators between ingredients; normalizes whitespace

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
