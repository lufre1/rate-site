"""Comment flair (issue #35).

A comment can carry one optional label from a fixed set. The stored value is
a stable slug; the display text is translated on the client. Flair is
editable by the owner, and an explicit null clears it.

Runs against a private SQLite database created fresh for each test by the
`sqlite_db` fixture in conftest.py -- never a shared or ambient database.
"""
import pytest
from fastapi.testclient import TestClient

import main
from database import SessionLocal, Mensa, Meal
from datetime import date as date_cls


@pytest.fixture()
def client(monkeypatch, tmp_path, sqlite_db):
    """A TestClient wired to a throwaway SQLite schema and upload dir.

    Deliberately does NOT enter the app as a context manager, so the
    "on_startup" hook (init_db's Postgres-only ALTER TABLE calls, the live
    scraper run, the background scheduler) never fires.
    """
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


def register(client, username, password="correct-horse-battery"):
    return client.post("/api/v1/auth/register", json={"username": username, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_create_rating_with_flair(client, meal_id):
    """Anonymous creation with a flair stores it and the breakdown exposes it."""
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings",
        json={"rating": 4, "comment": "Sehr gut", "flair": "recommendation"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["flair"] == "recommendation"

    rating_id = resp.json()["id"]
    get = client.get(f"/api/v1/ratings/{rating_id}")
    assert get.status_code == 200
    assert get.json()["flair"] == "recommendation"

    breakdown = client.get(f"/api/v1/meals/{meal_id}/ratings-breakdown").json()
    row = next(c for c in breakdown["comments"] if c["id"] == rating_id)
    assert row["flair"] == "recommendation"


def test_create_rating_without_flair_defaults_null(client, meal_id):
    resp = client.post(f"/api/v1/meals/{meal_id}/ratings", json={"rating": 3, "comment": "ok"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["flair"] is None


@pytest.mark.parametrize("flair", main.FLAIRS)
def test_every_known_flair_is_accepted(client, meal_id, flair):
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings",
        json={"rating": 3, "comment": "c", "flair": flair},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["flair"] == flair


@pytest.mark.parametrize("flair", ["RECOMMENDATION", "meh", ""])
def test_create_rating_rejects_unknown_flair(client, meal_id, flair):
    """Case-sensitive and non-empty: the stored value is a stable slug, and
    the frontend only ever sends one of FLAIRS."""
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings",
        json={"rating": 3, "comment": "c", "flair": flair},
    )
    assert resp.status_code == 400
    assert "flair" in resp.json()["detail"]


def test_create_rating_with_photo_accepts_flair_form_field(client, meal_id):
    """The multipart route takes flair as a form field, like comment."""
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings-with-photo",
        data={"rating": 2, "comment": "Eher nicht", "flair": "do-not-eat"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["flair"] == "do-not-eat"


def test_create_rating_with_photo_rejects_unknown_flair(client, meal_id):
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings-with-photo",
        data={"rating": 2, "comment": "c", "flair": "nope"},
    )
    assert resp.status_code == 400


def test_update_own_rating_changes_flair(client, meal_id):
    token = register(client, "owner").json()["token"]
    created = client.post(
        f"/api/v1/meals/{meal_id}/ratings",
        json={"rating": 4, "comment": "c", "flair": "warning"},
        headers=bearer(token),
    )
    assert created.status_code == 201
    rating_id = created.json()["id"]

    # Change it
    resp = client.patch(
        f"/api/v1/ratings/{rating_id}",
        json={"flair": "unexpected"},
        headers=bearer(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["flair"] == "unexpected"

    # An explicit null clears it
    resp = client.patch(
        f"/api/v1/ratings/{rating_id}",
        json={"flair": None},
        headers=bearer(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["flair"] is None

    # Absent key leaves it untouched
    resp = client.patch(
        f"/api/v1/ratings/{rating_id}",
        json={"comment": "still here"},
        headers=bearer(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["flair"] is None


def test_update_flair_rejects_unknown_value(client, meal_id):
    token = register(client, "owner").json()["token"]
    created = client.post(
        f"/api/v1/meals/{meal_id}/ratings",
        json={"rating": 4, "comment": "c"},
        headers=bearer(token),
    )
    rating_id = created.json()["id"]

    resp = client.patch(
        f"/api/v1/ratings/{rating_id}",
        json={"flair": "nope"},
        headers=bearer(token),
    )
    assert resp.status_code == 400


def test_update_flair_requires_ownership(client, meal_id):
    """Anonymous rows are owned by nobody (owned_rating), so the authenticated
    PATCH refuses them exactly like every other field."""
    created = client.post(
        f"/api/v1/meals/{meal_id}/ratings",
        json={"rating": 4, "comment": "c"},
    )
    assert created.status_code == 201
    rating_id = created.json()["id"]

    token = register(client, "owner").json()["token"]
    resp = client.patch(
        f"/api/v1/ratings/{rating_id}",
        json={"flair": "warning"},
        headers=bearer(token),
    )
    assert resp.status_code == 403
