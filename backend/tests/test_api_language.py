"""API integration tests: hit a running backend and compare against the site.

Requires a reachable backend (set API_BASE_URL, default http://localhost:8000).
  docker compose up -d
  API_BASE_URL=http://localhost:8000 python -m pytest tests/test_api_language.py -v
"""
import os
from datetime import date, timedelta

import pytest
import requests

from scraper import (
    ALL_URL, CACHE_URL, ALIAS_MAP,
    _mensa_tables_for_date, _dish_rows, _parse_dish_row,
)

BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
VALID = set(ALIAS_MAP.values())


def _api_up():
    try:
        return requests.get(f"{BASE}/api/v1/mensas", timeout=5).status_code == 200
    except requests.RequestException:
        return False


pytestmark = pytest.mark.skipif(not _api_up(), reason=f"backend not reachable at {BASE}")


def _date_with_data():
    today = date.today()
    for o in range(7):
        d = today + timedelta(days=o)
        ds = d.strftime('%Y-%m-%d')
        tables = _mensa_tables_for_date(ds, ALL_URL, CACHE_URL)
        if any(n in VALID for n in tables):
            return d, tables
    pytest.skip("no menu data on the official site this week")


def _meals(date_obj, lang):
    return requests.get(
        f"{BASE}/api/v1/meals",
        params={"date": date_obj.isoformat(), "lang": lang},
        timeout=10,
    ).json()


def test_de_and_en_return_same_count():
    d, _ = _date_with_data()
    de = _meals(d, "de")
    en = _meals(d, "en")
    assert len(de) == len(en), f"DE returned {len(de)} items but EN returned {len(en)}"


def test_no_duplicate_names_per_mensa():
    d, _ = _date_with_data()
    for lang in ("de", "en"):
        by_mensa = {}
        for m in _meals(d, lang):
            by_mensa.setdefault(m["mensa"], []).append(m["name"])
        for mensa, names in by_mensa.items():
            assert len(names) == len(set(names)), \
                f"{lang} {mensa}: duplicate dish names {names}"


def test_count_matches_official_site():
    d, de_tables = _date_with_data()
    expected = 0
    for name, table in de_tables.items():
        if name not in VALID:
            continue
        names = {
            dish['name']
            for row in _dish_rows(table)
            if (dish := _parse_dish_row(row))
        }
        expected += len(names)
    meals = _meals(d, "de")
    # Exclude side entries from count (they're extracted from main dish descriptions)
    non_side_meals = [m for m in meals if m.get('type') != 'side']
    assert len(non_side_meals) == expected, \
        f"API returned {len(non_side_meals)} non-side DE items but the official site lists {expected}"
