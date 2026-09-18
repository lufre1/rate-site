"""API tests for public user profiles (issue #30).

Profiles are private by default. A user opts in via PATCH /me/profile; until
then their profile route 404s exactly like a nonexistent one (no username
oracle). A public profile lists only rows with a matching user_id -- anonymous
rows (user_id IS NULL) are never linked, because the generated names are not
identities.

Runs against a private SQLite database created fresh for each test by the
`sqlite_db` fixture in conftest.py -- never a shared or ambient database.
"""
import pytest
from fastapi.testclient import TestClient

import main
from database import SessionLocal, Mensa, Meal, Rating, User

GOOD_PW = "correct-horse-battery"


@pytest.fixture()
def client(monkeypatch, tmp_path, sqlite_db):
    """TestClient on a throwaway schema.

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

    main.app.dependency_overrides[main.get_db] = override_get_db
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


def register(client, username, password=GOOD_PW):
    return client.post("/api/v1/auth/register", json={"username": username, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def make_user(client, username, password=GOOD_PW):
    """Register a user and return (user_id, token)."""
    resp = register(client, username, password)
    assert resp.status_code == 201, resp.text
    token = resp.json()["token"]
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        return user.id, token
    finally:
        db.close()


def make_mensa(db, name="Zentralmensa"):
    mensa = Mensa(name=name)
    db.add(mensa)
    db.commit()
    db.refresh(mensa)
    return mensa.id


def make_meal(db, mensa_id, name, date, type_="main"):
    meal = Meal(name=name, name_de=name, type=type_, date=date, mensa_id=mensa_id, description="Reis")
    db.add(meal)
    db.commit()
    db.refresh(meal)
    return meal.id


def make_rating(db, user_id, meal_id, rating=5, comment=None):
    r = Rating(user_id=user_id, meal_id=meal_id, rating=rating, comment=comment)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r.id


def set_public(client, token, is_public):
    resp = client.patch("/api/v1/me/profile", json={"is_public": is_public}, headers=bearer(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


# --------------------------------------------------------------- default privacy

def test_new_account_is_private_by_default(client):
    """A freshly registered account is private: /me says so and the profile 404s."""
    _, token = make_user(client, "alice")

    me = client.get("/api/v1/me", headers=bearer(token))
    assert me.status_code == 200
    assert me.json()["is_public"] is False

    # Private profile is indistinguishable from a nonexistent one.
    assert client.get("/api/v1/users/alice").status_code == 404
    assert client.get("/api/v1/users/alice/ratings").status_code == 404


def test_private_and_nonexistent_return_identical_404(client):
    """A 403 would confirm the account exists; both must be the same 404 body."""
    make_user(client, "bob")
    private = client.get("/api/v1/users/bob")
    missing = client.get("/api/v1/users/does-not-exist")
    assert private.status_code == 404
    assert missing.status_code == 404
    assert private.json() == missing.json()


# --------------------------------------------------------------- opt in / out

def test_toggle_public_then_private(client):
    """Opting in exposes the profile; opting out removes it immediately."""
    _, token = make_user(client, "carol")

    data = set_public(client, token, True)
    assert data["is_public"] is True
    assert client.get("/api/v1/users/carol").status_code == 200

    # No cache layer: the very next request after going private 404s again.
    data = set_public(client, token, False)
    assert data["is_public"] is False
    assert client.get("/api/v1/users/carol").status_code == 404


def test_toggle_requires_boolean(client):
    _, token = make_user(client, "dave")
    assert client.patch("/api/v1/me/profile", json={"is_public": "yes"}, headers=bearer(token)).status_code == 400
    assert client.patch("/api/v1/me/profile", json={}, headers=bearer(token)).status_code == 400


def test_toggle_requires_auth(client):
    assert client.patch("/api/v1/me/profile", json={"is_public": True}).status_code == 401


# --------------------------------------------------------------- listing

def test_public_profile_lists_only_matching_user_id(client):
    """A public profile shows only that user's rows -- never another user's and
    never an anonymous rating, even when the anonymous name collides."""
    db = SessionLocal()
    try:
        mensa_id = make_mensa(db)
        meal = make_meal(db, mensa_id, "Curry", __import__("datetime").date.today())

        alice_id, alice_token = make_user(client, "alice")
        bob_id, _ = make_user(client, "bob")

        # Two of Alice's ratings, one of Bob's, one anonymous.
        make_rating(db, alice_id, meal, rating=5, comment="Alice one")
        make_rating(db, alice_id, meal, rating=4, comment="Alice two")
        make_rating(db, bob_id, meal, rating=5, comment="Bob")
        # Anonymous row that even shares Alice's display name must not appear.
        make_rating(db, None, meal, rating=5, comment="anon")
        db.query(Rating).filter(Rating.user_id == None).update({"user_name": "alice"}, synchronize_session=False)
        db.commit()
    finally:
        db.close()

    set_public(client, alice_token, True)

    resp = client.get("/api/v1/users/alice/ratings")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    assert {r["comment"] for r in rows} == {"Alice one", "Alice two"}

    # The profile summary counts only Alice's ratings.
    profile = client.get("/api/v1/users/alice").json()
    assert profile["rating_count"] == 2
    assert profile["username"] == "alice"


def test_public_profile_excludes_anonymous_even_with_same_name(client):
    """Matching on user_name would attach strangers' reviews; we match user_id."""
    db = SessionLocal()
    try:
        mensa_id = make_mensa(db)
        meal = make_meal(db, mensa_id, "Pasta", __import__("datetime").date.today())
        eve_id, eve_token = make_user(client, "eve")
        make_rating(db, eve_id, meal, rating=5, comment="mine")
        # An anonymous rating whose user_name happens to equal Eve's username.
        make_rating(db, None, meal, rating=5, comment="stranger")
        db.query(Rating).filter(Rating.user_id == None).update({"user_name": "eve"}, synchronize_session=False)
        db.commit()
    finally:
        db.close()

    set_public(client, eve_token, True)
    rows = client.get("/api/v1/users/eve/ratings").json()
    assert [r["comment"] for r in rows] == ["mine"]


# --------------------------------------------------------------- display name

def test_display_name_all_underscore_rejected(client):
    """A name of only underscores used to pass; it must now be rejected."""
    _, token = make_user(client, "frank")
    resp = client.patch("/api/v1/me/display-name", json={"display_name": "____"}, headers=bearer(token))
    assert resp.status_code == 400


def test_display_name_with_alnum_still_accepted(client):
    _, token = make_user(client, "gina")
    resp = client.patch("/api/v1/me/display-name", json={"display_name": "Gina_1"}, headers=bearer(token))
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Gina_1"
