# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A web app for rating and browsing daily mensa (university cafeteria) menus in Göttingen, Germany. React frontend, FastAPI backend, PostgreSQL database, all deployed via Docker Compose behind an Nginx reverse proxy. There is also a more detailed `AGENTS.md` in the repo root, but treat it as a design doc, not ground truth — see "Known discrepancies" below for places it's out of date.

## Architecture

```
Browser → proxy (nginx-proxy.conf, port 80)
              ├─ /            → frontend container (Nginx serving the React build)
              └─ /api/v1/...  → backend container (Uvicorn/FastAPI, port 8000)
                                     └─ Postgres (db container)
```

- The `proxy` service (`docker-compose.yml`) mounts `nginx-proxy.conf` and is the only container that publishes a host port. It forwards `/api/v1` requests to `backend` with the path unchanged, and everything else to `frontend`.
- **Dead config trap**: the top-level `nginx.conf` and the `nginx/` directory (which has its own `Dockerfile` bundling a frontend build + nginx into one image) are **not referenced anywhere in `docker-compose.yml`** — leftovers from an earlier single-container layout. The configs actually in effect are `nginx-proxy.conf` (the `proxy` service) and `frontend/nginx.conf` (baked into the `frontend` image by `frontend/Dockerfile`). Editing `nginx.conf` or anything under `nginx/` has no effect on the running stack.
- Frontend and backend are separate Docker images (`frontend/Dockerfile`, `backend/Dockerfile`); `REACT_APP_API_URL` is baked into the frontend at **image build time**, not read at runtime — changing it requires a rebuild, not just a container restart.

## Backend (`backend/`)

- `database.py` — SQLAlchemy models `Mensa`, `Meal`, `Rating`, plus `init_db()`. There is no migration framework (no Alembic): `init_db()` calls `create_all()` and then runs manual, idempotent `ALTER TABLE ... ADD COLUMN` checks for columns added after the initial schema (see the `description`/`tags` columns as the existing pattern). Follow that same inline-check-and-ALTER approach for future schema additions.
- `scraper.py` — scrapes cached menu HTML from the Studierendenwerk Göttingen site for the next 7 days, for four known mensas (`ALIAS_MAP`). Prefers the bundled `alle.html` page (one fetch, all mensas) and falls back to per-mensa pages if that's missing/too small. Dedupes rows within a run by `(name, description, mensa_id)`. Wired up in `main.py`'s startup hook to run once immediately and then every 4 hours via `APScheduler`.
- `main.py` — all routes live here, versioned under `/api/v1`. Ratings are created with a server-generated joke `user_name` (`generate_funny_name()`) — there's no real user auth/accounts anywhere in this app.
  - **Known bug / trap**: the backend defines a dedicated search route `GET /api/v1/meals/search?q=...&past=...`, but the frontend actually calls `GET /api/v1/meals?query=...&past=...` (see `frontend/src/App.js`), which hits the *other* handler (`get_meals`) — one that only understands a `date` param and silently ignores `query`/`past`. In practice, the deployed "search" UI is not exercising the `/meals/search` code path at all. If you touch search behavior, check which route is actually being hit before trusting the endpoint table in `AGENTS.md`.
  - `get_meals` also has unreachable code after an early `return results` (leftover from a refactor) — the dead branch below it is not executed.
  - `RatingOut` is defined twice in this file; the second definition (which adds `meal_id`) silently shadows the first. If you need `RatingOut`, you're getting the second one.

## Frontend (`frontend/src/`)

- Single-file React app: nearly all UI logic lives in `App.js` (no router, no state library — plain `useState`/`useEffect`, no Redux/Context). Styling is inline `style={}` objects throughout; `index.css` only holds global/mobile-responsive rules. There's no component directory to navigate — new UI usually means editing `App.js` directly.
- Talks to the backend via plain `fetch` against `REACT_APP_API_URL` (see Environment below).

## Environment / Config

- `.env` (gitignored, real secrets) vs `.env.example` (template) — `DATABASE_URL`, `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`, `REACT_APP_API_URL`.
- `backend/database.py` hard-fails at import time if `DATABASE_URL` isn't set — always export it before running the backend outside Docker.

## Common Commands

### Docker Compose (primary workflow)

```bash
# Full rebuild and restart
docker compose down && docker compose up -d --build

# Rebuild a single service
docker compose build backend && docker compose up -d backend
docker compose build frontend && docker compose up -d frontend

# Logs
docker compose logs -f backend
docker compose logs -f proxy

# Shell into Postgres
docker compose exec db psql -U user -d mensa_db
```

### Frontend (local dev, outside Docker)

```bash
cd frontend && npm start   # dev server, reads REACT_APP_API_URL from env
cd frontend && npm run build
```

### Backend (local dev, outside Docker)

```bash
cd backend
pip install -r requirements.txt
DATABASE_URL=postgresql://user:pass@localhost:5432/mensa_db uvicorn main:app --reload
```

### No test suite, no linter

There are no test files and no lint config anywhere in this repo (`requirements.txt` has no `pytest`/`ruff`; `frontend/package.json` defines no `lint` script). Don't assume `pytest`, `ruff check`, or `npm run lint` work — they don't exist yet. Verify changes by running the app (`docker compose up -d --build`) and exercising the affected endpoint/UI directly.
