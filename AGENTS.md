# Mensa Rating System

## Overview

A web application for rating and discovering daily mensa (cafeteria) menus at universities in Göttingen, Germany. Users can browse daily menus, search for specific dishes, rate meals, and read community reviews.

- **Frontend**: React.js (served via Nginx)
- **Backend**: FastAPI (Python 3.11)
- **Database**: PostgreSQL 15 (persistent storage)
- **Infrastructure**: Docker Compose + Nginx reverse proxy
- **Live Site**: http://141.5.100.246/

## Architecture

```
┌────────────────────────────────────────────────────────┐
│  User Browser (141.5.100.246)                          │
└────────────────────┬───────────────────────────────────┘
                     │ Port 80
                     ▼
┌────────────────────────────────────────────────────────┐
│  proxy (Nginx Reverse Proxy)                            │
│  /         → frontend:80   (React static files)         │
│  /api/v1   → backend:8000  (FastAPI)                    │
└──────────────┬───────────────────────┬─────────────────┘
               │                       │
               ▼                       ▼
        ┌──────────┐          ┌──────────────┐
        │ frontend │          │   backend    │
        │ (Nginx)  │          │ (Uvicorn)    │
        │ :80      │          │ :8000        │
        └────┬─────┘          └──────┬───────┘
             │                       │
             │                       ▼
             │                ┌──────────┐
             └───────────────►│    db    │
                             │PostgreSQL│
                             │ :5432    │
                             └──────────┘
```

## Directory Structure

```
rate-site/
├── docker-compose.yml      # Docker services definition
├── nginx-proxy.conf        # Nginx reverse proxy config (routes to services)
├── .env                    # Environment variables (secrets, not committed)
├── .env.example            # Template for environment variables
├── backend/                # FastAPI backend
│   ├── Dockerfile          # Python 3.11 image
│   ├── main.py             # API routes (all under /api/v1)
│   ├── database.py         # SQLAlchemy models & DB connection
│   ├── scraper.py          # Menu scraper (runs every 4 hours)
│   └── requirements.txt    # Python dependencies
├── frontend/               # React frontend
│   ├── Dockerfile          # Node build + Nginx serve
│   ├── nginx.conf          # Frontend Nginx config (SPA fallback)
│   ├── public/index.html   # HTML template
│   └── src/
│       ├── App.js          # Main React component
│       └── index.css       # Global styles (mobile-responsive)
└── AGENTS.md               # This file
```

## RESTful API

The API strictly follows RESTful principles. All endpoints are versioned under `/api/v1`.

### Endpoints

| Resource     | Endpoint                                  | Method | Description                                    |
|--------------|-------------------------------------------|--------|------------------------------------------------|
| **Mensas**   | `/api/v1/mensas`                          | GET    | List all mensas                                |
| **Meals**    | `/api/v1/meals?date=YYYY-MM-DD`           | GET    | List/filter meals by date                      |
|              | `/api/v1/meals?query=search&past=false`   | GET    | Search meals by name/description               |
| **Ratings**  | `/api/v1/meals/{meal_id}/ratings`         | GET    | List ratings for a specific meal               |
|              | `/api/v1/meals/{meal_id}/ratings`         | POST   | Submit a rating (body: `{rating, comment}`)    |
|              | `/api/v1/ratings/{rating_id}`             | GET    | Get a single rating by ID                      |
|              | `/api/v1/meals/{meal_id}/side-ratings`    | GET    | List aggregated per-side ratings for a dish    |
|              | `/api/v1/meals/{meal_id}/side-ratings`    | POST   | Rate one of a dish's sides (body: `{side_name, rating, comment}`) |

### Key Principles

1. **Resource-Oriented URLs**: Nouns only, no verbs (`/meals`, not `/getMeals`).
2. **Hierarchical Resources**: Ratings are nested under meals (`/meals/{id}/ratings`).
3. **Standard HTTP Methods**: `GET` for retrieval, `POST` for creation.
4. **Standard Status Codes**:
   - `200 OK` — Successful GET
   - `201 Created` — Successful POST
   - `400 Bad Request` — Invalid query parameters
   - `404 Not Found` — Resource not found
   - `422 Unprocessable Entity` — Validation errors (FastAPI default)
5. **Pagination**: Defaults to `limit=20`. Override with `?limit=X`.
6. **Filtering**: `?date=`, `?query=`, `?past=` (boolean).

### Error Response Format

```json
{ "detail": "Meal not found" }
```

### Live API Endpoints

```bash
# List all mensas
curl http://141.5.100.246/api/v1/mensas

# Get meals for a specific date
curl "http://141.5.100.246/api/v1/meals?date=2026-07-02"

# Search for "Pizza" among past menus
curl "http://141.5.100.246/api/v1/meals?query=Pizza&past=true"

# Get ratings for meal ID 32
curl "http://141.5.100.246/api/v1/meals/32/ratings"

# Submit a rating for meal ID 32
curl -X POST "http://141.5.100.246/api/v1/meals/32/ratings" \
  -H "Content-Type: application/json" \
  -d '{"rating": 5, "comment": "Delicious!"}'

# Rate one of meal 32's sides (e.g. "Pommes frites", parsed from its description)
curl -X POST "http://141.5.100.246/api/v1/meals/32/side-ratings" \
  -H "Content-Type: application/json" \
  -d '{"side_name": "Pommes frites", "rating": 4}'
```

**Swagger UI**: http://141.5.100.246/docs

## Infrastructure

### Docker Services

| Service    | Image              | Port | Purpose                            |
|------------|--------------------|------|------------------------------------|
| `proxy`    | `nginx:alpine`     | 80   | Reverse proxy (routes traffic)     |
| `frontend` | `rate-site-frontend`| 80   | Serves React SPA (internal)        |
| `backend`  | `rate-site-backend`| 8000  | FastAPI server (internal)          |
| `db`       | `postgres:15-alpine`| 5432 | PostgreSQL database                |

### Database

- **Persistent Volume**: `postgres_data` — survives container restarts.
- **Connection**: Via `DATABASE_URL` env var (`postgresql://user:pass@db:5432/mensa_db`).
- **Schema**: `meals`, `mensas`, `ratings` tables.
- **Auto-Refresh**: Menu scraper runs every 4 hours; new meals persisted automatically.

## Development Commands

### Docker

```bash
# Full rebuild and restart
docker compose down && docker compose up -d --build

# Rebuild only backend
docker compose build backend && docker compose up -d backend

# Rebuild only frontend
docker compose build frontend && docker compose up -d frontend

# View logs (follow mode)
docker compose logs -f backend
docker compose logs -f proxy

# Run a single service
docker compose up -d db backend
```

### Frontend

```bash
# Development mode (on host)
cd frontend && npm start

# Rebuild image
docker compose build frontend

# Check linting
cd frontend && npm run lint
```

### Backend

```bash
# Run locally (without Docker)
cd backend && pip install -r requirements.txt
uvicorn main:app --reload

# Check linting
docker compose exec backend python -m ruff check .

# Run tests
docker compose exec backend pytest
```

### Database

```bash
# Connect to PostgreSQL
docker compose exec db psql -U user -d mensa_db

# List tables
docker compose exec db psql -U user -d mensa_db -c "\dt"

# Count meals
docker compose exec db psql -U user -d mensa_db -c "SELECT COUNT(*) FROM meals;"
```

### Nginx Proxy

```bash
# Test configuration
docker compose exec proxy nginx -t

# Reload without restart
docker compose exec proxy nginx -s reload
```

## Mobile Optimization

The frontend includes mobile-specific improvements:

- **Viewport**: `<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=3.0">`
- **Base font size**: `16px` root, using `rem` units throughout
- **Horizontal overflow**: Disabled (`body { overflow-x: hidden }`)
- **Touch-friendly targets**: Buttons ≥ 48x48px
- **Responsive layout**: Flexbox wrapping, `max-width: 100%` containers
- **Media queries**: Filters stack vertically on small screens

## Deployment

1. Push changes to the main branch.
2. Rebuild and restart:
   ```bash
   docker compose down && docker compose up -d --build
   ```
3. Verify at http://141.5.100.246/
4. Check logs for issues: `docker compose logs --tail=50`

## Troubleshooting

| Problem                        | Solution                                           |
|--------------------------------|----------------------------------------------------|
| Port 80 already in use       | Stop host Nginx: `sudo systemctl stop nginx`       |
| Frontend not loading         | Rebuild: `docker compose build frontend`           |
| API returns 404              | Check proxy: `docker compose logs proxy`           |
| Backend crash/error          | Check logs: `docker compose logs backend`          |
| Stale browser cache          | Hard refresh (Ctrl+Shift+R)                        |
| Database not ready           | Backend waits for healthcheck; wait a few seconds  |

## Future Improvements

- [ ] Pagination UI (infinite scroll / "Load More" button)
- [ ] Dark mode toggle
- [ ] PWA support (manifest.json, service worker)
- [ ] User authentication for custom ratings
- [ ] Dish image upload
- [ ] Backend unit tests (pytest)
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] Price and allergen fields in meal schema
