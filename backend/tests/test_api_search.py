"""Regression tests for GET /api/v1/meals/search.

The search filter matched only `name` and `description`. scraper.py writes the
German text into both of those and into `name_de`/`description_de`, keeping the
English text in `name_en`/`description_en` -- so an English query returned
nothing even though the same dish was displayed in English on the menu view.

Runs against a private SQLite database created fresh for each test by the
`sqlite_db` fixture in conftest.py.
"""
from datetime import date as date_cls, timedelta

import pytest
from fastapi.testclient import TestClient

import main
from database import SessionLocal, Mensa, Meal


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
def seeded(client, sqlite_db):
    """One bilingual dish, dated today so the default future-only filter keeps it."""
    db = SessionLocal()
    try:
        mensa = Mensa(name="Zentralmensa")
        db.add(mensa)
        db.commit()
        db.refresh(mensa)
        db.add(Meal(
            name="Hähnchenbrust", name_de="Hähnchenbrust", name_en="Chicken breast",
            description="mit Reis", description_de="mit Reis",
            description_en="with rice",
            type="main", date=date_cls.today(), mensa_id=mensa.id,
        ))
        db.commit()
    finally:
        db.close()


def _names(resp):
    assert resp.status_code == 200
    return [m["name"] for m in resp.json()]


def test_english_query_matches_english_name(client, seeded):
    assert _names(client.get("/api/v1/meals/search?q=chicken&lang=en")) == ["Chicken breast"]


def test_english_query_matches_english_description(client, seeded):
    assert _names(client.get("/api/v1/meals/search?q=rice&lang=en")) == ["Chicken breast"]


def test_german_query_still_matches(client, seeded):
    assert _names(client.get("/api/v1/meals/search?q=Hähnchen&lang=de")) == ["Hähnchenbrust"]


def test_german_query_works_on_the_english_ui(client, seeded):
    """People type the German dish name even with the site in English."""
    assert _names(client.get("/api/v1/meals/search?q=Hähnchen&lang=en")) == ["Chicken breast"]


def test_match_in_several_columns_returns_one_row(client, seeded):
    """"Reis" hits description and description_de; the dish must not be listed twice."""
    assert _names(client.get("/api/v1/meals/search?q=Reis&lang=de")) == ["Hähnchenbrust"]


def test_unrelated_query_matches_nothing(client, seeded):
    assert _names(client.get("/api/v1/meals/search?q=zzzznotadish&lang=en")) == []


def test_past_dishes_need_the_past_flag(client, sqlite_db):
    db = SessionLocal()
    try:
        mensa = Mensa(name="CGiN")
        db.add(mensa)
        db.commit()
        db.refresh(mensa)
        db.add(Meal(
            name="Linsensuppe", name_de="Linsensuppe", name_en="Lentil soup",
            type="main", date=date_cls.today() - timedelta(days=3), mensa_id=mensa.id,
        ))
        db.commit()
    finally:
        db.close()

    assert _names(client.get("/api/v1/meals/search?q=lentil&lang=en")) == []
    assert _names(client.get("/api/v1/meals/search?q=lentil&lang=en&past=true")) == ["Lentil soup"]
