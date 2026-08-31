# Mensa Rating System

Rate and review meals at Göttingen university mensas (Zentralmensa, CGiN, Mensa am Turm, Bistro HAWK).

## Features

- Browse menus for the next 7 days across 4 mensas
- Optional accounts (username + password) — see your own ratings and favourites
- Rate dishes with 1–5 star ratings (works signed in or anonymously)
- Submit comments and upload photos (JPG/PNG/WebP, max 5MB)
- Rate side dishes individually
- Multilingual support (German/English)
- Search across all dishes
- View rating breakdowns (recent vs overall)
- Side dish rating averages

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 / i18next |
| Backend | FastAPI (Python 3.11) |
| Database | PostgreSQL 15 |
| Web Server | Nginx (reverse proxy + static) |
| Containerization | Docker Compose |

## Quick Start

```bash
# Configure environment
cp .env.example .env
# Edit .env with your DATABASE_URL and REACT_APP_API_URL

# Build and start
docker compose down && docker compose up -d --build

# Wait ~5–10s for database health check
# Access at http://localhost
```

## Project Structure

```
rate-site/
├── docker-compose.yml        # Services orchestration
├── .env.example             # Environment template
├── nginx-proxy.conf         # Host nginx reverse proxy
├── backend/
│   ├── main.py              # API endpoints
│   ├── database.py          # SQLAlchemy models
│   ├── scraper.py           # Menu scraper
│   └── tests/               # Test suite
└── frontend/
    └── src/                 # React application
```

## API Endpoints (`/api/v1/`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/mensas` | List of mensa names |
| GET | `/meals` | Meals for date (`lang=de|en`) |
| GET | `/meals/search` | Search dishes |
| GET | `/meals/{id}/ratings` | All ratings for a dish |
| GET | `/meals/{id}/ratings-breakdown` | Rating breakdown with comments |
| GET | `/meals/{id}/side-ratings` | Side dish averages |
| GET | `/meals/{id}/photos` | Photos for a meal |
| POST | `/meals/{id}/ratings` | Create rating |
| POST | `/meals/{id}/ratings-with-photo` | Rating with photo |
| POST | `/meals/{id}/side-ratings` | Rate side dish |

## Development

> **Never run pytest inside the `backend` container** — the suite drops and
> recreates tables against whatever `DATABASE_URL` is in scope, which there is
> production. Use the isolated test stack below.

```bash
# Run backend lint
docker compose exec backend python -m ruff check .

# Run the test suite (own compose project + throwaway Postgres on tmpfs)
docker compose -p rate-site-test -f docker-compose.test.yml run --rm tests

# Run DB integration tests
docker compose -p rate-site-test -f docker-compose.test.yml run --rm tests \
    python -m pytest tests/test_db_integrity.py -v

# Deploy to prod (backs up first)
./ops/pre-deploy.sh

# Manual menu scrape
docker compose exec backend python -c "from scraper import scrape_menus; scrape_menus()"
```

### Backups

Nightly `pg_dump` + uploads tarball to `/home/cloud/backups` via cron
(`ops/backup.sh`), 14 dailies and 8 weekly copies, with a row-count tripwire
that alarms if a table suddenly empties. Restore with `ops/restore.sh`.
See the Backups section in `AGENTS.md`.

## Configuration

**Environment variables (`.env`):**
- `DATABASE_URL` — PostgreSQL connection string
- `REACT_APP_API_URL` — Backend API URL (default: `http://localhost:8000`)

**Build-time (frontend):**
- `REACT_APP_API_URL` set in `frontend/Dockerfile`

## License

MIT