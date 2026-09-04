"""Regression tests for how /uploads/{filename} is served.

main.py used to register `@app.get("/uploads/{filename}")` at import time and
then mount StaticFiles on the same prefix. Starlette matches routes in
registration order, so the hand-rolled route always won and the mount was
unreachable -- along with the conditional-request handling it provides.

These tests pin the behaviour that matters to the frontend (`App.js` loads
`${API}${photo_url}`) and the caching the mount adds.
"""
import os

import pytest
from fastapi.testclient import TestClient

import main

# 2x2 red pixel PNG, reused from test_photo_upload.py.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000020000000208060000007286c8"
    "7c0000001849444154789c6360606060f80f0400030001000000ffff0300065a"
    "02d20000000049454e44ae426082"
)


def _served_directory():
    """The directory the mount actually reads.

    StaticFiles captures UPLOAD_DIR at import time, so monkeypatching
    main.UPLOAD_DIR would not move it. Ask the mount instead.
    """
    mount = next(r for r in main.app.routes if getattr(r, "name", None) == "uploads")
    return mount.app.directory


@pytest.fixture()
def photo_on_disk():
    path = os.path.join(_served_directory(), "regression_pixel.png")
    with open(path, "wb") as fh:
        fh.write(PNG)
    try:
        yield "regression_pixel.png"
    finally:
        os.remove(path)


@pytest.fixture()
def client():
    return TestClient(main.app)


def test_photo_is_served_with_its_content_type(client, photo_on_disk):
    resp = client.get(f"/uploads/{photo_on_disk}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == PNG


def test_response_carries_cache_validators(client, photo_on_disk):
    """FileResponse already sent these, so this is a guard, not a regression."""
    headers = client.get(f"/uploads/{photo_on_disk}").headers
    assert "etag" in headers
    assert "last-modified" in headers


def test_matching_etag_gets_a_304(client, photo_on_disk):
    """The gap FileResponse left: it sent an ETag but ignored If-None-Match, so
    a revalidating browser got the whole file back with a 200 every time."""
    etag = client.get(f"/uploads/{photo_on_disk}").headers["etag"]
    resp = client.get(f"/uploads/{photo_on_disk}", headers={"If-None-Match": etag})
    assert resp.status_code == 304
    assert resp.content == b""


def test_missing_photo_is_404(client):
    assert client.get("/uploads/there-is-no-such-file.png").status_code == 404


def test_path_traversal_is_refused(client):
    """StaticFiles resolves against `directory` and rejects anything outside it."""
    for attempt in ("../database.py", "..%2Fdatabase.py", "%2e%2e%2fdatabase.py"):
        assert client.get(f"/uploads/{attempt}").status_code in (403, 404)
