"""Tests for GET /api/v1/announcement.

The route serves the current active announcement (newest id wins) in the
requested language, or 404 when there is none. The frontend shows it once per
browser; the "shown once" logic lives client-side, so these tests only pin the
server contract.
"""
import pytest
from fastapi.testclient import TestClient

import main
from database import SessionLocal, SiteAnnouncement


@pytest.fixture()
def client(monkeypatch, tmp_path, sqlite_db):
    """A TestClient wired to a throwaway SQLite schema (see test_api_ratings)."""
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


def _add_announcement(text_de, text_en, active=True):
    db = SessionLocal()
    try:
        ann = SiteAnnouncement(text_de=text_de, text_en=text_en, active=active)
        db.add(ann)
        db.commit()
        db.refresh(ann)
        return ann.id
    finally:
        db.close()


def test_no_announcement_is_404(client):
    resp = client.get("/api/v1/announcement")
    assert resp.status_code == 404


def test_returns_active_announcement_in_german_by_default(client):
    _add_announcement("Neues Feature!", "New feature!")
    resp = client.get("/api/v1/announcement")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == 1
    assert body["text"] == "Neues Feature!"


def test_returns_english_when_requested(client):
    _add_announcement("Neues Feature!", "New feature!")
    resp = client.get("/api/v1/announcement?lang=en")
    assert resp.status_code == 200
    assert resp.json()["text"] == "New feature!"


def test_inactive_announcement_is_ignored(client):
    _add_announcement("Alt", "Old", active=False)
    resp = client.get("/api/v1/announcement")
    assert resp.status_code == 404


def test_newest_active_wins(client):
    _add_announcement("Erste", "First")
    _add_announcement("Zweite", "Second")
    resp = client.get("/api/v1/announcement")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == 2
    assert body["text"] == "Zweite"


def test_inactive_older_does_not_shadow_newer_active(client):
    _add_announcement("Alt", "Old", active=False)
    _add_announcement("Neu", "New")
    resp = client.get("/api/v1/announcement")
    assert resp.status_code == 200
    assert resp.json()["id"] == 2
