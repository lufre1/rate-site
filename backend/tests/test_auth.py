"""API tests for the accounts feature.

Covers the register/login/session round-trip, that anonymous rating still works
untouched, and that one user cannot edit or delete another user's rating.

Runs against a private SQLite database created fresh for each test by the
`sqlite_db` fixture in conftest.py -- never a shared or ambient database.
"""
from datetime import date as date_cls, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import auth
import main
from database import SessionLocal, Mensa, Meal, AuthToken, Rating, SideRating, CommentVote

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


# ------------------------------------------------- deleting a voted rating

def voter(vid):
    return {"X-Voter-Id": vid}


def test_owner_can_delete_a_rating_that_has_been_voted_on(client, meal_id):
    """Regression: this used to 500.

    comment_votes.rating_id and photo_votes.rating_id reference ratings.id with
    NO ACTION and Rating declares no relationship() to either table, so the
    bare DELETE raised a foreign-key violation that the catch-all handler
    turned into an opaque 500. Production had at least one review its author
    could not delete.
    """
    token = register(client, "voted-on").json()["token"]
    rating_id = client.post(f"/api/v1/meals/{meal_id}/ratings",
                            json={"rating": 5, "comment": "worth a vote"},
                            headers=bearer(token)).json()["id"]

    assert client.put(f"/api/v1/ratings/{rating_id}/vote", json={"direction": 1},
                      headers=voter("v_someone")).status_code == 200

    assert client.delete(f"/api/v1/ratings/{rating_id}", headers=bearer(token)).status_code == 204
    assert client.get(f"/api/v1/ratings/{rating_id}").status_code == 404


def test_deleting_a_rating_removes_its_photo_file(client, meal_id, tmp_path):
    token = register(client, "photo-owner").json()["token"]
    created = client.post(
        f"/api/v1/meals/{meal_id}/ratings-with-photo",
        data={"rating": "4", "comment": "with a picture"},
        files={"photo": ("meal.png", _tiny_png(), "image/png")},
        headers=bearer(token),
    )
    assert created.status_code == 201, created.text
    rating_id = created.json()["id"]
    photo_url = created.json()["photo_url"]
    assert photo_url

    stored = tmp_path / photo_url.rsplit("/", 1)[-1]
    assert stored.is_file()

    assert client.delete(f"/api/v1/ratings/{rating_id}", headers=bearer(token)).status_code == 204
    assert not stored.exists()


def test_upload_drops_the_original_filename_and_its_metadata(client, meal_id, tmp_path):
    """The stored name must not echo the uploader's file name, and EXIF must go."""
    token = register(client, "exif-owner").json()["token"]
    created = client.post(
        f"/api/v1/meals/{meal_id}/ratings-with-photo",
        data={"rating": "5"},
        files={"photo": ("holiday-with-gps.png", _tiny_png(with_exif=True), "image/png")},
        headers=bearer(token),
    )
    assert created.status_code == 201, created.text
    name = created.json()["photo_url"].rsplit("/", 1)[-1]
    assert "holiday" not in name and "gps" not in name
    assert (tmp_path / name).read_bytes().find(b"Exif") == -1


def _tiny_png(with_exif=False):
    """A 1x1 PNG, optionally carrying an eXIf chunk."""
    import struct
    import zlib

    def chunk(ctype, payload=b""):
        body = ctype + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    out = b"\x89PNG\r\n\x1a\n"
    out += chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    if with_exif:
        out += chunk(b"eXIf", b"Exif\x00\x00MM\x00*" + b"\x00" * 32)
    out += chunk(b"IDAT", zlib.compress(b"\x00\x00"))
    out += chunk(b"IEND")
    return out


# ------------------------------------------------------------ account erasure

def test_delete_account_anonymises_ratings_and_ends_every_session(client, meal_id):
    """DSGVO Art. 17: the account goes, the content stays as anonymous rows."""
    first = register(client, "leaving").json()["token"]
    # A second login, so we can prove *all* sessions die, not just the caller's.
    second = client.post("/api/v1/auth/login",
                         json={"username": "leaving", "password": GOOD_PW}).json()["token"]

    rating_id = client.post(f"/api/v1/meals/{meal_id}/ratings",
                            json={"rating": 5, "comment": "was signed in"},
                            headers=bearer(first)).json()["id"]
    before = client.get(f"/api/v1/meals/{meal_id}/ratings").json()
    assert [r["user_name"] for r in before] == ["leaving"]

    assert client.delete("/api/v1/me", headers=bearer(first)).status_code == 204

    # Both sessions are gone.
    assert client.get("/api/v1/me", headers=bearer(first)).status_code == 401
    assert client.get("/api/v1/me", headers=bearer(second)).status_code == 401

    # The rating survives, detached from the account and renamed.
    after = client.get(f"/api/v1/meals/{meal_id}/ratings").json()
    assert len(after) == 1
    assert after[0]["id"] == rating_id
    assert after[0]["rating"] == 5
    assert after[0]["comment"] == "was signed in"
    assert after[0]["user_name"] != "leaving"

    # And it is genuinely anonymous now, so the authenticated routes disown it.
    fresh = register(client, "somebody-else").json()["token"]
    assert client.delete(f"/api/v1/ratings/{rating_id}", headers=bearer(fresh)).status_code == 403


def test_delete_account_frees_the_username(client):
    token = register(client, "recycled").json()["token"]
    assert client.delete("/api/v1/me", headers=bearer(token)).status_code == 204
    assert register(client, "recycled").status_code == 201


def test_delete_account_keeps_votes_but_drops_the_account_link(client, meal_id):
    """Votes are counted per voter_id; deleting them would reshuffle which
    photo represents a dish, so only the user_id link is cleared."""
    author = register(client, "author").json()["token"]
    rating_id = client.post(f"/api/v1/meals/{meal_id}/ratings",
                            json={"rating": 3, "comment": "vote on me"},
                            headers=bearer(author)).json()["id"]

    voter_token = register(client, "the-voter").json()["token"]
    assert client.put(f"/api/v1/ratings/{rating_id}/vote", json={"direction": 1},
                      headers={**bearer(voter_token), **voter("v_kept")}).status_code == 200

    assert client.delete("/api/v1/me", headers=bearer(voter_token)).status_code == 204

    # The score is unchanged, and the vote is still attributed to the voter id.
    status = client.get(f"/api/v1/ratings/{rating_id}/vote", headers=voter("v_kept"))
    assert status.status_code == 200
    assert status.json()["score"] == 1


def test_delete_account_requires_authentication(client):
    assert client.delete("/api/v1/me").status_code == 401


# ------------------------------------------------------------- token at rest

def _only_token_row():
    db = SessionLocal()
    try:
        rows = db.query(AuthToken).all()
        assert len(rows) == 1, f"expected exactly one session, got {len(rows)}"
        return rows[0].token, rows[0].expires_at
    finally:
        db.close()


def test_token_is_not_stored_in_plaintext(client):
    """A pg_dump must not be a set of usable credentials (issue #10)."""
    token = register(client, "hashed").json()["token"]

    stored, _ = _only_token_row()
    assert stored != token
    assert stored == auth._digest(token)
    # A SHA-256 digest, not the 43-char token_urlsafe value it replaced.
    assert len(stored) == 64
    assert all(c in "0123456789abcdef" for c in stored)


def test_issued_token_carries_an_expiry(client):
    register(client, "expiring")
    _, expires_at = _only_token_row()
    assert expires_at is not None
    # Within a minute of a full TTL out; the test cannot pin the exact instant.
    assert abs((expires_at - (datetime.utcnow() + auth.TOKEN_TTL))) < timedelta(minutes=1)


def test_logout_deletes_the_hashed_row(client):
    """logout has to digest before querying, or it deletes nothing."""
    token = register(client, "leaver").json()["token"]
    assert client.post("/api/v1/auth/logout", headers=bearer(token)).status_code == 204

    db = SessionLocal()
    try:
        assert db.query(AuthToken).count() == 0
    finally:
        db.close()


# ----------------------------------------------------------------- expiry

def _set_expiry(when):
    db = SessionLocal()
    try:
        row = db.query(AuthToken).one()
        row.expires_at = when
        db.add(row)
        db.commit()
    finally:
        db.close()


def test_expired_token_is_rejected(client):
    token = register(client, "stale").json()["token"]
    assert client.get("/api/v1/me", headers=bearer(token)).status_code == 200

    _set_expiry(datetime.utcnow() - timedelta(seconds=1))
    assert client.get("/api/v1/me", headers=bearer(token)).status_code == 401


def test_token_with_no_expiry_is_rejected(client):
    """Fail closed: a NULL expires_at means something wrote a row outside
    issue_token, not that the session lives forever."""
    token = register(client, "nullexpiry").json()["token"]
    _set_expiry(None)
    assert client.get("/api/v1/me", headers=bearer(token)).status_code == 401


def test_expiry_slides_when_the_session_is_used(client):
    token = register(client, "active").json()["token"]

    # Two days in, so the refresh guard (one day) lets a write through.
    _set_expiry(datetime.utcnow() + auth.TOKEN_TTL - timedelta(days=2))
    assert client.get("/api/v1/me", headers=bearer(token)).status_code == 200

    _, refreshed = _only_token_row()
    assert refreshed - datetime.utcnow() > auth.TOKEN_TTL - timedelta(minutes=1)


def test_expiry_is_not_rewritten_on_every_request(client):
    """_lookup is on every authenticated path, so the refresh must be guarded
    to one write per token per day rather than a write per read."""
    token = register(client, "chatty").json()["token"]
    _, first = _only_token_row()

    for _ in range(3):
        assert client.get("/api/v1/me", headers=bearer(token)).status_code == 200

    _, after = _only_token_row()
    assert after == first


# ----------------------------------------------------------------- purge job

def test_purge_removes_only_lapsed_sessions(client):
    live = register(client, "liveone").json()["token"]
    doomed = register(client, "doomed").json()["token"]

    db = SessionLocal()
    try:
        row = db.query(AuthToken).filter(
            AuthToken.token == auth._digest(doomed)
        ).one()
        row.expires_at = datetime.utcnow() - timedelta(days=1)
        db.add(row)
        db.commit()

        assert auth.purge_expired_tokens(db) == 1
        assert [r.token for r in db.query(AuthToken).all()] == [auth._digest(live)]
    finally:
        db.close()

    assert client.get("/api/v1/me", headers=bearer(live)).status_code == 200


def test_auto_upvote_on_comment_creation(client, meal_id):
    """#23 auto-upvote on comment creation, toggle vote, stars-only no vote."""
    voter_id = "v_test_auto_upvote"

    # Create a rating with comment + X-Voter-Id header
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings",
        json={"rating": 4, "comment": "first comment"},
        headers=voter(voter_id)
    )
    assert resp.status_code == 201
    rating_id = resp.json()["id"]

    # Assert exactly one CommentVote row created with direction=1
    db = SessionLocal()
    try:
        votes = db.query(CommentVote).filter(
            CommentVote.rating_id == rating_id
        ).all()
        assert len(votes) == 1
        assert votes[0].direction == 1
        assert votes[0].voter_id == voter_id
        # user_id should be None for anonymous
        assert votes[0].user_id is None
    finally:
        db.close()

    # Author toggles vote with same voter_id → score returns to 0
    # Sending the same direction again removes the vote (toggle off)
    resp = client.put(
        f"/api/v1/ratings/{rating_id}/vote",
        json={"direction": 1},
        headers=voter(voter_id)
    )
    assert resp.status_code == 200

    db = SessionLocal()
    try:
        votes = db.query(CommentVote).filter(
            CommentVote.rating_id == rating_id
        ).all()
        assert len(votes) == 0  # Vote removed, no rows
    finally:
        db.close()

    # Create a stars-only rating → no CommentVote
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings",
        json={"rating": 5},  # No comment
        headers=voter(voter_id + "_2")
    )
    assert resp.status_code == 201
    rating_id2 = resp.json()["id"]

    db = SessionLocal()
    try:
        votes = db.query(CommentVote).filter(
            CommentVote.rating_id == rating_id2
        ).all()
        assert len(votes) == 0  # No vote for stars-only rating
    finally:
        db.close()


def test_rename_updates_existing_ratings(client, meal_id):
    """#25 rename updates existing ratings and side_ratings."""
    token = register(client, "renamer").json()["token"]

    # Post ratings and side_ratings
    client.patch(
        "/api/v1/me/display-name",
        json={"display_name": "Old Name"},
        headers=bearer(token)
    )

    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings",
        json={"rating": 5, "comment": "rated"},
        headers=bearer(token)
    )
    assert resp.status_code == 201
    rating_id = resp.json()["id"]

    resp = client.post(
        f"/api/v1/meals/{meal_id}/side-ratings",
        json={"side_name": "Reis", "rating": 4},
        headers=bearer(token)
    )
    assert resp.status_code == 201
    side_rating_id = resp.json()["id"]

    # PATCH display name
    resp = client.patch(
        "/api/v1/me/display-name",
        json={"display_name": "New Name"},
        headers=bearer(token)
    )
    assert resp.status_code == 200

    # Assert all user's ratings and side_ratings now show "New Name"
    db = SessionLocal()
    try:
        rating = db.query(Rating).filter(Rating.id == rating_id).one()
        assert rating.user_name == "New Name"

        side = db.query(SideRating).filter(SideRating.id == side_rating_id).one()
        assert side.user_name == "New Name"
    finally:
        db.close()

    # Clear display name → all show username
    client.patch(
        "/api/v1/me/display-name",
        json={"display_name": None},
        headers=bearer(token)
    )

    db = SessionLocal()
    try:
        rating = db.query(Rating).filter(Rating.id == rating_id).one()
        assert rating.user_name == "renamer"

        side = db.query(SideRating).filter(SideRating.id == side_rating_id).one()
        assert side.user_name == "renamer"
    finally:
        db.close()

    # Another user's rows unchanged
    other_token = register(client, "other").json()["token"]
    client.patch(
        "/api/v1/me/display-name",
        json={"display_name": "Other Name"},
        headers=bearer(other_token)
    )

    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings",
        json={"rating": 3, "comment": "other rated"},
        headers=bearer(other_token)
    )
    assert resp.status_code == 201
    other_rating_id = resp.json()["id"]

    db = SessionLocal()
    try:
        other_rating = db.query(Rating).filter(Rating.id == other_rating_id).one()
        assert other_rating.user_name == "Other Name"
    finally:
        db.close()


def test_login_returns_display_name(client):
    """#24 login returns display_name, register returns null."""
    # Set a display name via PATCH /me/display-name
    register_resp = register(client, "displayuser")
    token = register_resp.json()["token"]
    client.patch(
        "/api/v1/me/display-name",
        json={"display_name": "Display User"},
        headers=bearer(token)
    )

    # Log out, logs in fresh
    login = client.post("/api/v1/auth/login", json={"username": "displayuser", "password": GOOD_PW})
    assert login.status_code == 200

    # Assert login response carries display_name
    assert login.json()["display_name"] == "Display User"

    # Register response carries display_name=null
    register_resp = client.post("/api/v1/auth/register", json={"username": "newuser", "password": GOOD_PW})
    assert register_resp.status_code == 201
    assert register_resp.json()["display_name"] is None
