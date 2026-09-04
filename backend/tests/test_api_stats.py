"""Tests for the statistics/overview endpoint.

Covers:
- Weekly trends day-of-week mapping (dow 0=Sunday -> lowercase day keys)
- Weekly trends bucketing on Berlin day boundaries (Postgres only)
- Language parameter (lang=en vs lang=de) for dish name resolution
- Minimum rating floor for top dishes and mensa rankings
- Correct aggregation of avg_rating and rating_count
"""
from datetime import date as date_cls, datetime, timedelta
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
from database import SessionLocal, Mensa, Meal, Rating, Base


@pytest.fixture()
def client(monkeypatch, tmp_path, sqlite_db):
    """A TestClient wired to a throwaway SQLite schema and upload dir."""
    monkeypatch.setattr(main, "UPLOAD_DIR", str(tmp_path))

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[main.get_db] = override_get_db
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


@pytest.fixture()
def seed_data(client, sqlite_db):
    """Seed test data with known ratings for stats testing."""
    db = SessionLocal()
    try:
        mensa1 = Mensa(name="Mensa A")
        mensa2 = Mensa(name="Mensa B")
        db.add(mensa1)
        db.add(mensa2)
        db.commit()
        db.refresh(mensa1)
        db.refresh(mensa2)

        meal1 = Meal(
            name="Pasta", name_de="Pasta", name_en="Pasta",
            description="Tomatensoße", description_de="Tomatensoße",
            description_en="Tomato sauce", tags=None, type="main",
            date=date_cls.today(), mensa_id=mensa1.id,
        )
        meal2 = Meal(
            name="Currywurst", name_de="Currywurst", name_en="Currywurst",
            description="Mit Pommes", description_de="Mit Pommes",
            description_en="With fries", tags=None, type="main",
            date=date_cls.today(), mensa_id=mensa1.id,
        )
        meal3 = Meal(
            name="Salat", name_de="Salat", name_en="Salad",
            description="Gemüse", description_de="Gemüse",
            description_en="Vegetables", tags=None, type="main",
            date=date_cls.today(), mensa_id=mensa2.id,
        )
        db.add(meal1)
        db.add(meal2)
        db.add(meal3)
        db.commit()
        db.refresh(meal1)
        db.refresh(meal2)
        db.refresh(meal3)

        today = datetime.now()
        ratings = [
            Rating(meal_id=meal1.id, rating=5, comment="Gut", created_at=today - timedelta(days=0)),
            Rating(meal_id=meal1.id, rating=4, comment="OK", created_at=today - timedelta(days=1)),
            Rating(meal_id=meal1.id, rating=5, comment="Toll", created_at=today - timedelta(days=2)),
            Rating(meal_id=meal1.id, rating=4, comment="Fein", created_at=today - timedelta(days=3)),
            Rating(meal_id=meal1.id, rating=5, comment="Perfekt", created_at=today - timedelta(days=4)),
            Rating(meal_id=meal2.id, rating=3, comment="Mittel", created_at=today - timedelta(days=5)),
            Rating(meal_id=meal2.id, rating=4, comment="Gut", created_at=today - timedelta(days=6)),
            Rating(meal_id=meal3.id, rating=5, comment="Frisch", created_at=today - timedelta(days=0)),
            Rating(meal_id=meal3.id, rating=4, comment="Gesund", created_at=today - timedelta(days=1)),
        ]
        for r in ratings:
            db.add(r)
        db.commit()
        return {"meal1": meal1.id, "meal2": meal2.id, "meal3": meal3.id}
    finally:
        db.close()


WEEK_ORDER = ["monday", "tuesday", "wednesday", "thursday",
              "friday", "saturday", "sunday"]

# Anchored to real calendar dates so the assertions name a weekday rather than a
# relative offset -- `seed_data` uses datetime.now() - timedelta(...), which has no
# fixed weekday and is why the two-day label shift survived this file for so long.
# Midday times keep every count clear of the UTC/Berlin day boundary, so the
# expectations hold on SQLite (naive) and Postgres (converted) alike.
KNOWN_WEEKDAYS = {
    "monday": [datetime(2026, 1, 5, 12, 0), datetime(2026, 1, 12, 12, 0)],
    "tuesday": [datetime(2026, 1, 6, 12, 0)],
    "wednesday": [datetime(2026, 1, 7, 12, 0), datetime(2026, 1, 7, 13, 0),
                  datetime(2026, 1, 7, 14, 0)],
    "thursday": [],
    "friday": [datetime(2026, 1, 9, 12, 0)],
    "saturday": [datetime(2026, 1, 10, 12, 0)],
    "sunday": [datetime(2026, 1, 11, 12, 0), datetime(2026, 1, 11, 13, 0)],
}


def _seed_ratings(meal_id, stamps):
    """Add one rating per timestamp in `stamps`."""
    db = SessionLocal()
    try:
        for created_at in stamps:
            db.add(Rating(meal_id=meal_id, rating=4, comment="x", created_at=created_at))
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def weekday_data(client, sqlite_db):
    """One mensa, one meal, and ratings pinned to known weekdays."""
    db = SessionLocal()
    try:
        mensa = Mensa(name="Mensa A")
        db.add(mensa)
        db.commit()
        db.refresh(mensa)

        meal = Meal(
            name="Pasta", name_de="Pasta", name_en="Pasta",
            description="Tomatensoße", description_de="Tomatensoße",
            description_en="Tomato sauce", tags=None, type="main",
            date=date_cls(2026, 1, 5), mensa_id=mensa.id,
        )
        db.add(meal)
        db.commit()
        db.refresh(meal)
        meal_id = meal.id
    finally:
        db.close()

    _seed_ratings(meal_id, [s for stamps in KNOWN_WEEKDAYS.values() for s in stamps])
    return meal_id


def test_weekly_trends_day_mapping(client, weekday_data):
    """A rating made on a given weekday must be counted under that weekday.

    Regression test for the (i + 6) % 7 offset, which credited every count to the
    day two places later -- Monday's ratings showed up under Wednesday.
    """
    resp = client.get("/api/v1/stats/overview")
    assert resp.status_code == 200
    weekly = resp.json()["weekly_trends"]

    expected = {day: len(stamps) for day, stamps in KNOWN_WEEKDAYS.items()}
    assert weekly == expected


def test_weekly_trends_keys_are_complete_and_ordered(client, weekday_data):
    """All seven days are always present, Monday first (the frontend renders in order)."""
    resp = client.get("/api/v1/stats/overview")
    assert resp.status_code == 200
    weekly = resp.json()["weekly_trends"]

    assert list(weekly.keys()) == WEEK_ORDER
    assert all(isinstance(v, int) for v in weekly.values())


def test_weekly_trends_zero_fills_days_without_ratings(client, weekday_data):
    """A day with no ratings reports 0 rather than going missing."""
    resp = client.get("/api/v1/stats/overview")
    assert resp.status_code == 200
    assert resp.json()["weekly_trends"]["thursday"] == 0


def test_local_dow_converts_to_berlin_on_postgres():
    """created_at is naive UTC, so on Postgres the weekday must be taken in Berlin.

    This asserts the compiled SQL rather than query results: the `client` fixture
    is bound to `sqlite_db`, so no test in this file ever reaches a real Postgres.
    Verified separately against the live database -- 2026-01-05 23:30 UTC (Monday)
    converts to Tuesday 00:30 CET, and 2026-07-06 22:30 UTC to Tuesday 00:30 CEST.
    """
    sql = str(main._local_dow(create_engine("postgresql://")))
    assert "timezone(:timezone_1, timezone(:timezone_2, ratings.created_at))" in sql


def test_local_dow_stays_naive_on_sqlite():
    """SQLite has no timezone database, so the expression must not emit timezone()."""
    sql = str(main._local_dow(create_engine("sqlite://")))
    assert "timezone" not in sql


def test_lang_parameter_affects_dish_names(client, seed_data):
    """The lang parameter should control whether dish names are EN or DE."""
    resp_de = client.get("/api/v1/stats/overview?lang=de")
    assert resp_de.status_code == 200
    data_de = resp_de.json()
    dish_de = data_de["top_rated_dishes"][0]["name"]

    resp_en = client.get("/api/v1/stats/overview?lang=en")
    assert resp_en.status_code == 200
    data_en = resp_en.json()
    dish_en = data_en["top_rated_dishes"][0]["name"]

    assert dish_de == "Pasta"
    assert dish_en == "Pasta"


def test_top_dishes_minimum_rating_floor(client, seed_data):
    """Top dishes should only include items with >= 5 ratings."""
    resp = client.get("/api/v1/stats/overview")
    assert resp.status_code == 200
    data = resp.json()

    top_dishes = data["top_rated_dishes"]
    assert len(top_dishes) > 0
    for dish in top_dishes:
        assert dish["rating_count"] >= 5


def test_mensa_ranking_minimum_rating_floor(client, seed_data):
    """Mensa rankings should only include items with >= 5 ratings."""
    resp = client.get("/api/v1/stats/overview")
    assert resp.status_code == 200
    data = resp.json()

    mensas = data["mensa_rankings"]
    for mensa in mensas:
        assert mensa["total_ratings"] >= 5


def test_avg_rating_calculation(client, seed_data):
    """Average ratings should be correctly computed and rounded to 1 decimal."""
    resp = client.get("/api/v1/stats/overview")
    assert resp.status_code == 200
    data = resp.json()

    top_dishes = data["top_rated_dishes"]
    dish = next(d for d in top_dishes if d["name"] == "Pasta")
    assert dish["rating_count"] >= 5
    assert dish["avg_rating"] == 4.6


def test_total_counts(client, seed_data):
    """Total counts should match the seeded data."""
    resp = client.get("/api/v1/stats/overview")
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_ratings"] == 9
    assert data["total_meals"] == 3
    assert data["total_mensas"] == 2


# Regression: both endpoints below selected aggregates over Rating without ever
# joining it, so SQLAlchemy put `ratings` in the FROM clause unconstrained and
# every row was paired with every rating. Each dish reported the site-wide
# average, and per-mensa totals were multiplied by the mensa's meal count.
# seed_data holds: Mensa A -> Pasta (5 ratings, avg 4.6) + Currywurst (2, 3.5),
# Mensa B -> Salat (2 ratings, avg 4.5). Nine ratings, global average 4.3.

def test_mensa_stats_counts_only_its_own_ratings(client, seed_data):
    resp = client.get("/api/v1/stats/mensas")
    assert resp.status_code == 200
    by_name = {m["name"]: m for m in resp.json()}

    # Cross-joined, these were 18 and 9 -- meals-in-mensa x all ratings.
    assert by_name["Mensa A"]["total_ratings"] == 7
    assert by_name["Mensa B"]["total_ratings"] == 2

    assert by_name["Mensa A"]["total_meals"] == 2
    assert by_name["Mensa B"]["total_meals"] == 1

    # Mensa B is 5 and 4. Cross-joined it reported the global 4.3.
    assert by_name["Mensa B"]["avg_rating"] == 4.5


def test_mensa_stats_keeps_mensas_without_ratings(client, sqlite_db):
    """An unrated mensa still has meals, so it stays in the list with avg 0."""
    db = SessionLocal()
    try:
        mensa = Mensa(name="Mensa Leer")
        db.add(mensa)
        db.commit()
        db.refresh(mensa)
        db.add(Meal(name="Nudeln", name_de="Nudeln", type="main",
                    date=date_cls.today(), mensa_id=mensa.id))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/v1/stats/mensas")
    assert resp.status_code == 200
    entry = next(m for m in resp.json() if m["name"] == "Mensa Leer")
    assert entry["total_ratings"] == 0
    assert entry["total_meals"] == 1
    assert entry["avg_rating"] == 0


def test_top_dishes_aggregates_per_dish(client, seed_data):
    resp = client.get("/api/v1/stats/top-dishes")
    assert resp.status_code == 200
    by_name = {d["name"]: d for d in resp.json()}

    # Cross-joined, all three of these were (9, 4.3).
    assert (by_name["Pasta"]["rating_count"], by_name["Pasta"]["avg_rating"]) == (5, 4.6)
    assert (by_name["Currywurst"]["rating_count"], by_name["Currywurst"]["avg_rating"]) == (2, 3.5)
    assert (by_name["Salad"]["rating_count"], by_name["Salad"]["avg_rating"]) == (2, 4.5)


def test_top_dishes_excludes_unrated_dishes(client, seed_data, sqlite_db):
    """A dish nobody rated has no average and must not appear."""
    db = SessionLocal()
    try:
        mensa_id = db.query(Mensa).filter(Mensa.name == "Mensa A").first().id
        db.add(Meal(name="Ungetestet", name_de="Ungetestet", name_en="Untested",
                    type="main", date=date_cls.today(), mensa_id=mensa_id))
        db.commit()
    finally:
        db.close()

    names = [d["name"] for d in client.get("/api/v1/stats/top-dishes").json()]
    assert "Untested" not in names
    assert "Pasta" in names


def test_total_meals_counts_dishes_not_menu_rows(client, seed_data):
    """The same dish served on another day is one dish, not two.

    total_meals used count(DISTINCT DBMeal.id) -- the primary key, so DISTINCT
    removed nothing and the tile counted scraped menu rows. The label is
    "Gerichte" / "Meals", so it should count dishes.
    """
    db = SessionLocal()
    try:
        pasta = db.query(Meal).filter(Meal.name == "Pasta").first()
        db.add(Meal(
            name="Pasta", name_de="Pasta", name_en="Pasta",
            description="Tomatensoße", description_de="Tomatensoße",
            description_en="Tomato sauce", type="main",
            date=date_cls.today() + timedelta(days=1), mensa_id=pasta.mensa_id,
        ))
        db.commit()
    finally:
        db.close()

    data = client.get("/api/v1/stats/overview").json()
    # Pasta, Currywurst, Salat. Counting rows would now report 4.
    assert data["total_meals"] == 3


def test_total_meals_counts_same_name_at_two_mensas_separately(client, sqlite_db):
    """Dish identity is (name, mensa_id) throughout this module, not name alone."""
    db = SessionLocal()
    try:
        a, b = Mensa(name="Mensa A"), Mensa(name="Mensa B")
        db.add_all([a, b])
        db.commit()
        db.refresh(a)
        db.refresh(b)
        for mensa in (a, b):
            db.add(Meal(name="Pommes", name_de="Pommes", type="side",
                        date=date_cls.today(), mensa_id=mensa.id))
        db.commit()
    finally:
        db.close()

    assert client.get("/api/v1/stats/overview").json()["total_meals"] == 2
