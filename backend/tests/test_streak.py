"""API tests for the rating streak feature.

A streak = a run of CONSECUTIVE SERVICE DAYS on which the user rated.
A "service day" is any date the site has a menu.
Sundays/holidays/closures are NOT service days, so they never break a streak.
Only RATINGS count (not votes). Day boundaries are Europe/Berlin.

Runs against a private SQLite database created fresh for each test by the
`sqlite_db` fixture in conftest.py -- never a shared or ambient database.
"""
from datetime import date as date_cls, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import auth
import main
import database
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
    # Fetch user id from the DB
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
    meal = Meal(
        name=name,
        name_de=name,
        type=type_,
        date=date,
        mensa_id=mensa_id,
        description="Reis, Salat"
    )
    db.add(meal)
    db.commit()
    db.refresh(meal)
    return meal.id


def make_rating(db, user_id, meal_id, rating=5, created_at=None):
    """Create a rating with explicit created_at (naive UTC datetime)."""
    if created_at is None:
        created_at = datetime.utcnow()
    rating_obj = Rating(
        user_id=user_id,
        meal_id=meal_id,
        rating=rating,
        created_at=created_at
    )
    db.add(rating_obj)
    db.commit()
    db.refresh(rating_obj)
    return rating_obj.id


# --------------------------------------------------------------- basic streak tests

def test_basic_consecutive_streak(client):
    """Service days Mon/Tue/Wed (3 meals), user rated all 3 → current == 3."""
    db = SessionLocal()
    try:
        mensa_id = make_mensa(db, "Zentralmensa")
        today = date_cls.today()
        # Use recent dates so today is a service day
        mon = today - timedelta(days=today.weekday())  # Monday of this week
        tue = mon + timedelta(days=1)
        wed = mon + timedelta(days=2)

        make_meal(db, mensa_id, "Montag", mon)
        make_meal(db, mensa_id, "Dienstag", tue)
        make_meal(db, mensa_id, "Mittwoch", wed)

        user_id, token = make_user(client, "alice")
        # Rate all three days
        make_rating(db, user_id, 1, created_at=datetime(mon.year, mon.month, mon.day, 12, 0))
        make_rating(db, user_id, 2, created_at=datetime(tue.year, tue.month, tue.day, 12, 0))
        make_rating(db, user_id, 3, created_at=datetime(wed.year, wed.month, wed.day, 12, 0))
    finally:
        db.close()

    resp = client.get("/api/v1/me/streak", headers=bearer(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["current"] == 3
    assert data["best"] == 3
    assert data["active"] is True


def test_sunday_gap_does_not_break_streak(client):
    """Service days = Fri, Mon, Tue (skip Sat+Sun), user rated all 3 → current == 3."""
    db = SessionLocal()
    try:
        mensa_id = make_mensa(db, "Zentralmensa")
        today = date_cls.today()
        # Find a Friday and use that
        fri = today - timedelta(days=today.weekday() + 3)  # Last Friday
        mon = fri + timedelta(days=3)
        tue = mon + timedelta(days=1)

        make_meal(db, mensa_id, "Freitag", fri)
        make_meal(db, mensa_id, "Montag", mon)
        make_meal(db, mensa_id, "Dienstag", tue)

        user_id, token = make_user(client, "bob")
        make_rating(db, user_id, 1, created_at=datetime(fri.year, fri.month, fri.day, 12, 0))
        make_rating(db, user_id, 2, created_at=datetime(mon.year, mon.month, mon.day, 12, 0))
        make_rating(db, user_id, 3, created_at=datetime(tue.year, tue.month, tue.day, 12, 0))
    finally:
        db.close()

    resp = client.get("/api/v1/me/streak", headers=bearer(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["current"] == 3
    assert data["best"] == 3
    assert data["active"] is True


def test_at_risk_active_false(client):
    """Service days Mon..Fri, user rated Mon/Tue/Wed only → current == 3, active == False.

    We use dates in the past so that the latest service day (Fri) is not rated.
    Today must be after Fri so that Fri is included in service_days (d <= today).
    """
    db = SessionLocal()
    try:
        mensa_id = make_mensa(db, "Zentralmensa")
        # Use dates in the past so today > all service days
        # Pick a week where today is already passed (e.g., last week)
        today = date_cls.today()
        mon = today - timedelta(days=today.weekday() + 7)  # Last Monday
        tue = mon + timedelta(days=1)
        wed = mon + timedelta(days=2)
        thu = mon + timedelta(days=3)
        fri = mon + timedelta(days=4)

        make_meal(db, mensa_id, "Montag", mon)
        make_meal(db, mensa_id, "Dienstag", tue)
        make_meal(db, mensa_id, "Mittwoch", wed)
        make_meal(db, mensa_id, "Donnerstag", thu)
        make_meal(db, mensa_id, "Freitag", fri)

        user_id, token = make_user(client, "charlie")
        make_rating(db, user_id, 1, created_at=datetime(mon.year, mon.month, mon.day, 12, 0))
        make_rating(db, user_id, 2, created_at=datetime(tue.year, tue.month, tue.day, 12, 0))
        make_rating(db, user_id, 3, created_at=datetime(wed.year, wed.month, wed.day, 12, 0))
        # Did NOT rate Thu or Fri
    finally:
        db.close()

    resp = client.get("/api/v1/me/streak", headers=bearer(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["current"] == 3
    assert data["best"] == 3
    assert data["active"] is False


def test_best_exceeds_current(client):
    """User had a 5-consecutive-service-day run earlier, then a gap, then rated 2 recent → best == 5, current == 2.

    We need a gap in service days (a day with no meal) to break the streak.
    We'll use: Mon, Tue, Wed, Thu, Fri (week 1), then Mon, Tue (week 2),
    but add a "gap day" (e.g., a holiday) as a service day that wasn't rated.
    """
    db = SessionLocal()
    try:
        mensa_id = make_mensa(db, "Zentralmensa")
        today = date_cls.today()
        # Week 1: Mon-Fri
        mon1 = today - timedelta(days=today.weekday() + 7)
        tue1 = mon1 + timedelta(days=1)
        wed1 = mon1 + timedelta(days=2)
        thu1 = mon1 + timedelta(days=3)
        fri1 = mon1 + timedelta(days=4)
        # A gap day (e.g., a holiday) - this is a service day but user didn't rate
        gap = fri1 + timedelta(days=1)
        # Week 2: Mon-Tue
        mon2 = gap + timedelta(days=1)
        tue2 = mon2 + timedelta(days=1)

        make_meal(db, mensa_id, "W1-Mon", mon1)
        make_meal(db, mensa_id, "W1-Tue", tue1)
        make_meal(db, mensa_id, "W1-Wed", wed1)
        make_meal(db, mensa_id, "W1-Thu", thu1)
        make_meal(db, mensa_id, "W1-Fri", fri1)
        # Gap day - service day but user didn't rate
        make_meal(db, mensa_id, "Gap", gap)
        # Week 2
        make_meal(db, mensa_id, "W2-Mon", mon2)
        make_meal(db, mensa_id, "W2-Tue", tue2)

        user_id, token = make_user(client, "dave")
        # Week 1: rated all 5
        make_rating(db, user_id, 1, created_at=datetime(mon1.year, mon1.month, mon1.day, 12, 0))
        make_rating(db, user_id, 2, created_at=datetime(tue1.year, tue1.month, tue1.day, 12, 0))
        make_rating(db, user_id, 3, created_at=datetime(wed1.year, wed1.month, wed1.day, 12, 0))
        make_rating(db, user_id, 4, created_at=datetime(thu1.year, thu1.month, thu1.day, 12, 0))
        make_rating(db, user_id, 5, created_at=datetime(fri1.year, fri1.month, fri1.day, 12, 0))
        # Did NOT rate gap day
        # Week 2: rated only Mon, Tue
        make_rating(db, user_id, 7, created_at=datetime(mon2.year, mon2.month, mon2.day, 12, 0))
        make_rating(db, user_id, 8, created_at=datetime(tue2.year, tue2.month, tue2.day, 12, 0))
    finally:
        db.close()

    resp = client.get("/api/v1/me/streak", headers=bearer(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["best"] == 5
    assert data["current"] == 2
    assert data["active"] is True


def test_no_ratings(client):
    """User exists but rated nothing → {current: 0, best: 0, active: false}."""
    db = SessionLocal()
    try:
        mensa_id = make_mensa(db, "Zentralmensa")
        today = date_cls.today()
        make_meal(db, mensa_id, "Heute", today)

        user_id, token = make_user(client, "eve")
        # No ratings created
    finally:
        db.close()

    resp = client.get("/api/v1/me/streak", headers=bearer(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"current": 0, "best": 0, "active": False}


def test_anonymous_no_token_401(client):
    """GET /api/v1/me/streak with no Authorization header → 401."""
    resp = client.get("/api/v1/me/streak")
    assert resp.status_code == 401


# --------------------------------------------------------------- Berlin timezone tests

def test_berlin_conversion_sqlite_utc_bucketing(client):
    """On SQLite, created_at is naive UTC, so the date buckets on UTC.

    This test verifies the expected behavior on SQLite (no timezone conversion).
    """
    db = SessionLocal()
    try:
        mensa_id = make_mensa(db, "Zentralmensa")
        today = date_cls.today()
        make_meal(db, mensa_id, "Heute", today)

        user_id, token = make_user(client, "grace")

        # Create a rating with a specific UTC time
        # The date portion should be used as-is on SQLite
        utc_time = datetime(today.year, today.month, today.day, 12, 0)
        make_rating(db, user_id, 1, rating=5, created_at=utc_time)
    finally:
        db.close()

    resp = client.get("/api/v1/me/streak", headers=bearer(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["current"] == 1
    assert data["best"] == 1
    assert data["active"] is True


def test_local_date_compiles_with_timezone_on_postgres():
    """The _local_date function should emit timezone() on Postgres.

    This mirrors the test_local_dow test in test_api_stats.py.
    """
    from sqlalchemy import create_engine
    sql = str(main._local_date(create_engine("postgresql://")))
    assert "timezone(:timezone_1, timezone(:timezone_2, ratings.created_at))" in sql


def test_local_date_no_timezone_on_sqlite():
    """The _local_date function should NOT emit timezone() on SQLite."""
    from sqlalchemy import create_engine
    sql = str(main._local_date(create_engine("sqlite://")))
    assert "timezone" not in sql


def test_berlin_conversion_sqlite_utc_bucketing(client):
    """On SQLite, created_at is naive UTC, so the date buckets on UTC.

    This test verifies the expected behavior on SQLite (no timezone conversion).
    """
    db = SessionLocal()
    try:
        mensa_id = make_mensa(db, "Zentralmensa")
        today = date_cls.today()
        make_meal(db, mensa_id, "Heute", today)

        user_id, token = make_user(client, "grace")

        # Create a rating with a specific UTC time
        # The date portion should be used as-is on SQLite
        utc_time = datetime(today.year, today.month, today.day, 12, 0)
        make_rating(db, user_id, 1, rating=5, created_at=utc_time)
    finally:
        db.close()

    resp = client.get("/api/v1/me/streak", headers=bearer(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["current"] == 1
    assert data["best"] == 1
    assert data["active"] is True


# --------------------------------------------------------------- edge cases

def test_single_service_day_rated(client):
    """Only one service day exists and user rated it."""
    db = SessionLocal()
    try:
        mensa_id = make_mensa(db, "Zentralmensa")
        today = date_cls.today()
        make_meal(db, mensa_id, "Heute", today)

        user_id, token = make_user(client, "henry")
        make_rating(db, user_id, 1, rating=5)
    finally:
        db.close()

    resp = client.get("/api/v1/me/streak", headers=bearer(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"current": 1, "best": 1, "active": True}


def test_no_service_days_yet(client):
    """No meals in database yet → all zeros."""
    db = SessionLocal()
    try:
        # No mensa, no meals
        user_id, token = make_user(client, "iris")
    finally:
        db.close()

    resp = client.get("/api/v1/me/streak", headers=bearer(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"current": 0, "best": 0, "active": False}


def test_rated_non_service_day_ignored(client):
    """User rated a day with no menu → that day is ignored for streak."""
    db = SessionLocal()
    try:
        mensa_id = make_mensa(db, "Zentralmensa")
        today = date_cls.today()
        # Only one service day
        make_meal(db, mensa_id, "Heute", today)

        user_id, token = make_user(client, "jack")
        # Rating on a day with no menu (this creates a rating but it won't
        # count toward the streak because that date is not a service day)
        non_service = today - timedelta(days=1)
        make_rating(db, user_id, 1, rating=5, created_at=datetime(non_service.year, non_service.month, non_service.day, 12, 0))
    finally:
        db.close()

    resp = client.get("/api/v1/me/streak", headers=bearer(token))
    assert resp.status_code == 200
    data = resp.json()
    # The rating was on a non-service day, so it doesn't count
    assert data == {"current": 0, "best": 0, "active": False}