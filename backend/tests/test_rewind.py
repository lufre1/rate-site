"""API tests for the rewind endpoint.

Covers weekly and monthly rewinds for community and personal scopes,
including photo/comment voting, language resolution, and cold-start handling.

Runs against a private SQLite database created fresh for each test by the
`sqlite_db` fixture in conftest.py -- never a shared or ambient database.
"""
from datetime import date as date_cls, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import auth
import main
from database import SessionLocal, Mensa, Meal, User, Rating, CommentVote, PhotoVote
from zoneinfo import ZoneInfo

GOOD_PW = "correct-horse-battery"


@pytest.fixture()
def client(monkeypatch, tmp_path, sqlite_db):
    """TestClient on a throwaway schema."""
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


# --------------------------------------------------------------- helpers

def compute_window_start(period: str, now: datetime):
    """Compute the window start in naive UTC, matching the endpoint logic."""
    now_b = now.replace(tzinfo=None)  # naive
    # Convert to Berlin time
    from zoneinfo import ZoneInfo
    now_berlin = now.replace(tzinfo=ZoneInfo("Europe/Berlin"))
    if period == "week":
        start_b = (now_berlin - timedelta(days=now_berlin.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        start_b = now_berlin.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_b.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    return start_utc


def create_mensa(db, name="Zentralmensa"):
    mensa = Mensa(name=name)
    db.add(mensa)
    db.commit()
    db.refresh(mensa)
    return mensa


def create_meal(db, mensa_id, name="Testgericht", name_de="Testgericht", name_en="Test dish",
                date=None, **kwargs):
    if date is None:
        date = date_cls.today()
    meal = Meal(
        name=name, name_de=name_de, name_en=name_en, type="main",
        date=date, mensa_id=mensa_id, description="Reis, Salat", **kwargs
    )
    db.add(meal)
    db.commit()
    db.refresh(meal)
    return meal


def create_rating(db, meal_id, rating, comment=None, photo_url=None,
                  user_id=None, user_name=None, created_at=None):
    if created_at is None:
        created_at = datetime.utcnow()
    rating_obj = Rating(
        meal_id=meal_id,
        rating=rating,
        comment=comment,
        photo_url=photo_url,
        user_id=user_id,
        user_name=user_name,
        created_at=created_at,
    )
    db.add(rating_obj)
    db.commit()
    db.refresh(rating_obj)
    return rating_obj


def create_comment_vote(db, rating_id, voter_id, direction=1):
    vote = CommentVote(rating_id=rating_id, voter_id=voter_id, direction=direction)
    db.add(vote)
    db.commit()
    return vote


def create_photo_vote(db, rating_id, voter_id, direction=1):
    vote = PhotoVote(rating_id=rating_id, voter_id=voter_id, direction=direction)
    db.add(vote)
    db.commit()
    return vote


# --------------------------------------------------------------- tests

def test_community_weekly_min_3_gate(client):
    """A dish with 3 in-window ratings appears; a dish with only 2 does not."""
    now = datetime.utcnow()
    window_start = compute_window_start("week", now)

    db = SessionLocal()
    try:
        mensa = create_mensa(db, "Zentralmensa")
        # Dish A: 3 ratings (should appear)
        meal_a = create_meal(db, mensa.id, name="Dish A", name_de="Gericht A")
        create_rating(db, meal_a.id, 5, created_at=window_start + timedelta(hours=1))
        create_rating(db, meal_a.id, 4, created_at=window_start + timedelta(hours=2))
        create_rating(db, meal_a.id, 3, created_at=window_start + timedelta(hours=3))
        # Dish B: only 2 ratings (should NOT appear)
        meal_b = create_meal(db, mensa.id, name="Dish B", name_de="Gericht B")
        create_rating(db, meal_b.id, 5, created_at=window_start + timedelta(hours=1))
        create_rating(db, meal_b.id, 4, created_at=window_start + timedelta(hours=2))
        # Dish C: 4 ratings (should appear)
        meal_c = create_meal(db, mensa.id, name="Dish C", name_de="Gericht C")
        create_rating(db, meal_c.id, 5, created_at=window_start + timedelta(hours=1))
        create_rating(db, meal_c.id, 5, created_at=window_start + timedelta(hours=2))
        create_rating(db, meal_c.id, 5, created_at=window_start + timedelta(hours=3))
        create_rating(db, meal_c.id, 5, created_at=window_start + timedelta(hours=4))
    finally:
        db.close()

    resp = client.get("/api/v1/rewind?period=week&scope=community&lang=de")
    assert resp.status_code == 200
    data = resp.json()
    assert data["period"] == "week"
    assert data["scope"] == "community"
    assert data["enough"] is True
    assert data["total_ratings"] == 9  # 3 + 4 from dishes that pass the gate (all in-window)
    assert data["dishes_rated"] == 3

    dish_names = [d["name"] for d in data["dishes"]]
    # Dish B should NOT be in the list (only 2 ratings)
    assert "Gericht A" in dish_names
    assert "Gericht C" in dish_names
    assert "Gericht B" not in dish_names


def test_community_ranking_uses_weighted_mean(client):
    """A broadly-liked dish outranks a small-sample enthusiastic one (issue #28).

    A raw mean would put the 3x5-star dish first; the shrunken mean pulls it
    toward the neutral prior so the 8-rating dish wins.
    """
    now = datetime.utcnow()
    window_start = compute_window_start("week", now)

    db = SessionLocal()
    try:
        mensa = create_mensa(db, "Zentralmensa")
        # Enthusiast: 3 ratings, all 5 stars (raw mean 5.0)
        meal_e = create_meal(db, mensa.id, name="Enthusiast", name_de="Enthusiast")
        for h in range(1, 4):
            create_rating(db, meal_e.id, 5, created_at=window_start + timedelta(hours=h))
        # Beloved: 8 ratings, six 5s and two 4s (raw mean 4.75)
        meal_b = create_meal(db, mensa.id, name="Beloved", name_de="Beloved")
        for h, star in enumerate([5, 5, 5, 5, 5, 5, 4, 4], start=1):
            create_rating(db, meal_b.id, star, created_at=window_start + timedelta(hours=h))
    finally:
        db.close()

    resp = client.get("/api/v1/rewind?period=week&scope=community&lang=de")
    assert resp.status_code == 200
    data = resp.json()
    names = [d["name"] for d in data["dishes"]]
    # Beloved (8 ratings) must outrank Enthusiast (3 ratings) despite the lower raw mean.
    assert names[0] == "Beloved"
    assert names.index("Beloved") < names.index("Enthusiast")


def test_window_filtering_excludes_last_week(client):
    """A rating from last week is excluded from the weekly rewind."""
    now = datetime.utcnow()
    window_start = compute_window_start("week", now)
    last_week = window_start - timedelta(days=7)

    db = SessionLocal()
    try:
        mensa = create_mensa(db, "Zentralmensa")
        meal = create_meal(db, mensa.id, name="Testgericht", name_de="Gericht")
        # Rating from last week (should be excluded)
        create_rating(db, meal.id, 5, created_at=last_week + timedelta(hours=1))
        # Rating from this week (should be included)
        create_rating(db, meal.id, 4, created_at=window_start + timedelta(hours=1))
    finally:
        db.close()

    resp = client.get("/api/v1/rewind?period=week&scope=community&lang=de")
    assert resp.status_code == 200
    data = resp.json()
    # Only 1 rating in window
    assert data["total_ratings"] == 1
    assert data["enough"] is False  # < 3 ratings


def test_best_photo_by_photo_vote_tie_oldest(client):
    """Best photo by photo-vote score desc, ties to oldest."""
    now = datetime.utcnow()
    window_start = compute_window_start("week", now)

    db = SessionLocal()
    try:
        mensa = create_mensa(db, "Zentralmensa")
        meal = create_meal(db, mensa.id, name="Testgericht", name_de="Gericht")

        # First photo (older)
        rating1 = create_rating(db, meal.id, 5, photo_url="photo1.jpg",
                                created_at=window_start + timedelta(hours=1))
        # Second photo (newer)
        rating2 = create_rating(db, meal.id, 5, photo_url="photo2.jpg",
                                created_at=window_start + timedelta(hours=2))
        # Third rating without photo to pass min-3 gate
        create_rating(db, meal.id, 4, created_at=window_start + timedelta(hours=3))

        # Give rating2 more photo votes
        create_photo_vote(db, rating2.id, "voter1", 1)
        create_photo_vote(db, rating2.id, "voter2", 1)
        create_photo_vote(db, rating2.id, "voter3", 1)
        # rating1 has fewer votes
        create_photo_vote(db, rating1.id, "voter4", 1)

        resp = client.get("/api/v1/rewind?period=week&scope=community&lang=de")
        assert resp.status_code == 200
        data = resp.json()
        # photo2 should win (more votes)
        dish = next(d for d in data["dishes"] if d["name"] == "Gericht")
        assert dish["photo_url"] == "photo2.jpg"

        # Now test tie-breaker: same votes, older wins
        db2 = SessionLocal()
        try:
            mensa2 = create_mensa(db2, "Ostmensa")
            meal2 = create_meal(db2, mensa2.id, name="Tiegericht", name_de="Tiegericht")

            # First photo (older)
            rating3 = create_rating(db2, meal2.id, 5, photo_url="tie1.jpg",
                                    created_at=window_start + timedelta(hours=1))
            # Second photo (newer)
            rating4 = create_rating(db2, meal2.id, 5, photo_url="tie2.jpg",
                                    created_at=window_start + timedelta(hours=2))
            # Third rating without photo to pass min-3 gate
            create_rating(db2, meal2.id, 4, created_at=window_start + timedelta(hours=3))

            # Same number of votes
            create_photo_vote(db2, rating3.id, "voter1", 1)
            create_photo_vote(db2, rating4.id, "voter2", 1)

        finally:
            db2.close()

        resp2 = client.get("/api/v1/rewind?period=week&scope=community&lang=de")
        assert resp2.status_code == 200
        data2 = resp2.json()
        # tie1 should win (older, same votes)
        dish2 = next(d for d in data2["dishes"] if d["name"] == "Tiegericht")
        assert dish2["photo_url"] == "tie1.jpg"

    finally:
        db.close()


def test_top_comments_by_comment_vote(client):
    """Top comments by comment-vote score desc, ties to older."""
    now = datetime.utcnow()
    window_start = compute_window_start("week", now)

    db = SessionLocal()
    try:
        mensa = create_mensa(db, "Zentralmensa")
        meal = create_meal(db, mensa.id, name="Testgericht", name_de="Gericht")

        # First comment (older, fewer votes)
        rating1 = create_rating(db, meal.id, 5, comment="First comment",
                                created_at=window_start + timedelta(hours=1))
        # Second comment (newer, more votes)
        rating2 = create_rating(db, meal.id, 5, comment="Second comment",
                                created_at=window_start + timedelta(hours=2))
        # Third rating without comment to pass min-3 gate
        create_rating(db, meal.id, 4, created_at=window_start + timedelta(hours=3))

        # Give rating2 more comment votes
        create_comment_vote(db, rating2.id, "voter1", 1)
        create_comment_vote(db, rating2.id, "voter2", 1)
        create_comment_vote(db, rating2.id, "voter3", 1)
        # rating1 has fewer votes
        create_comment_vote(db, rating1.id, "voter4", 1)

        resp = client.get("/api/v1/rewind?period=week&scope=community&lang=de")
        assert resp.status_code == 200
        data = resp.json()
        dish = next(d for d in data["dishes"] if d["name"] == "Gericht")
        comments = dish["comments"]
        # Second comment should be first (more votes)
        assert len(comments) == 2
        assert comments[0]["text"] == "Second comment"
        assert comments[1]["text"] == "First comment"

    finally:
        db.close()


def test_personal_scope_returns_only_user_ratings(client):
    """scope=me with a token returns only that user's dishes."""
    now = datetime.utcnow()
    window_start = compute_window_start("week", now)

    db = SessionLocal()
    try:
        mensa = create_mensa(db, "Zentralmensa")
        meal = create_meal(db, mensa.id, name="Testgericht", name_de="Gericht")

        # User 1
        user1 = User(
            username="alice",
            password_hash=auth.hash_password(GOOD_PW)
        )
        db.add(user1)
        db.commit()
        db.refresh(user1)

        # User 2
        user2 = User(
            username="bob",
            password_hash=auth.hash_password(GOOD_PW)
        )
        db.add(user2)
        db.commit()
        db.refresh(user2)

        # User 1 rates the dish
        create_rating(db, meal.id, 5, user_id=user1.id, user_name="alice",
                      created_at=window_start + timedelta(hours=1))
        # User 2 rates the dish
        create_rating(db, meal.id, 3, user_id=user2.id, user_name="bob",
                      created_at=window_start + timedelta(hours=2))

    finally:
        db.close()

    # Login as alice
    login = client.post("/api/v1/auth/login", json={"username": "alice", "password": GOOD_PW})
    token = login.json()["token"]

    # Community scope: both ratings
    resp = client.get("/api/v1/rewind?period=week&scope=community&lang=de")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_ratings"] == 2

    # Personal scope: only alice's rating
    resp_me = client.get("/api/v1/rewind?period=week&scope=me&lang=de",
                         headers=bearer(token))
    assert resp_me.status_code == 200
    data_me = resp_me.json()
    assert data_me["dishes_rated"] == 1
    assert data_me["dishes"][0]["name"] == "Gericht"
    assert data_me["dishes"][0]["rating"] == 5


def test_personal_scope_without_token_returns_401(client):
    """scope=me without token → 401."""
    resp = client.get("/api/v1/rewind?period=week&scope=me&lang=de")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


def test_lang_en_returns_english_name(client):
    """A dish with name_en set returns the English name."""
    now = datetime.utcnow()
    window_start = compute_window_start("week", now)

    db = SessionLocal()
    try:
        mensa = create_mensa(db, "Zentralmensa")
        meal = create_meal(db, mensa.id, name="Testgericht", name_de="Gericht",
                           name_en="Test dish")

        create_rating(db, meal.id, 5, created_at=window_start + timedelta(hours=1))
        create_rating(db, meal.id, 4, created_at=window_start + timedelta(hours=2))
        create_rating(db, meal.id, 3, created_at=window_start + timedelta(hours=3))

    finally:
        db.close()

    # German
    resp = client.get("/api/v1/rewind?period=week&scope=community&lang=de")
    assert resp.status_code == 200
    data = resp.json()
    assert data["dishes"][0]["name"] == "Gericht"

    # English
    resp_en = client.get("/api/v1/rewind?period=week&scope=community&lang=en")
    assert resp_en.status_code == 200
    data_en = resp_en.json()
    assert data_en["dishes"][0]["name"] == "Test dish"


def test_enough_false_for_insufficient_ratings(client):
    """A window with < 3 community ratings returns enough: false."""
    now = datetime.utcnow()
    window_start = compute_window_start("week", now)

    db = SessionLocal()
    try:
        mensa = create_mensa(db, "Zentralmensa")
        meal = create_meal(db, mensa.id, name="Testgericht", name_de="Gericht")

        # Only 2 ratings
        create_rating(db, meal.id, 5, created_at=window_start + timedelta(hours=1))
        create_rating(db, meal.id, 4, created_at=window_start + timedelta(hours=2))

    finally:
        db.close()

    resp = client.get("/api/v1/rewind?period=week&scope=community&lang=de")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enough"] is False
    assert data["total_ratings"] == 2


def test_personal_scope_photos_and_dishes_rated(client):
    """Personal scope returns photos count and dishes_rated."""
    now = datetime.utcnow()
    window_start = compute_window_start("week", now)

    db = SessionLocal()
    try:
        mensa = create_mensa(db, "Zentralmensa")
        meal1 = create_meal(db, mensa.id, name="Testgericht1", name_de="Gericht1")
        meal2 = create_meal(db, mensa.id, name="Testgericht2", name_de="Gericht2")

        user = User(
            username="alice",
            password_hash=auth.hash_password(GOOD_PW)
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # User rates two dishes, one with photo
        create_rating(db, meal1.id, 5, user_id=user.id, user_name="alice",
                      photo_url="photo1.jpg",
                      created_at=window_start + timedelta(hours=1))
        create_rating(db, meal2.id, 4, user_id=user.id, user_name="alice",
                      created_at=window_start + timedelta(hours=2))

    finally:
        db.close()

    login = client.post("/api/v1/auth/login", json={"username": "alice", "password": GOOD_PW})
    token = login.json()["token"]

    resp = client.get("/api/v1/rewind?period=week&scope=me&lang=de",
                      headers=bearer(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["dishes_rated"] == 2
    assert data["photos"] == 1
    assert data["enough"] is True


def test_personal_scope_top_5_by_best_star(client):
    """Personal scope: top 5 by best_star desc, tie by most recent."""
    now = datetime.utcnow()
    window_start = compute_window_start("week", now)

    db = SessionLocal()
    try:
        mensa = create_mensa(db, "Zentralmensa")

        user = User(
            username="alice",
            password_hash=auth.hash_password(GOOD_PW)
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # Create 6 dishes
        for i in range(6):
            meal = create_meal(db, mensa.id, name=f"Gericht{i}", name_de=f"Gericht{i}")
            # Different ratings
            rating = 5 - (i % 3)  # 5, 4, 3, 5, 4, 3
            create_rating(db, meal.id, rating, user_id=user.id, user_name="alice",
                          created_at=window_start + timedelta(hours=i+1))

    finally:
        db.close()

    login = client.post("/api/v1/auth/login", json={"username": "alice", "password": GOOD_PW})
    token = login.json()["token"]

    resp = client.get("/api/v1/rewind?period=week&scope=me&lang=de",
                      headers=bearer(token))
    assert resp.status_code == 200
    data = resp.json()
    # Should only return top 5
    assert len(data["dishes"]) == 5
    # Should be sorted by rating desc
    ratings = [d["rating"] for d in data["dishes"]]
    assert ratings == sorted(ratings, reverse=True)


def test_personal_scope_comment_and_photo(client):
    """Personal scope returns user's most recent comment and photo."""
    now = datetime.utcnow()
    window_start = compute_window_start("week", now)

    db = SessionLocal()
    try:
        mensa = create_mensa(db, "Zentralmensa")
        meal = create_meal(db, mensa.id, name="Testgericht", name_de="Gericht")

        user = User(
            username="alice",
            password_hash=auth.hash_password(GOOD_PW)
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # First rating: comment only
        rating1 = create_rating(db, meal.id, 5, user_id=user.id, user_name="alice",
                                comment="First comment",
                                created_at=window_start + timedelta(hours=1))
        # Second rating: photo only
        rating2 = create_rating(db, meal.id, 4, user_id=user.id, user_name="alice",
                                photo_url="photo.jpg",
                                created_at=window_start + timedelta(hours=2))
        # Third rating: both
        rating3 = create_rating(db, meal.id, 3, user_id=user.id, user_name="alice",
                                comment="Latest comment",
                                photo_url="latest.jpg",
                                created_at=window_start + timedelta(hours=3))

    finally:
        db.close()

    login = client.post("/api/v1/auth/login", json={"username": "alice", "password": GOOD_PW})
    token = login.json()["token"]

    resp = client.get("/api/v1/rewind?period=week&scope=me&lang=de",
                      headers=bearer(token))
    assert resp.status_code == 200
    data = resp.json()
    # Most recent comment
    assert data["dishes"][0]["comment"] == "Latest comment"
    # Most recent photo
    assert data["dishes"][0]["photo_url"] == "latest.jpg"


def test_monthly_scope(client):
    """Monthly scope filters by month start."""
    now = datetime.utcnow()
    # Compute month start
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_start_berlin = month_start.replace(tzinfo=ZoneInfo("Europe/Berlin"))
    month_start_utc = month_start_berlin.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    last_month = month_start - timedelta(days=30)

    db = SessionLocal()
    try:
        mensa = create_mensa(db, "Zentralmensa")
        meal = create_meal(db, mensa.id, name="Testgericht", name_de="Gericht")

        # Rating from last month (should be excluded)
        create_rating(db, meal.id, 5, created_at=last_month + timedelta(hours=1))
        # Rating from this month (should be included)
        create_rating(db, meal.id, 4, created_at=month_start_utc + timedelta(hours=1))
        create_rating(db, meal.id, 3, created_at=month_start_utc + timedelta(hours=2))
        create_rating(db, meal.id, 2, created_at=month_start_utc + timedelta(hours=3))

    finally:
        db.close()

    resp = client.get("/api/v1/rewind?period=month&scope=community&lang=de")
    assert resp.status_code == 200
    data = resp.json()
    assert data["period"] == "month"
    assert data["total_ratings"] == 3
    assert data["enough"] is True


def test_personal_scope_without_ratings(client):
    """Personal scope with no ratings returns empty dishes."""
    now = datetime.utcnow()
    window_start = compute_window_start("week", now)

    db = SessionLocal()
    try:
        mensa = create_mensa(db, "Zentralmensa")
        meal = create_meal(db, mensa.id, name="Testgericht", name_de="Gericht")

        # Rating from last week (outside window)
        create_rating(db, meal.id, 5, created_at=window_start - timedelta(days=7))

        # Create user alice
        user = User(
            username="alice",
            password_hash=auth.hash_password(GOOD_PW)
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    finally:
        db.close()

    login = client.post("/api/v1/auth/login", json={"username": "alice", "password": GOOD_PW})
    token = login.json()["token"]

    resp = client.get("/api/v1/rewind?period=week&scope=me&lang=de",
                      headers=bearer(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["dishes_rated"] == 0
    assert data["photos"] == 0
    assert data["enough"] is False
    assert data["dishes"] == []


def test_response_shape_community(client):
    """Verify the response shape for community scope."""
    now = datetime.utcnow()
    window_start = compute_window_start("week", now)

    db = SessionLocal()
    try:
        mensa = create_mensa(db, "Zentralmensa")
        meal = create_meal(db, mensa.id, name="Testgericht", name_de="Gericht",
                           name_en="Test dish")

        create_rating(db, meal.id, 5, created_at=window_start + timedelta(hours=1))
        create_rating(db, meal.id, 4, created_at=window_start + timedelta(hours=2))
        create_rating(db, meal.id, 3, created_at=window_start + timedelta(hours=3))

    finally:
        db.close()

    resp = client.get("/api/v1/rewind?period=week&scope=community&lang=de")
    assert resp.status_code == 200
    data = resp.json()

    # Check top-level keys
    assert set(data.keys()) == {"period", "scope", "enough", "total_ratings",
                                "dishes_rated", "dishes"}
    assert data["period"] == "week"
    assert data["scope"] == "community"
    assert isinstance(data["enough"], bool)
    assert isinstance(data["total_ratings"], int)
    assert isinstance(data["dishes_rated"], int)

    # Check dish shape
    assert len(data["dishes"]) == 1
    dish = data["dishes"][0]
    assert set(dish.keys()) == {"name", "mensa", "avg_rating", "rating_count",
                                "photo_url", "comments"}
    assert isinstance(dish["name"], str)
    assert isinstance(dish["mensa"], str)
    assert isinstance(dish["avg_rating"], float)
    assert isinstance(dish["rating_count"], int)
    assert dish["photo_url"] is None  # No photo
    assert isinstance(dish["comments"], list)


def test_response_shape_me(client):
    """Verify the response shape for personal scope."""
    now = datetime.utcnow()
    window_start = compute_window_start("week", now)

    db = SessionLocal()
    try:
        mensa = create_mensa(db, "Zentralmensa")
        meal = create_meal(db, mensa.id, name="Testgericht", name_de="Gericht")

        user = User(
            username="alice",
            password_hash=auth.hash_password(GOOD_PW)
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        create_rating(db, meal.id, 5, user_id=user.id, user_name="alice",
                      comment="Great!", photo_url="photo.jpg",
                      created_at=window_start + timedelta(hours=1))

    finally:
        db.close()

    login = client.post("/api/v1/auth/login", json={"username": "alice", "password": GOOD_PW})
    token = login.json()["token"]

    resp = client.get("/api/v1/rewind?period=week&scope=me&lang=de",
                      headers=bearer(token))
    assert resp.status_code == 200
    data = resp.json()

    # Check top-level keys
    assert set(data.keys()) == {"period", "scope", "enough", "dishes_rated",
                                "photos", "dishes"}
    assert data["period"] == "week"
    assert data["scope"] == "me"
    assert isinstance(data["enough"], bool)
    assert isinstance(data["dishes_rated"], int)
    assert isinstance(data["photos"], int)

    # Check dish shape
    assert len(data["dishes"]) == 1
    dish = data["dishes"][0]
    assert set(dish.keys()) == {"name", "mensa", "rating", "comment", "photo_url"}
    assert isinstance(dish["name"], str)
    assert isinstance(dish["mensa"], str)
    assert isinstance(dish["rating"], int)
    assert dish["comment"] == "Great!"
    assert dish["photo_url"] == "photo.jpg"