"""Shared pytest setup.

Ensures the backend package is importable and that importing `scraper`/`database`
does not require a real database for the parse-only tests. Integration tests that
actually need Postgres check DATABASE_URL themselves and skip otherwise.
"""
import os
import sys

# Make backend/ importable (scraper.py, database.py, main.py live there).
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# database.py requires DATABASE_URL at import time. Provide a harmless SQLite
# default so parse-only tests can import scraper without a live DB. Real
# integration runs (docker compose) already set a Postgres URL, which wins.
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_parse_only.db")
