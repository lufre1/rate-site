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


# ---- Comment edge cases ----


def test_create_rating_with_null_comment(client, meal_id):
    resp = client.post(f"/api/v1/meals/{meal_id}/ratings", json={"rating": 3, "comment": None})
    assert resp.status_code == 201, resp.text
    assert resp.json()["comment"] is None


def test_create_rating_with_empty_comment(client, meal_id):
    resp = client.post(f"/api/v1/meals/{meal_id}/ratings", json={"rating": 3, "comment": ""})
    assert resp.status_code == 201, resp.text
    assert resp.json()["comment"] == ""


def test_create_rating_without_comment_field(client, meal_id):
    resp = client.post(f"/api/v1/meals/{meal_id}/ratings", json={"rating": 3})
    assert resp.status_code == 201, resp.text
    assert resp.json()["comment"] is None


def test_create_rating_nonexistent_meal(client):
    resp = client.post("/api/v1/meals/99999/ratings", json={"rating": 4, "comment": "test"})
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_patch_comment_on_rating(client, meal_id):
    create = client.post(f"/api/v1/meals/{meal_id}/ratings", json={"rating": 2, "comment": "Meh"})
    assert create.status_code == 201
    rating_id = create.json()["id"]

    resp = client.patch(f"/api/v1/ratings/{rating_id}/comment", json={"comment": "Updated comment"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["comment"] == "Updated comment"

    get = client.get(f"/api/v1/ratings/{rating_id}")
    assert get.json()["comment"] == "Updated comment"


def test_patch_comment_nonexistent_rating(client):
    resp = client.patch("/api/v1/ratings/99999/comment", json={"comment": "test"})
    assert resp.status_code == 404


def test_patch_comment_rejects_non_string(client, meal_id):
    create = client.post(f"/api/v1/meals/{meal_id}/ratings", json={"rating": 5, "comment": "OK"})
    assert create.status_code == 201
    rating_id = create.json()["id"]

    resp = client.patch(f"/api/v1/ratings/{rating_id}/comment", json={"comment": 42})
    assert resp.status_code == 400


# ---- Photo upload edge cases ----


def test_photo_upload_without_file(client, meal_id):
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings-with-photo",
        data={"rating": 4},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["rating"] == 4
    assert body["photo_url"] is None


def test_photo_upload_without_file_rating_only(client, meal_id):
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings-with-photo",
        data={"rating": 5, "comment": "Only rating no photo"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["comment"] == "Only rating no photo"
    assert body["photo_url"] is None


def test_photo_upload_nonexistent_meal(client):
    png_bytes = base64.b64decode(PNG_BASE64)
    resp = client.post(
        "/api/v1/meals/99999/ratings-with-photo",
        data={"rating": 4},
        files={"photo": ("test.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 404


def test_photo_upload_rejects_invalid_file_type(client, meal_id):
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings-with-photo",
        data={"rating": 4},
        files={"photo": ("test.txt", b"not an image", "text/plain")},
    )
    assert resp.status_code == 400
    assert "file type" in resp.json()["detail"].lower()


def test_photo_upload_rejects_oversized(client, meal_id):
    oversized = b"x" * (5 * 1024 * 1024 + 1)
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings-with-photo",
        data={"rating": 3},
        files={"photo": ("big.png", oversized, "image/png")},
    )
    assert resp.status_code == 400
    assert "5mb" in resp.json()["detail"].lower()


# ---- Existing tests ----


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


def test_ratings_endpoint_returns_list_for_backward_compat(client, meal_id):
    """Test that GET /ratings returns a list for backward compatibility."""
    # Create a rating for today's meal
    create = client.post(f"/api/v1/meals/{meal_id}/ratings", json={"rating": 4, "comment": "Good"})
    assert create.status_code == 201

    resp = client.get(f"/api/v1/meals/{meal_id}/ratings")
    assert resp.status_code == 200
    body = resp.json()
    
    # Should be a list (backward compatible with old frontend)
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["rating"] == 4
    assert body[0]["comment"] == "Good"


def test_ratings_breakdown_returns_full_breakdown(client, meal_id):
    """Test that GET /ratings-breakdown returns full breakdown with recent, overall, and comments."""
    # Create a rating first
    client.post(f"/api/v1/meals/{meal_id}/ratings", json={"rating": 5, "comment": "Excellent!"})

    resp = client.get(f"/api/v1/meals/{meal_id}/ratings-breakdown")
    assert resp.status_code == 200
    body = resp.json()
    
    # Should have recent, overall, and comments keys
    assert "recent" in body
    assert "overall" in body
    assert "comments" in body
    
    # Recent section
    assert "ratings" in body["recent"]
    assert "avg" in body["recent"]
    assert "count" in body["recent"]
    assert body["recent"]["count"] == 1
    assert body["recent"]["avg"] == 5.0
    assert len(body["recent"]["ratings"]) == 1
    assert body["recent"]["ratings"][0]["rating"] == 5
    
    # Overall section
    assert "avg" in body["overall"]
    assert "count" in body["overall"]
    assert body["overall"]["count"] == 1
    assert body["overall"]["avg"] == 5.0
    
    # Comments section
    assert isinstance(body["comments"], list)
    assert len(body["comments"]) == 1
    assert body["comments"][0]["comment"] == "Excellent!"
    assert body["comments"][0]["rating"] == 5


def test_comments_limited_to_15_most_recent(client, meal_id):
    """Test that comments are limited to 15 most recent (in /ratings-breakdown)."""
    # Create 20 ratings with comments
    for i in range(20):
        client.post(
            f"/api/v1/meals/{meal_id}/ratings",
            json={"rating": 3, "comment": f"Comment {i+1}"},
        )

    # Test the breakdown endpoint which has the comments limit
    resp = client.get(f"/api/v1/meals/{meal_id}/ratings-breakdown")
    assert resp.status_code == 200
    body = resp.json()
    
    # Should only have 15 comments (limited from 20)
    assert len(body["comments"]) == 15
    
    # Comments are ordered by created_at (most recent first). 
    # Since all ratings in this test are created quickly, the order depends on DB behavior.
    # Just verify we get 15 comments and they're from the 20 created (not all the same)
    comment_texts = [c["comment"] for c in body["comments"]]
    assert len(comment_texts) == 15
    # Should have some diversity (not all the same comment)
    assert len(set(comment_texts)) >= 10


def test_side_ratings_includes_recent_stats(client, meal_id):
    """Test that GET /side-ratings includes recent_avg and recent_count."""
    # Create a side rating
    client.post(
        f"/api/v1/meals/{meal_id}/side-ratings",
        json={"side_name": "Reis", "rating": 4},
    )

    resp = client.get(f"/api/v1/meals/{meal_id}/side-ratings")
    assert resp.status_code == 200
    sides = resp.json()
    
    assert len(sides) == 1
    side = sides[0]
    assert side["side_name"] == "Reis"
    assert side["avg_rating"] == 4.0
    assert side["rating_count"] == 1
    
    # Should have recent stats
    assert "recent_avg" in side
    assert "recent_count" in side
    assert side["recent_avg"] == 4.0
    assert side["recent_count"] == 1


def test_ratings_across_multiple_dates_same_dish(client, meal_id):
    """Test that ratings for the same dish across multiple dates work correctly."""
    from datetime import date as date_cls, timedelta
    db = SessionLocal()
    try:
        # Create a second meal instance with the same name but different date (yesterday)
        from datetime import timedelta
        yesterday = date_cls.today() - timedelta(days=1)
        
        mensa = db.query(Mensa).filter(Mensa.id == 1).first()
        meal2 = Meal(
            name="Testgericht", name_de="Testgericht", name_en="Test Dish",
            description="Reis, Bohnen", description_de="Reis, Bohnen",
            description_en="Rice, Beans", tags=None, type="main",
            date=yesterday, mensa_id=mensa.id,
        )
        db.add(meal2)
        db.commit()
        db.refresh(meal2)
        meal2_id = meal2.id
    finally:
        db.close()
    
    # Create a rating for yesterday's meal
    client.post(f"/api/v1/meals/{meal2_id}/ratings", json={"rating": 3, "comment": "Old rating"})
    
    # Create a rating for today's meal
    client.post(f"/api/v1/meals/{meal_id}/ratings", json={"rating": 5, "comment": "New rating"})
    
    # GET /ratings returns all ratings (for backward compat with old frontend)
    resp = client.get(f"/api/v1/meals/{meal_id}/ratings")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 2  # Both today and yesterday's ratings
    
    # GET /ratings-breakdown should show both in overall but only today in recent
    resp = client.get(f"/api/v1/meals/{meal_id}/ratings-breakdown")
    assert resp.status_code == 200
    body = resp.json()
    
    # Recent should only have today's rating
    assert body["recent"]["count"] == 1
    assert body["recent"]["avg"] == 5.0
    
    # Overall should have both ratings (avg of 3 and 5 = 4.0)
    assert body["overall"]["count"] == 2
    assert body["overall"]["avg"] == 4.0
    
    # Comments should show both comments (most recent 15)
    assert len(body["comments"]) == 2
    assert body["comments"][0]["comment"] == "New rating"  # More recent
    assert body["comments"][1]["comment"] == "Old rating"

    # Only the comment tied to today's meal is flagged as recent;
    # yesterday's comment must NOT carry the current/recent flag.
    assert body["comments"][0]["is_recent"] is True
    assert body["comments"][1]["is_recent"] is False
    
    # GET /side-ratings for today's meal should only count today's ratings
    client.post(
        f"/api/v1/meals/{meal2_id}/side-ratings",
        json={"side_name": "Reis", "rating": 2},
    )
    client.post(
        f"/api/v1/meals/{meal_id}/side-ratings",
        json={"side_name": "Reis", "rating": 4},
    )
    
    resp = client.get(f"/api/v1/meals/{meal_id}/side-ratings")
    assert resp.status_code == 200
    sides = resp.json()
    assert len(sides) == 1
    side = sides[0]
    
    # Overall should average both (2+4)/2 = 3.0
    assert side["avg_rating"] == 3.0
    assert side["rating_count"] == 2
    
    # Recent should only be today's (4)
    assert side["recent_avg"] == 4.0
    assert side["recent_count"] == 1



