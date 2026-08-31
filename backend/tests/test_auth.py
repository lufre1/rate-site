"""API tests for the accounts feature.

Covers the register/login/session round-trip, that anonymous rating still works
untouched, and that one user cannot edit or delete another user's rating.

Runs against a private SQLite database created fresh for each test by the
`sqlite_db` fixture in conftest.py -- never a shared or ambient database.
"""
from datetime import date as date_cls

import pytest
from fastapi.testclient import TestClient

import main
from database import SessionLocal, Mensa, Meal

GOOD_PW = "correct-horse-battery"


@pytest.fixture()
def client(monkeypatch, tmp_path, sqlite_db):
    """TestClient on a throwaway schema. Same shape as tests/test_api_ratings.py.

    Not used as a context manager, so the on_startup hook (Postgres-only ALTERs,
    the live scraper, the scheduler) never fires.
    """
    monkeypatch.setattr(main, "UPLOAD_DIR", str(tmp_path))

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    # get_db lives in database.py and is the same object main and auth both
    # depend on, so this single override covers the auth dependencies too.
    main.app.dependency_overrides[main.get_db] = override_get_db
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


@pytest.fixture()
def meal_id(sqlite_db):
    db = SessionLocal()
    try:
        mensa = Mensa(name="Zentralmensa")
        db.add(mensa)
        db.commit()
        db.refresh(mensa)
        meal = Meal(name="Testgericht", name_de="Testgericht", type="main",
                    date=date_cls.today(), mensa_id=mensa.id, description="Reis, Salat")
        db.add(meal)
        db.commit()
        db.refresh(meal)
        return meal.id
    finally:
        db.close()


def register(client, username, password=GOOD_PW):
    return client.post("/api/v1/auth/register", json={"username": username, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------- register/login

def test_register_login_me_round_trip(client):
    resp = register(client, "alice")
    assert resp.status_code == 201, resp.text
    token = resp.json()["token"]
    assert resp.json()["username"] == "alice"

    me = client.get("/api/v1/me", headers=bearer(token))
    assert me.status_code == 200
    assert me.json()["username"] == "alice"
    assert me.json()["rating_count"] == 0

    login = client.post("/api/v1/auth/login", json={"username": "alice", "password": GOOD_PW})
    assert login.status_code == 200
    assert client.get("/api/v1/me", headers=bearer(login.json()["token"])).status_code == 200


def test_duplicate_username_rejected(client):
    assert register(client, "bob").status_code == 201
    assert register(client, "bob").status_code == 409
    # Case-insensitive: "Bob" must not be able to squat on "bob".
    assert register(client, "BOB").status_code == 409


@pytest.mark.parametrize("username,password", [
    ("ab", GOOD_PW),                 # too short
    ("a" * 31, GOOD_PW),             # too long
    ("has space", GOOD_PW),          # illegal character
    ("carol", "short"),              # password under 8 chars
])
def test_invalid_credentials_rejected(client, username, password):
    assert register(client, username, password).status_code == 400


def test_login_failures_are_indistinguishable(client):
    register(client, "dave")
    wrong_pw = client.post("/api/v1/auth/login", json={"username": "dave", "password": "wrong-password"})
    no_user = client.post("/api/v1/auth/login", json={"username": "nobody", "password": "wrong-password"})
    assert wrong_pw.status_code == no_user.status_code == 401
    # Same body, so the endpoint is not a username oracle.
    assert wrong_pw.json() == no_user.json()


def test_me_requires_a_valid_token(client):
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers=bearer("garbage")).status_code == 401
    assert client.get("/api/v1/me", headers={"Authorization": "Basic xyz"}).status_code == 401


def test_logout_invalidates_the_token(client):
    token = register(client, "erin").json()["token"]
    assert client.post("/api/v1/auth/logout", headers=bearer(token)).status_code == 204
    assert client.get("/api/v1/me", headers=bearer(token)).status_code == 401


# ------------------------------------------------------------------- rating identity

def test_anonymous_rating_still_works(client, meal_id):
    resp = client.post(f"/api/v1/meals/{meal_id}/ratings", json={"rating": 4, "comment": "fine"})
    assert resp.status_code == 201
    assert resp.json()["user_name"]           # still gets a generated funny name
    assert resp.json().get("user_id") is None


def test_signed_in_rating_uses_the_real_username(client, meal_id):
    token = register(client, "frank").json()["token"]
    resp = client.post(f"/api/v1/meals/{meal_id}/ratings",
                       json={"rating": 5, "comment": "great"}, headers=bearer(token))
    assert resp.status_code == 201
    assert resp.json()["user_name"] == "frank"


def test_signed_in_side_rating_uses_the_real_username(client, meal_id):
    """The easy one to forget -- side ratings have their own creation path."""
    token = register(client, "grace").json()["token"]
    resp = client.post(f"/api/v1/meals/{meal_id}/side-ratings",
                       json={"side_name": "Reis", "rating": 3}, headers=bearer(token))
    assert resp.status_code == 201
    assert resp.json()["user_name"] == "grace"


# ------------------------------------------------------------------- my ratings

def test_my_ratings_and_derived_favourites(client, meal_id):
    token = register(client, "heidi").json()["token"]
    for score in (5, 4, 2):
        client.post(f"/api/v1/meals/{meal_id}/ratings", json={"rating": score}, headers=bearer(token))
    # Someone else's rating must not leak into the list.
    other = register(client, "ivan").json()["token"]
    client.post(f"/api/v1/meals/{meal_id}/ratings", json={"rating": 1}, headers=bearer(other))

    mine = client.get("/api/v1/me/ratings", headers=bearer(token))
    assert mine.status_code == 200
    assert sorted(r["rating"] for r in mine.json()) == [2, 4, 5]
    assert mine.json()[0]["meal_name"] == "Testgericht"
    assert mine.json()[0]["mensa"] == "Zentralmensa"

    favs = client.get("/api/v1/me/ratings?min_rating=4&sort=rating", headers=bearer(token))
    assert [r["rating"] for r in favs.json()] == [5, 4]

    assert client.get("/api/v1/me/ratings").status_code == 401


# ------------------------------------------------------------------- ownership

def test_cannot_edit_or_delete_another_users_rating(client, meal_id):
    a_token = register(client, "judy").json()["token"]
    b_token = register(client, "mallory").json()["token"]

    rating_id = client.post(f"/api/v1/meals/{meal_id}/ratings",
                            json={"rating": 5}, headers=bearer(a_token)).json()["id"]

    assert client.patch(f"/api/v1/ratings/{rating_id}",
                        json={"rating": 1}, headers=bearer(b_token)).status_code == 403
    assert client.delete(f"/api/v1/ratings/{rating_id}", headers=bearer(b_token)).status_code == 403
    # Legacy comment route must respect ownership too.
    assert client.patch(f"/api/v1/ratings/{rating_id}/comment",
                        json={"comment": "hijacked"}, headers=bearer(b_token)).status_code == 403
    assert client.patch(f"/api/v1/ratings/{rating_id}/comment",
                        json={"comment": "hijacked"}).status_code == 403

    # The owner can.
    assert client.patch(f"/api/v1/ratings/{rating_id}",
                        json={"rating": 3, "comment": "edited"}, headers=bearer(a_token)).status_code == 200
    assert client.delete(f"/api/v1/ratings/{rating_id}", headers=bearer(a_token)).status_code == 204
    assert client.get(f"/api/v1/ratings/{rating_id}").status_code == 404


def test_anonymous_ratings_are_not_owned_by_anyone(client, meal_id):
    token = register(client, "niaj").json()["token"]
    rating_id = client.post(f"/api/v1/meals/{meal_id}/ratings", json={"rating": 4}).json()["id"]

    # No account owns it, so the authenticated routes refuse it...
    assert client.patch(f"/api/v1/ratings/{rating_id}", json={"rating": 1},
                        headers=bearer(token)).status_code == 403
    assert client.delete(f"/api/v1/ratings/{rating_id}", headers=bearer(token)).status_code == 403
    # ...but the pre-accounts comment route still works, as it always did.
    assert client.patch(f"/api/v1/ratings/{rating_id}/comment",
                        json={"comment": "late comment"}).status_code == 200


# --------------------------------------------------------------- display name

def test_get_display_name_in_me_response(client):
    register(client, "alice")
    login = client.post("/api/v1/auth/login", json={"username": "alice", "password": GOOD_PW})
    assert login.status_code == 200
    token = login.json()["token"]
    me = client.get("/api/v1/me", headers=bearer(token))
    assert me.status_code == 200
    assert me.json()["username"] == "alice"
    assert me.json()["display_name"] is None


def test_set_display_name(client):
    register(client, "bob")
    login = client.post("/api/v1/auth/login", json={"username": "bob", "password": GOOD_PW})
    token = login.json()["token"]

    resp = client.patch("/api/v1/me/display-name", json={"display_name": "Bobster"},
                        headers=bearer(token))
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Bobster"

    me = client.get("/api/v1/me", headers=bearer(token))
    assert me.json()["display_name"] == "Bobster"


def test_clear_display_name(client):
    register(client, "carol")
    login = client.post("/api/v1/auth/login", json={"username": "carol", "password": GOOD_PW})
    token = login.json()["token"]

    client.patch("/api/v1/me/display-name", json={"display_name": "Carol Fan"},
                 headers=bearer(token))
    me = client.get("/api/v1/me", headers=bearer(token))
    assert me.json()["display_name"] == "Carol Fan"

    resp = client.patch("/api/v1/me/display-name", json={"display_name": None},
                        headers=bearer(token))
    assert resp.status_code == 200
    assert resp.json()["display_name"] is None

    me = client.get("/api/v1/me", headers=bearer(token))
    assert me.json()["display_name"] is None


def test_display_name_on_ratings(client, meal_id):
    token = register(client, "dave").json()["token"]

    client.patch("/api/v1/me/display-name", json={"display_name": "Dave Fan"},
                 headers=bearer(token))

    resp = client.post(f"/api/v1/meals/{meal_id}/ratings",
                       json={"rating": 5, "comment": "great"}, headers=bearer(token))
    assert resp.status_code == 201
    assert resp.json()["user_name"] == "Dave Fan"

    client.patch("/api/v1/me/display-name", json={"display_name": None},
                 headers=bearer(token))

    resp2 = client.post(f"/api/v1/meals/{meal_id}/ratings",
                        json={"rating": 4}, headers=bearer(token))
    assert resp2.json()["user_name"] == "dave"


def test_display_name_on_side_ratings(client, meal_id):
    token = register(client, "erin").json()["token"]

    client.patch("/api/v1/me/display-name", json={"display_name": "Erin Eats"},
                 headers=bearer(token))

    resp = client.post(f"/api/v1/meals/{meal_id}/side-ratings",
                       json={"side_name": "Reis", "rating": 3}, headers=bearer(token))
    assert resp.status_code == 201
    assert resp.json()["user_name"] == "Erin Eats"


def test_display_name_validation(client):
    register(client, "frank")
    login = client.post("/api/v1/auth/login", json={"username": "frank", "password": GOOD_PW})
    token = login.json()["token"]

    # Too long
    resp = client.patch("/api/v1/me/display-name",
                        json={"display_name": "a" * 31}, headers=bearer(token))
    assert resp.status_code == 400

    # Invalid characters
    resp = client.patch("/api/v1/me/display-name",
                        json={"display_name": "has@special"}, headers=bearer(token))
    assert resp.status_code == 400

    # Empty string treated as null
    resp = client.patch("/api/v1/me/display-name",
                        json={"display_name": ""}, headers=bearer(token))
    assert resp.status_code == 200
    assert resp.json()["display_name"] is None


def test_display_name_requires_auth(client):
    resp = client.patch("/api/v1/me/display-name", json={"display_name": "test"})
    assert resp.status_code == 401
