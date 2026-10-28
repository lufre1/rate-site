"""Tests for the admin announcement write routes.

POST /api/v1/admin/announcement publishes a new banner (a fresh id, so it shows
again even to browsers that dismissed the old one) and retires the previously
active row. DELETE /api/v1/admin/announcement retires the current one. Both are
admin-only: anonymous is 401, a signed-in non-admin is 403.

Runs against a private SQLite database created fresh for each test by the
`sqlite_db` fixture in conftest.py.
"""
import pytest
from fastapi.testclient import TestClient

import main
from database import SessionLocal, User

GOOD_PW = "correct-horse-battery"


@pytest.fixture()
def client(monkeypatch, tmp_path, sqlite_db):
    """TestClient on a throwaway schema. Same shape as test_announcement.py."""
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


def make_admin(username):
    """Flip the is_admin flag directly in the DB (there is no self-serve route)."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        user.is_admin = True
        db.commit()
    finally:
        db.close()


def _publish(client, token, text_de="Neues Feature!", text_en="New feature!"):
    return client.post(
        "/api/v1/admin/announcement",
        json={"text_de": text_de, "text_en": text_en},
        headers=bearer(token),
    )


# ---------------------------------------------------------------- authz

def test_anonymous_cannot_publish(client):
    resp = client.post("/api/v1/admin/announcement", json={"text_de": "x", "text_en": "y"})
    assert resp.status_code == 401


def test_anonymous_cannot_retire(client):
    resp = client.delete("/api/v1/admin/announcement")
    assert resp.status_code == 401


def test_non_admin_cannot_publish(client):
    token = register(client, "plain").json()["token"]
    resp = _publish(client, token)
    assert resp.status_code == 403


def test_non_admin_cannot_retire(client):
    token = register(client, "plain2").json()["token"]
    resp = client.delete("/api/v1/admin/announcement", headers=bearer(token))
    assert resp.status_code == 403


# ---------------------------------------------------------------- publish

def test_admin_can_publish_and_it_is_served(client):
    token = register(client, "boss").json()["token"]
    make_admin("boss")
    resp = _publish(client, token)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["text_de"] == "Neues Feature!"
    assert body["text_en"] == "New feature!"

    served = client.get("/api/v1/announcement")
    assert served.status_code == 200
    assert served.json()["id"] == body["id"]
    assert served.json()["text"] == "Neues Feature!"

    served_en = client.get("/api/v1/announcement?lang=en")
    assert served_en.json()["text"] == "New feature!"


def test_publish_retires_the_previous_active(client):
    token = register(client, "boss2").json()["token"]
    make_admin("boss2")
    first = _publish(client, token, text_de="Erste", text_en="First").json()
    second = _publish(client, token, text_de="Zweite", text_en="Second").json()
    assert second["id"] != first["id"]
    served = client.get("/api/v1/announcement")
    assert served.json()["id"] == second["id"]
    assert served.json()["text"] == "Zweite"


def test_publish_rejects_empty_text(client):
    token = register(client, "boss3").json()["token"]
    make_admin("boss3")
    resp = _publish(client, token, text_de="   ", text_en="New feature!")
    assert resp.status_code == 400


def test_publish_rejects_overlong_text(client):
    token = register(client, "boss4").json()["token"]
    make_admin("boss4")
    resp = _publish(client, token, text_de="x" * 501, text_en="New feature!")
    assert resp.status_code == 400


# ---------------------------------------------------------------- retire

def test_admin_can_retire_the_active_announcement(client):
    token = register(client, "boss5").json()["token"]
    make_admin("boss5")
    _publish(client, token)
    assert client.get("/api/v1/announcement").status_code == 200

    resp = client.delete("/api/v1/admin/announcement", headers=bearer(token))
    assert resp.status_code == 204
    assert client.get("/api/v1/announcement").status_code == 404


def test_retire_with_none_active_is_404(client):
    token = register(client, "boss6").json()["token"]
    make_admin("boss6")
    resp = client.delete("/api/v1/admin/announcement", headers=bearer(token))
    assert resp.status_code == 404


# ---------------------------------------------------------------- /me carries is_admin

def test_me_reports_is_admin(client):
    token = register(client, "boss7").json()["token"]
    assert client.get("/api/v1/me", headers=bearer(token)).json()["is_admin"] is False
    make_admin("boss7")
    assert client.get("/api/v1/me", headers=bearer(token)).json()["is_admin"] is True
