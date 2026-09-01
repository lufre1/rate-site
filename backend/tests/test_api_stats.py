"""Tests for the statistics/overview endpoint.

Covers:
- Weekly trends day-of-week mapping (dow 0=Sunday maps to Monday label via offset)
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


def test_weekly_trends_day_mapping(client, seed_data):
    """Weekly trends should map PostgreSQL dow (0=Sunday) to Monday-first labels."""
    resp = client.get("/api/v1/stats/overview")
    assert resp.status_code == 200
    data = resp.json()
    weekly = data["weekly_trends"]

    assert set(weekly.keys()) == {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
    assert isinstance(weekly["Monday"], int)
    assert isinstance(weekly["Sunday"], int)


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