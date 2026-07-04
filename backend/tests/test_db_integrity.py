"""DB integration tests: run the scraper, then verify the stored menu.

Requires a Postgres DATABASE_URL (skips otherwise), so run inside docker compose:
  docker compose up -d db
  docker compose exec backend python -m pytest tests/test_db_integrity.py -v
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
    from database import init_db, SessionLocal
    from scraper import scrape_menus
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
            # No unexpected extras — except rows that already carry ratings.
            for extra in db_names - expected:
                row = db.query(DBMeal).filter(
                    DBMeal.date == d, DBMeal.mensa_id == mensa.id, DBMeal.name == extra
                ).first()
                rated = (
                    db.query(DBRating).filter(DBRating.meal_id == row.id).first()
                    or db.query(DBSideRating).filter(DBSideRating.meal_id == row.id).first()
                )
                assert rated, f"{d} {mensa_name}: unexpected extra dish {extra!r} (not on site, unrated)"
