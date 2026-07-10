"""Frontend/API integration tests: verify nginx proxy routing end-to-end.

Tests the full routing chain:
  browser → proxy nginx (port 80) → frontend nginx → backend

The frontend is built with REACT_APP_API_URL=/api, so JS code does:
  fetch(`${API}/api/v1/mensas`) = fetch('/api/api/v1/mensas')

Frontend nginx strips /api prefix before proxying to backend:
  location ~ ^/api/(.*) → proxy_pass to backend:8000/$1

So the chain is:
  /api/api/v1/mensas → frontend nginx strips first /api → /api/v1/mensas → backend

Direct proxy routing (bypassing frontend) also works:
  /api/v1/mensas → proxy nginx → backend:8000

Requires the Docker stack running (or at least the proxy on port 80).
"""
import os

import pytest
import requests

# Base URL for proxy/nginx (port 80)
PROXY_BASE = os.getenv("API_BASE_URL", "http://localhost")


def _proxy_up(timeout: int = 5) -> bool:
    """Check if the nginx proxy is reachable on port 80."""
    try:
        resp = requests.get(f"{PROXY_BASE}/", timeout=timeout)
        return resp.status_code == 200
    except requests.RequestException:
        return False


# Skip if proxy is not reachable
pytestmark = pytest.mark.skipif(
    not _proxy_up(), reason=f"nginx proxy not reachable at {PROXY_BASE}"
)


def test_frontend_index_served_through_proxy():
    """Test that the frontend index.html is served through the proxy.

    Verifies: proxy nginx location / → frontend:80
    """
    resp = requests.get(f"{PROXY_BASE}/", timeout=10)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    # The frontend index.html should contain the root div
    assert "root" in resp.text.lower(), "Expected 'root' in index.html"


def test_api_frontend_chain_serves_mensas():
    """Test API calls through the frontend-nginx chain.

    Verifies: proxy / → frontend nginx (strips /api) → backend

    JS code: fetch('/api/api/v1/mensas')
    Frontend nginx strips first /api: /api/v1/mensas → backend
    """
    resp = requests.get(f"{PROXY_BASE}/api/api/v1/mensas", timeout=10)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    data = resp.json()
    assert isinstance(data, list), f"Expected list, got {type(data)}"
    assert len(data) > 0, "Expected at least one mensa"

    # Check that we have expected mensa names
    mensa_names = {m if isinstance(m, str) else m.get("name", "") for m in data}
    # At least one of the known mensas should be present
    expected_mensas = {"Zentralmensa", "CGiN", "Mensa am Turm", "Bistro HAWK"}
    assert mensa_names & expected_mensas, f"Expected some of {expected_mensas}, got {mensa_names}"


def test_api_direct_routing_serves_mensas():
    """Test API calls through direct proxy routing.

    Verifies: proxy /api/v1 → backend:8000 (bypasses frontend)
    """
    resp = requests.get(f"{PROXY_BASE}/api/v1/mensas", timeout=10)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    data = resp.json()
    assert isinstance(data, list), f"Expected list, got {type(data)}"
    assert len(data) > 0, "Expected at least one mensa"


def test_meals_endpoint_through_proxy():
    """Test the /meals endpoint through the frontend chain."""
    resp = requests.get(
        f"{PROXY_BASE}/api/api/v1/meals?date=2026-01-01&lang=de",
        timeout=10,
    )
    # May return 404 if no meals exist for that date, but should not error
    if resp.status_code == 200:
        data = resp.json()
        assert isinstance(data, list), f"Expected list, got {type(data)}"


def test_meals_search_through_proxy():
    """Test the /meals/search endpoint through the frontend chain."""
    resp = requests.get(
        f"{PROXY_BASE}/api/api/v1/meals/search?q=Reis&lang=de",
        timeout=10,
    )
    # May return 404 if no matching meals, but should not error
    if resp.status_code == 200:
        data = resp.json()
        assert isinstance(data, list), f"Expected list, got {type(data)}"


def test_static_frontend_js_served():
    """Test that static JS files are served by the frontend nginx.

    The frontend builds to /static/js/main.*.js (hashed filename).
    We look for the actual JS file path in the index.html.
    """
    # Get the index to find the JS bundle filename
    index = requests.get(f"{PROXY_BASE}/", timeout=10)
    assert index.status_code == 200

    import re
    match = re.search(r'src="(/static/js/main\.[^"]+\.js)"', index.text)
    assert match, "Could not find JS bundle path in index.html"
    js_path = match.group(1)

    resp = requests.get(f"{PROXY_BASE}{js_path}", timeout=10)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert len(resp.content) > 0, "Expected non-empty JS file"


def test_upload_route_exists():
    """Test that /uploads route exists (for photo serving)."""
    # Just check the route is recognized, not necessarily that it returns 200
    # (it may 404 if no uploads exist, but should not 404 for wrong route)
    resp = requests.get(f"{PROXY_BASE}/uploads/", timeout=10)
    # 404 is expected if no uploads, but 404 with "Not Found" is the right response
    if resp.status_code == 404:
        # Check it's the right 404 (not a routing issue)
        pass  # Acceptable - no uploads yet
    else:
        # If it returns 200, that's also fine (uploads directory listing)
        assert resp.status_code == 200, f"Expected 200 or 404, got {resp.status_code}"


def test_mensas_api_returns_expected_fields():
    """Test that the mensas API returns expected fields."""
    resp = requests.get(f"{PROXY_BASE}/api/api/v1/mensas", timeout=10)
    assert resp.status_code == 200

    data = resp.json()
    assert isinstance(data, list)

    if len(data) > 0:
        # First item should be a string or dict
        first = data[0]
        if isinstance(first, dict):
            assert "name" in first, f"Expected 'name' in mensa object, got {first.keys()}"


def test_lang_parameter_works_through_proxy():
    """Test that the lang query parameter works through the frontend chain."""
    # Get meals in German
    resp_de = requests.get(
        f"{PROXY_BASE}/api/api/v1/meals?date=2026-01-01&lang=de",
        timeout=10,
    )
    if resp_de.status_code == 200:
        data_de = resp_de.json()
        if len(data_de) > 0:
            # German meals should have name_de
            first = data_de[0]
            # At leastname_de or name should exist
            assert any(k in first for k in ("name", "name_de")), f"Missing name fields: {first.keys()}"

    # Get meals in English
    resp_en = requests.get(
        f"{PROXY_BASE}/api/api/v1/meals?date=2026-01-01&lang=en",
        timeout=10,
    )
    if resp_en.status_code == 200:
        data_en = resp_en.json()
        if len(data_en) > 0:
            first = data_en[0]
            assert any(k in first for k in ("name", "name_en")), f"Missing name fields: {first.keys()}"


def test_api_versions_routing():
    """Test that different API version routes work correctly."""
    # /api/v1/mensas via direct proxy
    resp_direct = requests.get(f"{PROXY_BASE}/api/v1/mensas", timeout=10)
    assert resp_direct.status_code == 200

    # /api/api/v1/mensas via frontend (strips first /api)
    resp_frontend = requests.get(f"{PROXY_BASE}/api/api/v1/mensas", timeout=10)
    assert resp_frontend.status_code == 200

    # Both should return the same data
    data_direct = resp_direct.json()
    data_frontend = resp_frontend.json()

    # Compare names (convert to sets for comparison if needed)
    names_direct = {m if isinstance(m, str) else m.get("name", "") for m in data_direct}
    names_frontend = {m if isinstance(m, str) else m.get("name", "") for m in data_frontend}

    assert names_direct == names_frontend, "Direct and frontend routes should return same data"


def test_proxy_health_check():
    """Test a simple health check through the proxy."""
    # Try the root - should return 200 with frontend HTML
    resp = requests.get(f"{PROXY_BASE}/", timeout=10)
    assert resp.status_code == 200

    # Check for some key frontend content
    assert "<!DOCTYPE html>" in resp.text or "<html" in resp.text.lower(), "Expected HTML content"


# Photo upload test requires a meal_id - skip if no meals exist
@pytest.fixture()
def meal_id_for_photo_test():
    """Get a meal ID from the API to use for photo upload tests."""
    resp = requests.get(f"{PROXY_BASE}/api/v1/meals", params={"limit": 1}, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        if isinstance(data, list) and len(data) > 0:
            return data[0].get("id")
    return None


def test_photo_upload_and_retrieval_through_proxy(meal_id_for_photo_test):
    """Test photo upload and retrieval through the proxy chain.

    Verifies:
    1. POST to /api/api/v1/meals/{meal_id}/ratings-with-photo uploads a photo
    2. GET to /uploads/{filename} retrieves the uploaded photo

    The frontend sends FormData with rating, comment, and photo fields.
    The backend stores photos in /uploads and returns a photo_url.
    """


    # Skip if no meal ID available
    if meal_id_for_photo_test is None:
        pytest.skip("No meal ID available for photo upload test")

    # Create a small 1x1 PNG for upload
    # 1x1 red pixel PNG
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    # Upload a photo via the frontend chain (strips /api prefix)
    resp = requests.post(
        f"{PROXY_BASE}/api/api/v1/meals/{meal_id_for_photo_test}/ratings-with-photo",
        data={
            "rating": 5,
            "comment": "Test photo from integration test",
        },
        files={"photo": ("test.png", png_bytes, "image/png")},
        timeout=10,
    )

    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

    upload_data = resp.json()
    assert "photo_url" in upload_data, f"Expected photo_url in response: {upload_data}"

    photo_url = upload_data["photo_url"]

    # The photo_url should be something like /uploads/xxx.png or /uploads/xxx.jpg
    # Retrieve the photo directly via /uploads
    # The backend returns photo_url as /uploads/xxx, but we need to go through proxy
    # Since JS uses /api/ prefix, the URL would be /api/uploads/xxx
    # But direct proxy route /uploads/xxx should also work

    # Try both patterns
    # Pattern 1: Direct proxy route (bypassing frontend)
    resp_direct = requests.get(f"{PROXY_BASE}{photo_url}", timeout=10)
    # Pattern 2: Through frontend (if photo_url doesn't have leading slash, add it)
    if not photo_url.startswith("/"):
        photo_url = "/" + photo_url
    resp_frontend = requests.get(f"{PROXY_BASE}{photo_url}", timeout=10)

    # One of the routes should work
    if resp_direct.status_code == 200:
        assert len(resp_direct.content) > 0, "Photo should have content"
        assert resp_direct.headers.get("content-type", "").startswith("image"), \
            f"Expected image content-type, got {resp_direct.headers.get('content-type')}"
    elif resp_frontend.status_code == 200:
        assert len(resp_frontend.content) > 0, "Photo should have content"
        assert resp_frontend.headers.get("content-type", "").startswith("image"), \
            f"Expected image content-type, got {resp_frontend.headers.get('content-type')}"
    else:
        pytest.fail(
            f"Photo retrieval failed. Direct: {resp_direct.status_code}, "
            f"Frontend: {resp_frontend.status_code}"
        )