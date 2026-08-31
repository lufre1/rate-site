"""DB integration tests: run the scraper, then verify the stored menu.

This module DROPS AND RECREATES every table, so it only ever runs against the
throwaway Postgres in docker-compose.test.yml (database name `mensa_test`):

  docker compose -p rate-site-test -f docker-compose.test.yml run --rm tests \
      python -m pytest tests/test_db_integrity.py -v

Never run it inside the production backend container. conftest.assert_disposable
enforces this, and the fixture below re-checks before issuing any DDL.
"""
import os
from collections import Counter
from datetime import date, timedelta

import pytest

_DB_URL = os.getenv("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    "postgres" not in _DB_URL,
    reason="DB integration test needs a Postgres DATABASE_URL (run in docker compose)",
)


@pytest.fixture(scope="module")
def db():
    from conftest import assert_disposable
    from database import init_db, SessionLocal, Base, engine
    from scraper import scrape_menus

    # Re-check immediately before the DDL. conftest already vetted DATABASE_URL
    # at import time; this guards against anything reassigning it since.
    assert_disposable(str(engine.url))

    # Start from a clean schema so scraper assertions see only this run's rows.
    Base.metadata.drop_all(bind=engine)
    init_db()
    scrape_menus()  # populate/refresh next 7 days from the live site
    session = SessionLocal()
    yield session
    session.close()


def _official_de_names(date_obj):
    """{mensa_name: set(dish names)} parsed from the official German site."""
    from scraper import (
        ALL_URL, CACHE_URL, ALIAS_MAP,
        _mensa_tables_for_date, _dish_rows, _parse_dish_row,
    )
    valid = set(ALIAS_MAP.values())
    ds = date_obj.strftime('%Y-%m-%d')
    tables = _mensa_tables_for_date(ds, ALL_URL, CACHE_URL)
    out = {}
    for name, table in tables.items():
        if name not in valid:
            continue
        names = set()
        for row in _dish_rows(table):
            dish = _parse_dish_row(row)
            if dish:
                names.add(dish['name'])
        out[name] = names
    return out


def test_no_duplicate_rows_per_mensa_date(db):
    from database import Meal as DBMeal
    rows = db.query(DBMeal.date, DBMeal.mensa_id, DBMeal.name).filter(
        DBMeal.date >= date.today()
    ).all()
    dups = {k: c for k, c in Counter(
        (r.date, r.mensa_id, r.name) for r in rows
    ).items() if c > 1}
    assert not dups, f"duplicate (date, mensa, name) rows found: {dups}"


def test_every_future_row_has_german_name(db):
    from database import Meal as DBMeal
    rows = db.query(DBMeal).filter(DBMeal.date >= date.today()).all()
    missing = [r.id for r in rows if not r.name_de]
    assert not missing, f"{len(missing)} future rows missing name_de"


def test_db_matches_official_site(db):
    from database import Meal as DBMeal, Mensa as DBMensa, Rating as DBRating, SideRating as DBSideRating
    today = date.today()
    for offset in range(7):
        d = today + timedelta(days=offset)
        expected_by_mensa = _official_de_names(d)
        for mensa_name, expected in expected_by_mensa.items():
            mensa = db.query(DBMensa).filter(DBMensa.name == mensa_name).first()
            assert mensa is not None, f"{d} {mensa_name}: site has dishes but mensa missing in DB"
            db_names = {
                m.name for m in db.query(DBMeal).filter(
                    DBMeal.date == d, DBMeal.mensa_id == mensa.id
                ).all()
            }
            # Nothing missing.
            assert expected.issubset(db_names), \
                f"{d} {mensa_name}: missing dishes {expected - db_names}"
            # No unexpected extras — except rows that already carry ratings, or are side dishes
            # (sides are extracted from main dish descriptions and may not appear on official site)
            for extra in db_names - expected:
                row = db.query(DBMeal).filter(
                    DBMeal.date == d, DBMeal.mensa_id == mensa.id, DBMeal.name == extra
                ).first()
                # Allow side dishes without ratings (they're extracted from main dishes)
                if row.type == 'side':
                    continue
                rated = (
                    db.query(DBRating).filter(DBRating.meal_id == row.id).first()
                    or db.query(DBSideRating).filter(DBSideRating.meal_id == row.id).first()
                )
                assert rated, f"{d} {mensa_name}: unexpected extra dish {extra!r} (not on site, unrated)"
