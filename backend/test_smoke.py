#!/usr/bin/env python3
"""End-to-end smoke test for the deployed (docker-compose) stack.

Unlike test_api_ratings.py (isolated SQLite, no server needed) and
test_photo_upload.py (needs a live DATABASE_URL to inspect the schema),
this script only talks HTTP to the real nginx-proxied app -- the same way a
browser does. Run it after `docker compose up -d --build` against the
default proxy URL:

    python backend/test_smoke.py

Or point it at any other deployment:

    API_BASE_URL=https://example.org python backend/test_smoke.py

Skips (exit 0) if the app isn't reachable, so it's safe to leave in CI
without a live deployment.
"""
import base64
import os
import sys

import requests

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost")

PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAAsTAAALEwEAmpwYAAAAAXNS"
    "R0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAkSURBVDhPY2RgYGBgAAEYAQABYDCqAAAAAElFTkSuQmCC"
)


def get_test_meal_id():
    """Pick any existing meal to rate/rate-with-photo against."""
    resp = requests.get(
        f"{API_BASE_URL}/api/v1/meals/search",
        params={"q": "a", "past": True, "lang": "de"},
        timeout=10,
    )
    if resp.status_code == 200 and resp.json():
        return resp.json()[0]["id"]
    return None


def run(name, fn, results):
    print("\n" + "=" * 60)
    print(name)
    print("=" * 60)
    try:
        ok = fn()
    except Exception as e:  # noqa: BLE001 - report and continue
        print(f"✗ FAIL: Exception: {e}")
        ok = False
    print(f"{'✓ PASS' if ok else '✗ FAIL'}: {name}")
    results.append((name, ok))
    return ok


def test_list_mensas_and_meals(meal_id):
    if meal_id is None:
        print("✗ FAIL: no meal available to test against")
        return False
    print(f"  Using meal id {meal_id}")
    return True


def test_create_rating_json(meal_id):
    resp = requests.post(
        f"{API_BASE_URL}/api/v1/meals/{meal_id}/ratings",
        json={"rating": 4, "comment": "smoke test review"},
        timeout=10,
    )
    if resp.status_code != 201:
        print(f"✗ unexpected status {resp.status_code}: {resp.text}")
        return False
    body = resp.json()
    if "meal_id" not in body:
        print(f"✗ response missing meal_id: {body}")
        return False
    print(f"  Created rating id={body['id']}")
    return True


def test_rating_range_validation(meal_id):
    resp = requests.post(
        f"{API_BASE_URL}/api/v1/meals/{meal_id}/ratings",
        json={"rating": 6},
        timeout=10,
    )
    if resp.status_code != 422:
        print(f"✗ expected 422 for out-of-range rating, got {resp.status_code}")
        return False
    return True


def test_get_ratings_has_meal_id_and_date(meal_id):
    resp = requests.get(f"{API_BASE_URL}/api/v1/meals/{meal_id}/ratings", timeout=10)
    if resp.status_code != 200:
        print(f"✗ unexpected status {resp.status_code}: {resp.text}")
        return False
    reviews = resp.json()
    if not reviews:
        print("✗ no reviews found (expected at least the one just created)")
        return False
    review = reviews[0]
    if "meal_id" not in review or not review.get("date"):
        print(f"✗ review missing meal_id/date: {review}")
        return False
    return True


def test_photo_upload_via_form_fields(meal_id):
    png_bytes = base64.b64decode(PNG_BASE64)
    resp = requests.post(
        f"{API_BASE_URL}/api/v1/meals/{meal_id}/ratings-with-photo",
        data={"rating": 5, "comment": "smoke test photo"},
        files={"photo": ("smoke.png", png_bytes, "image/png")},
        timeout=10,
    )
    if resp.status_code != 201:
        print(f"✗ unexpected status {resp.status_code}: {resp.text}")
        return False
    body = resp.json()
    if not body.get("photo_url"):
        print(f"✗ no photo_url in response: {body}")
        return False
    print(f"  photo_url={body['photo_url']}")
    return True


def test_photos_endpoint_has_date(meal_id):
    resp = requests.get(f"{API_BASE_URL}/api/v1/meals/{meal_id}/photos", timeout=10)
    if resp.status_code != 200:
        print(f"✗ unexpected status {resp.status_code}: {resp.text}")
        return False
    photos = resp.json()
    if not photos or not photos[-1].get("date"):
        print(f"✗ photos missing non-empty date: {photos}")
        return False
    return True


def test_frontend_served():
    resp = requests.get(f"{API_BASE_URL}/", timeout=10)
    if resp.status_code != 200 or "<div id=\"root\">" not in resp.text:
        print(f"✗ unexpected response serving frontend: {resp.status_code}")
        return False
    return True


def main():
    print("\n" + "=" * 60)
    print("END-TO-END SMOKE TEST")
    print("=" * 60)
    print(f"API Base URL: {API_BASE_URL}")

    try:
        requests.get(f"{API_BASE_URL}/api/v1/mensas", timeout=5)
    except Exception as e:
        print(f"SKIP: app not reachable at {API_BASE_URL}: {e}")
        return 0

    meal_id = get_test_meal_id()

    results = []
    run("List mensas / find a meal to test against", lambda: test_list_mensas_and_meals(meal_id), results)
    if meal_id is None:
        print("\nSKIP: no meal in the database to run rating tests against.")
        return 0

    run("Create rating via JSON body", lambda: test_create_rating_json(meal_id), results)
    run("Rating out of 1-5 range is rejected", lambda: test_rating_range_validation(meal_id), results)
    run("GET ratings includes meal_id and date", lambda: test_get_ratings_has_meal_id_and_date(meal_id), results)
    run("Photo upload via multipart form fields", lambda: test_photo_upload_via_form_fields(meal_id), results)
    run("Photos endpoint returns a non-empty date", lambda: test_photos_endpoint_has_date(meal_id), results)
    run("Frontend index page is served", test_frontend_served, results)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        print(f"{'✓ PASS' if ok else '✗ FAIL'}: {name}")
    print(f"\n{passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
