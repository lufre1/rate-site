"""Photo votes are a separate tally from comment votes.

The dish photo used to be picked by whichever rating had the highest *comment*
vote score, so an upvote meant as "useful review" silently promoted whatever
picture happened to be attached to it, and a photo posted without any text was
neither displayed nor votable. These tests pin the split down:

- photo votes toggle exactly like comment votes, on their own table;
- a photo-only rating is returned by /ratings-breakdown and can be voted on;
- comment votes have no effect on /top-photo, photo votes do;
- ties (which is every photo until someone votes) go to the oldest photo.

Runs against a private SQLite database created fresh for each test by the
`sqlite_db` fixture in conftest.py -- never a shared or ambient database.
"""
import base64
from datetime import date as date_cls, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import main
from database import SessionLocal, Mensa, Meal, Rating

PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAAsTAAALEwEAmpwYAAAAAXNS"
    "R0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAkSURBVDhPY2RgYGBgAAEYAQABYDCqAAAAAElFTkSuQmCC"
)

VOTER = {"X-Voter-Id": "v_test_voter"}
OTHER_VOTER = {"X-Voter-Id": "v_other_voter"}


@pytest.fixture()
def client(monkeypatch, tmp_path, sqlite_db):
    """TestClient on a throwaway SQLite schema and upload dir.

    Not entered as a context manager, so the "on_startup" hook (init_db's
    Postgres-only DDL, the live scraper, the scheduler) never fires.
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
            description=None, description_de=None, description_en=None,
            tags=None, type="main", date=date_cls.today(), mensa_id=mensa.id,
        )
        db.add(meal)
        db.commit()
        db.refresh(meal)
        return meal.id
    finally:
        db.close()


def make_rating(meal_id, *, comment=None, photo_url=None, created_at=None, rating=4):
    """Insert a rating directly -- the upload route cannot backdate created_at."""
    db = SessionLocal()
    try:
        row = Rating(
            meal_id=meal_id, rating=rating, comment=comment,
            user_name="Tester", photo_url=photo_url,
            created_at=created_at or datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def top_photo(client, meal_id):
    resp = client.get(f"/api/v1/meals/{meal_id}/top-photo")
    assert resp.status_code == 200
    return resp.json()["photo_url"]


def comments(client, meal_id, headers=None):
    resp = client.get(f"/api/v1/meals/{meal_id}/ratings-breakdown", headers=headers or {})
    assert resp.status_code == 200
    return resp.json()["comments"]


# --------------------------------------------------------------------------
# Toggle semantics
# --------------------------------------------------------------------------

def test_photo_vote_toggles(client, meal_id):
    rid = make_rating(meal_id, comment="lecker", photo_url="/uploads/a.png")

    up = client.put(f"/api/v1/ratings/{rid}/photo-vote", json={"direction": 1}, headers=VOTER)
    assert up.status_code == 200
    assert up.json() == {"direction": 1, "score": 1}

    # Same direction again removes the vote.
    again = client.put(f"/api/v1/ratings/{rid}/photo-vote", json={"direction": 1}, headers=VOTER)
    assert again.json() == {"direction": None, "score": 0}

    # Opposite direction flips rather than stacking.
    client.put(f"/api/v1/ratings/{rid}/photo-vote", json={"direction": 1}, headers=VOTER)
    flipped = client.put(f"/api/v1/ratings/{rid}/photo-vote", json={"direction": -1}, headers=VOTER)
    assert flipped.json() == {"direction": -1, "score": -1}


def test_photo_vote_status_is_per_voter(client, meal_id):
    rid = make_rating(meal_id, comment="lecker", photo_url="/uploads/a.png")
    client.put(f"/api/v1/ratings/{rid}/photo-vote", json={"direction": 1}, headers=VOTER)
    client.put(f"/api/v1/ratings/{rid}/photo-vote", json={"direction": 1}, headers=OTHER_VOTER)

    mine = client.get(f"/api/v1/ratings/{rid}/photo-vote", headers=VOTER).json()
    assert mine == {"direction": 1, "score": 2}

    third = client.get(f"/api/v1/ratings/{rid}/photo-vote", headers={"X-Voter-Id": "v_third"}).json()
    assert third == {"direction": None, "score": 2}


def test_photo_vote_requires_voter_id_and_valid_direction(client, meal_id):
    rid = make_rating(meal_id, comment="lecker", photo_url="/uploads/a.png")
    assert client.put(f"/api/v1/ratings/{rid}/photo-vote", json={"direction": 1}).status_code == 400
    assert client.put(f"/api/v1/ratings/{rid}/photo-vote", json={"direction": 5},
                      headers=VOTER).status_code == 400


# --------------------------------------------------------------------------
# The two tallies are independent
# --------------------------------------------------------------------------

def test_photo_vote_rejects_rating_without_photo(client, meal_id):
    rid = make_rating(meal_id, comment="nur Text")
    resp = client.put(f"/api/v1/ratings/{rid}/photo-vote", json={"direction": 1}, headers=VOTER)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Rating has no photo"


def test_comment_vote_still_rejects_rating_without_comment(client, meal_id):
    rid = make_rating(meal_id, photo_url="/uploads/a.png")
    resp = client.put(f"/api/v1/ratings/{rid}/vote", json={"direction": 1}, headers=VOTER)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Rating has no comment"


def test_comment_votes_do_not_decide_the_dish_photo(client, meal_id):
    """The regression this whole change exists to prevent."""
    older = datetime.utcnow() - timedelta(days=2)
    first = make_rating(meal_id, comment="alt", photo_url="/uploads/old.png", created_at=older)
    second = make_rating(meal_id, comment="neu", photo_url="/uploads/new.png")

    # Oldest wins the all-zero tie.
    assert top_photo(client, meal_id) == "/uploads/old.png"

    # Comment upvotes on the newer review must not promote its picture.
    for voter in ("v_a", "v_b", "v_c"):
        client.put(f"/api/v1/ratings/{second}/vote", json={"direction": 1},
                   headers={"X-Voter-Id": voter})
    assert top_photo(client, meal_id) == "/uploads/old.png"

    # A single photo upvote does.
    client.put(f"/api/v1/ratings/{second}/photo-vote", json={"direction": 1}, headers=VOTER)
    assert top_photo(client, meal_id) == "/uploads/new.png"

    # And downvoting it back below zero hands the dish back to the older photo.
    client.put(f"/api/v1/ratings/{second}/photo-vote", json={"direction": -1}, headers=VOTER)
    client.put(f"/api/v1/ratings/{second}/photo-vote", json={"direction": -1}, headers=OTHER_VOTER)
    assert top_photo(client, meal_id) == "/uploads/old.png"
    assert first  # the older rating is the one that won


def test_scores_do_not_leak_between_the_two_tables(client, meal_id):
    rid = make_rating(meal_id, comment="lecker", photo_url="/uploads/a.png")
    client.put(f"/api/v1/ratings/{rid}/vote", json={"direction": 1}, headers=VOTER)

    entry = comments(client, meal_id, VOTER)[0]
    assert entry["score"] == 1
    assert entry["vote_direction"] == 1
    assert entry["photo_score"] == 0
    assert entry["photo_vote_direction"] is None


# --------------------------------------------------------------------------
# Photo-only entries
# --------------------------------------------------------------------------

def test_photo_only_rating_is_listed_and_votable(client, meal_id):
    rid = make_rating(meal_id, photo_url="/uploads/solo.png")

    listed = comments(client, meal_id)
    assert [c["id"] for c in listed] == [rid]
    assert listed[0]["comment"] is None
    assert listed[0]["photo_url"] == "/uploads/solo.png"

    resp = client.put(f"/api/v1/ratings/{rid}/photo-vote", json={"direction": 1}, headers=VOTER)
    assert resp.json() == {"direction": 1, "score": 1}

    assert comments(client, meal_id, VOTER)[0]["photo_vote_direction"] == 1


def test_ratings_without_comment_or_photo_stay_hidden(client, meal_id):
    make_rating(meal_id)
    assert comments(client, meal_id) == []


def test_breakdown_always_includes_the_current_top_photo(client, meal_id):
    """It falls outside the 15 most recent entries, but must stay votable."""
    old = datetime.utcnow() - timedelta(days=30)
    winner = make_rating(meal_id, comment="das gute Foto", photo_url="/uploads/win.png",
                         created_at=old)
    client.put(f"/api/v1/ratings/{winner}/photo-vote", json={"direction": 1}, headers=VOTER)

    for i in range(20):
        make_rating(meal_id, comment=f"neuer Kommentar {i}")

    listed = comments(client, meal_id)
    assert len(listed) == 16  # 15 recent + the pinned winner
    assert winner in [c["id"] for c in listed]
    assert top_photo(client, meal_id) == "/uploads/win.png"


# --------------------------------------------------------------------------
# End-to-end through the real upload route
# --------------------------------------------------------------------------

def test_uploaded_photo_can_be_voted_and_becomes_the_dish_photo(client, meal_id):
    png = base64.b64decode(PNG_BASE64)
    resp = client.post(
        f"/api/v1/meals/{meal_id}/ratings-with-photo",
        data={"rating": "5", "comment": "sieht gut aus"},
        files={"photo": ("dish.png", png, "image/png")},
    )
    assert resp.status_code == 201
    rid = resp.json()["id"]

    vote = client.put(f"/api/v1/ratings/{rid}/photo-vote", json={"direction": 1}, headers=VOTER)
    assert vote.json()["score"] == 1

    photo_url = top_photo(client, meal_id)
    assert photo_url and photo_url.startswith("/uploads/")
