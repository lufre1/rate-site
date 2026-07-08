"""API regression tests for ratings/photos endpoints.

Covers bugs found during manual QA of the mensa rating UI:
- POST /ratings (JSON) accepts and validates a 1-5 rating.
- POST /ratings-with-photo accepts rating/comment as multipart form fields
  (not query params), matching what the frontend actually sends.
- GET /ratings includes meal_id and a real date (previously crashed with a
  Pydantic ValidationError because meal_id was never passed to the response
  model, which is what made the "click on comments" white screen happen once
  the frontend hook bug was also fixed).
- GET /photos returns a non-empty date for each photo.

Runs entirely against an isolated SQLite database (no live server, no
Postgres needed) -- see conftest.py for the DATABASE_URL default.
"""
import base64
import os
from datetime import date as date_cls

import pytest
from fastapi.testclient import TestClient

import main
from database import Base, engine, SessionLocal, Mensa, Meal

# 2x2 red pixel PNG, reused from test_photo_upload.py.
PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAAsTAAALEwEAmpwYAAAAAXNS"
    "R0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAkSURBVDhPY2RgYGBgAAEYAQABYDCqAAAAAElFTkSuQmCC"
)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """A TestClient wired to a throwaway SQLite schema and upload dir.

    Deliberately does NOT enter the app as a context manager, so the
    "on_startup" hook (init_db's Postgres-only ALTER TABLE calls, the live
    scraper run, the background scheduler) never fires.
    """
    monkeypatch.setattr(main, "UPLOAD_DIR", str(tmp_path))

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

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
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def meal_id(client):
    """Seed one mensa + one main-course meal, return the meal's id."""
    db = SessionLocal()
    try:
        mensa = Mensa(name="Testmensa")
        db.add(mensa)
        db.commit()
        db.refresh(mensa)

        meal = Meal(
            name="Testgericht", name_de="Testgericht", name_en="Test Dish",
            description="Reis, Bohnen", description_de="Reis, Bohnen",
            description_en="Rice, Beans", tags=None, type="main",
            date=date_cls.today(), mensa_id=mensa.id,
        )
        db.add(meal)
        db.commit()
        db.refresh(meal)
        return meal.id
    finally:
        db.close()


def test_create_rating_json(client, meal_id):
    resp = client.post(f"/api/v1/meals/{meal_id}/ratings", json={"rating": 4, "comment": "Nice"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["rating"] == 4
    assert body["comment"] == "Nice"


@pytest.mark.parametrize("bad_rating", [0, 6, -1])
def test_create_rating_rejects_out_of_range(client, meal_id, bad_rating):
    resp = client.post(f"/api/v1/meals/{meal_id}/ratings", json={"rating": bad_rating})
    assert resp.status_code == 422


def test_get_ratings_includes_meal_id_and_date(client, meal_id):
    """Regression test: this endpoint used to 500 because RatingOutWithDate
    requires meal_id but the response was built without it."""
    create = client.post(f"/api/v1/meals/{meal_id}/ratings", json={"rating": 5, "comment": "Great"})
    assert create.status_code == 201

    resp = client.get(f"/api/v1/meals/{meal_id}/ratings")
    assert resp.status_code == 200
    reviews = resp.json()
    assert len(reviews) == 1
    assert reviews[0]["meal_id"] == meal_id
    assert reviews[0]["date"]  # non-empty ISO date string


def test_create_rating_with_photo_via_form_fields(client, meal_id):
    """Regression test: rating/comment must be accepted as multipart form
    fields (the frontend sends FormData), not query parameters."""
    png_bytes = base64.b64decode(PNG_BASE64)
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings-with-photo",
        data={"rating": 5, "comment": "Tasty"},
        files={"photo": ("test.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["rating"] == 5
    assert body["comment"] == "Tasty"
    assert body["photo_url"]


def test_photo_upload_rejects_out_of_range_rating(client, meal_id):
    png_bytes = base64.b64decode(PNG_BASE64)
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings-with-photo",
        data={"rating": 6},
        files={"photo": ("test.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 422


def test_photos_endpoint_returns_meal_date(client, meal_id):
    """Regression test: /photos used to always return date="" because it
    read a nonexistent `rating_date` attribute."""
    png_bytes = base64.b64decode(PNG_BASE64)
    upload = client.post(
        f"/api/v1/meals/{meal_id}/ratings-with-photo",
        data={"rating": 4},
        files={"photo": ("test.png", png_bytes, "image/png")},
    )
    assert upload.status_code == 201

    resp = client.get(f"/api/v1/meals/{meal_id}/photos")
    assert resp.status_code == 200
    photos = resp.json()
    assert len(photos) == 1
    assert photos[0]["date"] == date_cls.today().isoformat()


def test_side_ratings_round_trip(client, meal_id):
    create = client.post(
        f"/api/v1/meals/{meal_id}/side-ratings",
        json={"side_name": "Reis", "rating": 4},
    )
    assert create.status_code == 201

    resp = client.get(f"/api/v1/meals/{meal_id}/side-ratings")
    assert resp.status_code == 200
    sides = resp.json()
    assert any(s["side_name"] == "Reis" and s["rating_count"] == 1 for s in sides)
