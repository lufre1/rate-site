"""Parse-only tests against the LIVE official website (no database required).

These verify the core invariants that guarantee correct menus:
  * German and English pages have identical row structure (so positional pairing
    at the raw <tr> level is valid),
  * no duplicate dishes appear within a mensa,
  * every mensa we care about is present in both languages under the same name.

Run: cd backend && python -m pytest tests/test_scraper_alignment.py -v
"""
from datetime import date, timedelta

import pytest

from scraper import (
    ALL_URL, CACHE_URL, ALL_URL_EN, CACHE_URL_EN, ALIAS_MAP,
    _mensa_tables_for_date, _dish_rows, _parse_dish_row,
)

VALID = set(ALIAS_MAP.values())


def _week_dates():
    today = date.today()
    return [(today + timedelta(days=o)).strftime('%Y-%m-%d') for o in range(7)]


@pytest.fixture(scope="module")
def week():
    """Fetch DE and EN mensa tables for the next 7 days once (network)."""
    data = {}
    for ds in _week_dates():
        de = _mensa_tables_for_date(ds, ALL_URL, CACHE_URL)
        en = _mensa_tables_for_date(ds, ALL_URL_EN, CACHE_URL_EN)
        data[ds] = (de, en)
    return data


def test_site_returns_data(week):
    assert any(de for de, _ in week.values()), \
        "official site returned no menu for any of the next 7 days"


def test_de_en_row_counts_aligned(week):
    """DE and EN tables for the same mensa must have equal raw row counts."""
    checked = 0
    for ds, (de, en) in week.items():
        for name, de_table in de.items():
            if name not in VALID or name not in en:
                continue
            de_rows = _dish_rows(de_table)
            en_rows = _dish_rows(en[name])
            assert len(de_rows) == len(en_rows), (
                f"{ds} {name!r}: DE has {len(de_rows)} rows but EN has {len(en_rows)}; "
                f"positional pairing would desync"
            )
            checked += 1
    assert checked > 0, "no mensa had both DE and EN tables to compare"


def test_no_duplicate_dishes_within_mensa(week):
    for ds, (de, _) in week.items():
        for name, de_table in de.items():
            if name not in VALID:
                continue
            seen = set()
            for row in _dish_rows(de_table):
                dish = _parse_dish_row(row)
                if not dish:
                    continue
                key = (dish['name'].lower(), (dish.get('description') or '').lower())
                assert key not in seen, f"{ds} {name!r}: duplicate dish {dish['name']!r}"
                seen.add(key)


def test_valid_mensas_present_in_both_languages(week):
    for ds, (de, en) in week.items():
        if not de or not en:
            continue  # tolerate a day where one language has no page yet
        for name in (n for n in de if n in VALID):
            assert name in en, \
                f"{ds}: mensa {name!r} present in DE but not EN (mensa-name drift?)"
