"""Shared pytest setup, and the safety rail that keeps tests off real databases.

On 2026-08-31 the production database was destroyed by running

    docker compose exec backend python -m pytest tests/

inside the prod container. This module used to call
``os.environ.setdefault("DATABASE_URL", "sqlite:///...")``; ``setdefault``
yields to an existing value, so inside the container the tests bound straight
to the live Postgres URL and the ``Base.metadata.drop_all()`` calls in the
fixtures dropped every table.

Two rules now prevent that:

1. Tests NEVER inherit an ambient ``DATABASE_URL``. The value is chosen here
   and assigned unconditionally.
2. Anything that is not obviously disposable is rejected loudly, before a
   single connection is opened. Fail closed, never fall through to "probably
   fine".

To run integration tests against a real Postgres, point ``TEST_DATABASE_URL``
at a database whose name ends in ``_test`` -- see docker-compose.test.yml.
"""
import os
import sys
import tempfile
import uuid
from urllib.parse import urlsplit

# Make backend/ importable (scraper.py, database.py, main.py live there).
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# --------------------------------------------------------------------------
# Safety rail
# --------------------------------------------------------------------------

_SUFFIX = "_test"


def _is_disposable(url: str) -> bool:
    """True only for databases a test run is allowed to create and destroy."""
    if not url:
        return False
    if url.startswith("sqlite"):
        return True
    # Postgres/MySQL/...: require an unmistakable marker in the database name.
    return urlsplit(url).path.lstrip("/").endswith(_SUFFIX)


def assert_disposable(url: str) -> None:
    """Abort the run unless `url` points at a throwaway database."""
    if _is_disposable(url):
        return
    name = urlsplit(url).path.lstrip("/") or "<unparseable>"
    raise RuntimeError(
        f"Refusing to run tests against database {name!r}.\n"
        f"The test suite drops and recreates tables, so it only accepts SQLite "
        f"or a database whose name ends in {_SUFFIX!r}.\n"
        f"Never run pytest inside the production backend container.\n"
        f"Use:  docker compose -p rate-site-test -f docker-compose.test.yml run --rm tests"
    )


def _choose_database_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL", "")
    if explicit:
        assert_disposable(explicit)
        return explicit

    ambient = os.environ.get("DATABASE_URL", "")
    if ambient and not _is_disposable(ambient):
        # Someone is running the suite somewhere it must not run -- most likely
        # the prod container. Say so instead of silently redirecting to SQLite.
        assert_disposable(ambient)
    if ambient:
        return ambient

    # Default: a private SQLite file, unique per run so a stale schema from an
    # earlier run can never be reused.
    return "sqlite:///" + os.path.join(
        tempfile.gettempdir(), f"rate_site_tests_{uuid.uuid4().hex}.db"
    )


DATABASE_URL = _choose_database_url()
assert_disposable(DATABASE_URL)
os.environ["DATABASE_URL"] = DATABASE_URL  # hard override, never setdefault

# main.py hardcodes UPLOAD_DIR to "/app/uploads" and creates it at import time.
# Point it at a throwaway directory: the real uploads/ holds user photos and
# the delete-rating endpoint calls os.remove() on files in it.
os.environ.setdefault(
    "UPLOAD_DIR", os.path.join(tempfile.gettempdir(), "rate_site_test_uploads")
)
os.makedirs(os.environ["UPLOAD_DIR"], exist_ok=True)

import pytest  # noqa: E402  (imported after the env is made safe)
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


def pytest_configure(config):
    """Re-assert the rail after collection, in case a module reassigned it."""
    assert_disposable(os.environ.get("DATABASE_URL", ""))


@pytest.fixture()
def sqlite_db(tmp_path, monkeypatch, request):
    """A private SQLite database for one test.

    Replaces this pattern, which is what destroyed production:

        Base.metadata.drop_all(bind=engine)   # engine could be ANY database
        Base.metadata.create_all(bind=engine)

    Each test gets its own file under tmp_path, so isolation comes from the
    database being new rather than from dropping tables in a shared one. The
    engine and session factory are swapped into `database` and into the
    requesting test module, so existing `SessionLocal()` calls pick them up
    without any change at the call sites.

    Yields the sessionmaker, so a test can open extra sessions if it needs to.
    """
    import database

    url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    database.Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    for module in (database, request.module):
        for attr, value in (("engine", engine), ("SessionLocal", TestSession)):
            if hasattr(module, attr):
                monkeypatch.setattr(module, attr, value)

    try:
        yield TestSession
    finally:
        engine.dispose()
