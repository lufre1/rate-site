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

from bs4 import BeautifulSoup

from scraper import (
    ALL_URL, CACHE_URL, ALL_URL_EN, CACHE_URL_EN, ALIAS_MAP,
    _mensa_tables_for_date, _dish_rows, _parse_dish_row, _parse_dish_rows,
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


# --- Multi-item rows (CGiN "Heute : Grillfest") -----------------------------
#
# Offline tests against markup copied verbatim from the live cached pages.
# This row shape has no <strong>: the heading sits in the type cell and every
# item is its own priced line, so one row yields one dish per line.

GRILLFEST_DE = '''<table class="sp_tab"><tr class="even"><td class="sp_typ">Heute : Grillfest</td><td class="sp_bez">Bratwurst im Brötchen. Senf/Tomatenketchup 2,60 €
Krakauer im Brötchen. Senf/Tomatenketchup 3,30 €
Mariniertes Schweinerückensteak. Tomatenketchup/Paprikasalsa 4,10 €
Mariniertes Putensteak. Tomatenkechuo/Paprikasalsa 4,10 €
Grillkäse mit Paprikasalsa 3,30 €
Ofenkartoffel mit Veganem Kräuterquark 3,00 €
Große Vegane Champignonpfanne mit Veganer Aioli Dip 3,30 €
Bunter Bauernsalat. Vegan 1,15 €
Bunter Kartoffelsalat Vegan mit Essig und Öl 1,10 €
Fladenbrot. Vegan 1,10 €


Kann a-k und 1-8 enthalten<br/><i class="smaller">(Mittagsangebot)</i></td><td class="sp_hin"><img src="/fileadmin/templates/images/mensaspeiseplan/png/vegan.png" /></td></tr></table>'''

# The English page serves Last Minute boilerplate in this very slot.
GRILLFEST_EN = '''<table class="sp_tab"><tr class="even"><td class="sp_typ">Heute : Grillfest</td><td class="sp_bez">Last Minute Mo. - Fr. 14:00 to 14:15 - Only while stocks last! 1 main course + 2 side dishes or 1 combination dish + 1 side dish May contain (1-11) and (a-n).For further information please ask our service staff.<br/><i class="smaller">(lunch offer)</i></td><td class="sp_hin"><img src="/fileadmin/templates/images/mensaspeiseplan/png/vegan.png" /></td></tr></table>'''

NORMAL_ROW_DE = '''<table class="sp_tab"><tr class="odd"><td class="sp_typ">Nds-Menü Vegan</td><td class="sp_bez"><strong>Vegane Dim Sum Spicy Jackfruit (a.1,a)</strong><br/>vegane Erdnuss-Kokos-Chilisauce (1,3,a.1,a,e,f,l), Kaiserschoten<br/><i class="smaller">(Mittagsangebot)</i></td><td class="sp_hin"><img src="/fileadmin/templates/images/mensaspeiseplan/png/vegan.png" /><img src="/fileadmin/templates/images/mensaspeiseplan/png/NDS.png" /></td></tr></table>'''


def _row(html):
    return BeautifulSoup(html, 'html.parser').find('tr')


@pytest.fixture(scope="module")
def grillfest():
    return _parse_dish_rows(_row(GRILLFEST_DE))


def test_grillfest_row_explodes_into_items(grillfest):
    names = [d['name'] for d in grillfest]
    assert len(grillfest) == 10, f"expected one dish per priced line, got {names}"
    for expected in ('Bratwurst im Brötchen', 'Bunter Bauernsalat', 'Fladenbrot'):
        assert expected in names, f"{expected!r} missing from {names}"
    # The umbrella heading must not survive as a dish of its own.
    assert 'Heute : Grillfest' not in names
    # The trailing "Kann a-k und 1-8 enthalten" line carries no price, so it
    # is not an item.
    assert not any('enthalten' in n for n in names), names
    for dish in grillfest:
        assert '€' not in dish['name'], dish
        assert '€' not in (dish['description'] or ''), dish


def test_grillfest_price_classifies_type(grillfest):
    sides = sorted(d['name'] for d in grillfest if d['type'] == 'side')
    mains = [d['name'] for d in grillfest if d['type'] == 'main']
    assert sides == ['Bunter Bauernsalat', 'Bunter Kartoffelsalat', 'Fladenbrot']
    assert len(mains) == 7, mains


def test_grillfest_name_description_split(grillfest):
    by_name = {d['name']: d for d in grillfest}
    assert by_name['Bratwurst im Brötchen']['description'] == 'Senf/Tomatenketchup'
    # No period here -- the split happens at the standalone diet word.
    assert by_name['Bunter Kartoffelsalat']['description'] == 'Vegan mit Essig und Öl'
    # ...but "Vegane"/"Veganer" mid-name must not split it.
    assert 'Große Vegane Champignonpfanne mit Veganer Aioli Dip' in by_name


def test_grillfest_tags_not_inherited_from_row(grillfest):
    """The row's single vegan.png describes the block, not the Bratwurst."""
    by_name = {d['name']: d for d in grillfest}
    assert by_name['Bratwurst im Brötchen']['tags'] is None
    assert by_name['Fladenbrot']['tags'] == ['vegan.png']


def test_english_last_minute_row_is_skipped():
    """The English Grillfest slot holds Last Minute boilerplate, not a dish."""
    assert _parse_dish_row(_row(GRILLFEST_EN)) is None
    assert _parse_dish_rows(_row(GRILLFEST_EN)) == []


def test_normal_row_unchanged():
    """A regular <strong> row still parses exactly as before."""
    dishes = _parse_dish_rows(_row(NORMAL_ROW_DE))
    assert len(dishes) == 1
    dish = dishes[0]
    assert dish['name'] == 'Vegane Dim Sum Spicy Jackfruit'
    assert dish['description'] == 'vegane Erdnuss-Kokos-Chilisauce, Kaiserschoten'
    assert dish['type'] == 'main'
    assert dish['tags'] == ['vegan.png', 'NDS.png']
