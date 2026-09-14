"""Test vote stuffing prevention for comment and photo votes.

The vote-stuffing logic now keys votes on `user_id` when signed in, and on
`voter_id` when anonymous. This file tests:

1. Signed-in user voting on a comment: first vote creates, second same-direction
   toggles off, opposite switches.
2. Anonymous user with the SAME voter_id: first vote creates, second same-direction
   toggles off.
3. Anonymous user with DIFFERENT voter_ids: both votes count.
4. Same three scenarios for photo votes.
5. get_vote_status / get_photo_vote_status return the correct direction for
   signed-in users regardless of the X-Voter-Id header (keyed on user_id).

Runs against a private SQLite database created fresh for each test by the
`sqlite_db` fixture in conftest.py -- never a shared or ambient database.
"""
import pytest
from fastapi.testclient import TestClient

import main
from database import SessionLocal, Mensa, Meal


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
            date=None, mensa_id=mensa.id,
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


VOTER = {"X-Voter-Id": "v_test_voter"}
OTHER_VOTER = {"X-Voter-Id": "v_other_voter"}


# --------------------------------------------------------------------------
# Comment votes
# --------------------------------------------------------------------------


def test_comment_vote_signed_in_toggles(client, meal_id):
    """Signed-in user: first vote creates, second same-direction toggles off,
    opposite switches."""
    token = register(client, "alice").json()["token"]

    # Create a rating with a comment
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings",
        json={"rating": 4, "comment": "Nice"},
        headers=bearer(token),
    )
    assert resp.status_code == 201
    rating_id = resp.json()["id"]

    # First vote should succeed
    vote_data = {"direction": 1}
    headers = {**bearer(token), **VOTER}
    vote_resp = client.put(f"/api/v1/ratings/{rating_id}/vote", json=vote_data, headers=headers)
    assert vote_resp.status_code == 200
    assert vote_resp.json()["direction"] == 1

    # Second same-direction vote should toggle off (remove vote)
    vote_resp2 = client.put(f"/api/v1/ratings/{rating_id}/vote", json=vote_data, headers=headers)
    assert vote_resp2.status_code == 200
    assert vote_resp2.json()["direction"] is None

    # Third vote (opposite direction) should switch
    flip = client.put(f"/api/v1/ratings/{rating_id}/vote", json={"direction": -1}, headers=headers)
    assert flip.status_code == 200
    assert flip.json()["direction"] == -1


def test_comment_vote_anonymous_same_voter_id_toggles(client, meal_id):
    """Anonymous user with the SAME voter_id: first vote creates, second same-direction toggles off."""
    # Create a rating with a comment (anonymous)
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings",
        json={"rating": 4, "comment": "Nice"},
    )
    assert resp.status_code == 201
    rating_id = resp.json()["id"]

    # First vote
    headers = VOTER
    vote_data = {"direction": 1}
    vote_resp1 = client.put(f"/api/v1/ratings/{rating_id}/vote", json=vote_data, headers=headers)
    assert vote_resp1.status_code == 200
    assert vote_resp1.json()["direction"] == 1

    # Second vote with same voter_id should toggle off
    vote_resp2 = client.put(f"/api/v1/ratings/{rating_id}/vote", json=vote_data, headers=headers)
    assert vote_resp2.status_code == 200
    assert vote_resp2.json()["direction"] is None


def test_comment_vote_anonymous_different_voter_ids(client, meal_id):
    """Different anonymous voter_ids can both vote on the same comment."""
    # Create a rating with a comment (anonymous)
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings",
        json={"rating": 4, "comment": "Nice"},
    )
    assert resp.status_code == 201
    rating_id = resp.json()["id"]

    # First anonymous vote
    headers1 = VOTER
    vote_data = {"direction": 1}
    vote_resp1 = client.put(f"/api/v1/ratings/{rating_id}/vote", json=vote_data, headers=headers1)
    assert vote_resp1.status_code == 200
    assert vote_resp1.json()["direction"] == 1

    # Second anonymous vote with different voter_id should succeed
    headers2 = OTHER_VOTER
    vote_resp2 = client.put(f"/api/v1/ratings/{rating_id}/vote", json=vote_data, headers=headers2)
    assert vote_resp2.status_code == 200
    assert vote_resp2.json()["direction"] == 1


def test_comment_vote_status_uses_user_id_not_voter_id(client, meal_id):
    """get_vote_status uses user_id for signed-in users, not the X-Voter-Id header."""
    token = register(client, "bob").json()["token"]

    # Create a rating with a comment
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings",
        json={"rating": 4, "comment": "Nice"},
        headers=bearer(token),
    )
    assert resp.status_code == 201
    rating_id = resp.json()["id"]

    # Vote with one voter_id
    headers = {**bearer(token), **VOTER}
    vote_data = {"direction": 1}
    client.put(f"/api/v1/ratings/{rating_id}/vote", json=vote_data, headers=headers)

    # Get status with same voter_id - should show vote
    status_resp = client.get(f"/api/v1/ratings/{rating_id}/vote", headers=headers)
    assert status_resp.status_code == 200
    assert status_resp.json()["direction"] == 1

    # Get status with different voter_id - should still show vote because it's keyed by user_id
    headers_different = {**bearer(token), **OTHER_VOTER}
    status_resp2 = client.get(f"/api/v1/ratings/{rating_id}/vote", headers=headers_different)
    assert status_resp2.status_code == 200
    assert status_resp2.json()["direction"] == 1


# --------------------------------------------------------------------------
# Photo votes
# --------------------------------------------------------------------------


def test_photo_vote_signed_in_toggles(client, meal_id):
    """Signed-in user: first photo vote creates, second same-direction toggles off."""
    token = register(client, "carol").json()["token"]

    # Create a rating with a photo via multipart form
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x00\x05\xfe\xd8\x00\x00\x00\x00IEND\xaeB`\x82"
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings-with-photo",
        data={"rating": "4", "comment": "Nice"},
        files={"photo": ("test.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 201
    rating_id = resp.json()["id"]

    # First photo vote should succeed
    vote_data = {"direction": 1}
    headers = {**bearer(token), **VOTER}
    vote_resp = client.put(f"/api/v1/ratings/{rating_id}/photo-vote", json=vote_data, headers=headers)
    assert vote_resp.status_code == 200
    assert vote_resp.json()["direction"] == 1

    # Second same-direction vote should toggle off
    vote_resp2 = client.put(f"/api/v1/ratings/{rating_id}/photo-vote", json=vote_data, headers=headers)
    assert vote_resp2.status_code == 200
    assert vote_resp2.json()["direction"] is None

    # Third vote (opposite direction) should switch
    flip = client.put(f"/api/v1/ratings/{rating_id}/photo-vote", json={"direction": -1}, headers=headers)
    assert flip.status_code == 200
    assert flip.json()["direction"] == -1


def test_photo_vote_anonymous_same_voter_id_toggles(client, meal_id):
    """Anonymous user with the SAME voter_id: first photo vote creates, second same-direction toggles off."""
    # Create a rating with a photo via multipart form
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x00\x05\xfe\xd8\x00\x00\x00\x00IEND\xaeB`\x82"
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings-with-photo",
        data={"rating": "4", "comment": "Nice"},
        files={"photo": ("test.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 201
    rating_id = resp.json()["id"]

    # First photo vote
    headers = VOTER
    vote_data = {"direction": 1}
    vote_resp1 = client.put(f"/api/v1/ratings/{rating_id}/photo-vote", json=vote_data, headers=headers)
    assert vote_resp1.status_code == 200
    assert vote_resp1.json()["direction"] == 1

    # Second vote with same voter_id should toggle off
    vote_resp2 = client.put(f"/api/v1/ratings/{rating_id}/photo-vote", json=vote_data, headers=headers)
    assert vote_resp2.status_code == 200
    assert vote_resp2.json()["direction"] is None


def test_photo_vote_anonymous_different_voter_ids(client, meal_id):
    """Different anonymous voter_ids can both vote on the same photo."""
    # Create a rating with a photo via multipart form
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x00\x05\xfe\xd8\x00\x00\x00\x00IEND\xaeB`\x82"
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings-with-photo",
        data={"rating": "4", "comment": "Nice"},
        files={"photo": ("test.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 201
    rating_id = resp.json()["id"]

    # First anonymous photo vote
    headers1 = VOTER
    vote_data = {"direction": 1}
    vote_resp1 = client.put(f"/api/v1/ratings/{rating_id}/photo-vote", json=vote_data, headers=headers1)
    assert vote_resp1.status_code == 200
    assert vote_resp1.json()["direction"] == 1

    # Second anonymous photo vote with different voter_id should succeed
    headers2 = OTHER_VOTER
    vote_resp2 = client.put(f"/api/v1/ratings/{rating_id}/photo-vote", json=vote_data, headers=headers2)
    assert vote_resp2.status_code == 200
    assert vote_resp2.json()["direction"] == 1


def test_photo_vote_status_uses_user_id_not_voter_id(client, meal_id):
    """get_photo_vote_status uses user_id for signed-in users, not the X-Voter-Id header."""
    token = register(client, "dave").json()["token"]

    # Create a rating with a photo via multipart form
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x00\x05\xfe\xd8\x00\x00\x00\x00IEND\xaeB`\x82"
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings-with-photo",
        data={"rating": "4", "comment": "Nice"},
        files={"photo": ("test.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 201
    rating_id = resp.json()["id"]

    # Photo vote with one voter_id
    headers = {**bearer(token), **VOTER}
    vote_data = {"direction": 1}
    client.put(f"/api/v1/ratings/{rating_id}/photo-vote", json=vote_data, headers=headers)

    # Get status with same voter_id - should show vote
    status_resp = client.get(f"/api/v1/ratings/{rating_id}/photo-vote", headers=headers)
    assert status_resp.status_code == 200
    assert status_resp.json()["direction"] == 1

    # Get status with different voter_id - should still show vote because it's keyed by user_id
    headers_different = {**bearer(token), **OTHER_VOTER}
    status_resp2 = client.get(f"/api/v1/ratings/{rating_id}/photo-vote", headers=headers_different)
    assert status_resp2.status_code == 200
    assert status_resp2.json()["direction"] == 1