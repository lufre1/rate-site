"""
Menu scraper for the Studierendenwerk Göttingen cached Speiseplan pages.

For each date it fetches BOTH the German and English `alle.html` documents and
merges them into a single Meal row per dish. The German and English cached pages
have identical table/row structure, so dishes are paired positionally at the raw
`<tr>` level: the German row decides whether a dish is included (its skip rules
run on German text), and the English row at the same index supplies the English
name/description. This guarantees no duplicate rows and no language desync.

Falls back to individual mensa URLs if alle.html is unavailable.

The cached HTML format per row:
  <td class="sp_typ">Vegan</td>
  <td class="sp_bez">
    <strong>MAIN DISH (a,1,a)</strong><br/>
    sub-ingredients, toppings<br/>
    <i class="smaller">(Mittagsangebot)</i>
  </td>
"""

import re
import json
import requests
from bs4 import BeautifulSoup, Tag
import logging

log = logging.getLogger("scraper")
from datetime import date, timedelta
from database import (
    SessionLocal,
    Meal as DBMeal,
    Mensa as DBMensa,
    Rating as DBRating,
    SideRating as DBSideRating,
)

# URLs for German content
ALL_URL = "https://www.studierendenwerk-goettingen.de/fileadmin/templates/php/mensaspeiseplan/cached/de/{date}/alle.html"
CACHE_URL = "https://www.studierendenwerk-goettingen.de/fileadmin/templates/php/mensaspeiseplan/cached/de/{date}/{mensa}.html"

# URLs for English content
ALL_URL_EN = "https://www.studierendenwerk-goettingen.de/fileadmin/templates/php/mensaspeiseplan/cached/en/{date}/alle.html"
CACHE_URL_EN = "https://www.studierendenwerk-goettingen.de/fileadmin/templates/php/mensaspeiseplan/cached/en/{date}/{mensa}.html"

ALIAS_MAP = {
    "zentralmensa": "Zentralmensa",
    "cgin": "CGiN",
    "mensa_am_turm": "Mensa am Turm",
    "bistro_hawk": "Bistro HAWK",
}

# Last Minute boilerplate, in either language. The type cell usually says
# "Last Minute", but CGiN's English page puts this text in the Grillfest row.
LAST_MINUTE_RE = re.compile(
    r'Only while stocks last|Nur solange der Vorrat reicht', re.IGNORECASE
)

# A price as the menu writes it: "2,60 €".
PRICE_RE = re.compile(r'(\d+)[,.](\d+)\s*€')

# Multi-item rows (e.g. CGiN "Heute : Grillfest") list every item on its own
# line with its own price, instead of wrapping one dish in <strong>. This many
# priced lines is what tells such a row apart from prose that mentions a price.
MULTI_ITEM_MIN_LINES = 3

# Within a multi-item row, price is what separates a side from a main: the
# salads and the Fladenbrot go for 1,10-1,15 €, every grill item for 2,60-4,10 €.
SIDE_PRICE_MAX = 2.00

# Diet words the menu appends to an item, e.g. "Bunter Bauernsalat. Vegan".
# Word boundaries matter -- "Vegane", "Veganer" and "Veganem" appear mid-name
# and must not split it.
DIET_RE = re.compile(r'\b(Vegan|Vegetarisch)\b')
DIET_TAGS = {'vegan': 'vegan.png', 'vegetarisch': 'vegetarisch.png'}


def _normalize(name):
    """Remove parenthesized allergen codes from a name string."""
    if not name:
        return ""
    return re.sub(r'\s*\([^)]*\)', '', name).strip()


def _parse_dish_row(row) -> dict | None:
    """Parse one menu row. Returns dict with name, description, type, and tags."""
    cells = row.find_all('td')
    if len(cells) < 2:
        return None

    raw_type = cells[0].get_text(strip=True)
    type_lower = raw_type.lower()

    # Skip non-rating items
    if 'last minute' in type_lower:
        return None
    if 'pastabuffet' in type_lower:
        return None

    bez_text = cells[1].get_text()
    if 'Selbstbedienung' in bez_text:
        return None
    # The English page sometimes serves the Last Minute blurb in an unrelated
    # row (CGiN's Grillfest slot), so the type-cell check above misses it.
    if LAST_MINUTE_RE.search(bez_text):
        return None

    # Find the <strong> tag for the dish name
    strong = cells[1].find('strong')

    # Determine dish type based on type cell
    if 'dessert' in type_lower:
        dish_type = 'dessert'
    elif any(kw in type_lower for kw in ['beilage', 'salat', 'suppe', 'stärke', 'gemüsebeilage', 'krautsalat']):
        dish_type = 'side'
    else:
        dish_type = 'main'

    # Main name: text inside <strong>, minus parenthesized allergen codes
    if strong:
        raw_name = strong.get_text(strip=True)
        name = _normalize(raw_name)
        if not name or len(name) < 2:
            return None
    else:
        # Row without strong tag - use type cell text as name
        name = raw_type.split('/')[0].strip()
        if not name or len(name) < 2:
            return None

    # Description: get text between </strong> and <i class="smaller">
    parts = []
    node = strong.next_sibling if strong else None
    while node:
        if isinstance(node, Tag) and node.name == 'i':
            break
        text = getattr(node, 'get_text', lambda: '')().strip()
        if text and not re.search(r'Mittagsangebot|Abendangebot|Mittags', text, re.IGNORECASE):
            parts.append(text)
        node = node.next_sibling

    description = ', '.join(p for p in parts if p) if parts else None
    if description:
        description = _normalize(description).strip()
        description = re.sub(r'\s+', ' ', description)
        # Clean up common conjunction separators that shouldn't be treated as ingredients
        # Remove standalone "or" that looks like a separator (but not words like "oranges")
        description = re.sub(r',\s*or\s*,', ', ', description)
        description = re.sub(r'\s+or\s+,', ', ', description)
        description = re.sub(r'^or\s*,?\s*', '', description, flags=re.IGNORECASE)
        description = re.sub(r',?\s*or\s*$', '', description, flags=re.IGNORECASE)
        description = description.strip(', ')
        # Additional cleanup for "oder" in German
        description = re.sub(r',\s*oder\s*,', ', ', description)
        description = re.sub(r'\s+oder\s+,', ', ', description)
        description = re.sub(r'^oder\s*,?\s*', '', description, flags=re.IGNORECASE)
        description = re.sub(r',?\s*oder\s*$', '', description, flags=re.IGNORECASE)
        description = description.strip(', ')

    # Extract tags from the sp_hin column (3rd cell)
    tags = []
    if len(cells) > 2:
        hin_cell = cells[2]
        for img in hin_cell.find_all('img'):
            src = img.get('src', '')
            if src:
                file_name = src.split('/')[-1]
                if file_name:
                    tags.append(file_name)

    return {
        'name': name,
        'description': description,
        'type': dish_type,
        'tags': tags if tags else None,
    }


def _bez_lines(bez_cell):
    """Text of a description cell before the trailing <i class="smaller">, split into lines."""
    parts = []
    for node in bez_cell.children:
        if isinstance(node, Tag) and node.name == 'i':
            break
        text = node.get_text() if isinstance(node, Tag) else str(node)
        if text:
            parts.append(text)
    return ''.join(parts).splitlines()


def _parse_multi_item_row(row) -> list[dict] | None:
    """Parse a row that lists several priced items instead of wrapping one in <strong>.

    CGiN's "Heute : Grillfest" is the live example: the heading sits in the type
    cell and the description cell holds one item per line, each with its own
    price. Each line becomes a dish of its own so it can be rated individually.
    Returns None if the row is not of that shape.
    """
    cells = row.find_all('td')
    if len(cells) < 2 or cells[1].find('strong'):
        return None

    lines = [line.strip() for line in _bez_lines(cells[1])]
    priced = [line for line in lines if PRICE_RE.search(line)]
    if len(priced) < MULTI_ITEM_MIN_LINES:
        return None

    dishes = []
    for line in priced:
        price_match = PRICE_RE.search(line)
        price = float(f'{price_match.group(1)}.{price_match.group(2)}')
        text = PRICE_RE.sub('', line).strip()

        # Split name from description: on the first period if there is one,
        # otherwise at a trailing diet word ("Bunter Kartoffelsalat Vegan mit ...").
        if '.' in text:
            name, _, description = text.partition('.')
        else:
            diet = DIET_RE.search(text)
            if diet and diet.start() > 0:
                name, description = text[:diet.start()], text[diet.start():]
            else:
                name, description = text, ''

        name = _normalize(re.sub(r'\s+', ' ', name)).strip(' ,.')
        if len(name) < 2:
            continue
        description = _normalize(re.sub(r'\s+', ' ', description)).strip(' ,.')

        # The row's own sp_hin images describe the whole block -- CGiN's carries a
        # single vegan.png that would label the Bratwurst vegan -- so derive the
        # tag per item from its own text instead.
        diet = DIET_RE.search(text)
        tags = [DIET_TAGS[diet.group(1).lower()]] if diet else None

        dishes.append({
            'name': name,
            'description': description or None,
            'type': 'side' if price < SIDE_PRICE_MAX else 'main',
            'tags': tags,
            'multi_item': True,
        })

    return dishes or None


def _parse_dish_rows(row) -> list[dict]:
    """Parse one menu row into the dishes it contains (usually exactly one)."""
    dishes = _parse_multi_item_row(row)
    if dishes:
        return dishes
    dish = _parse_dish_row(row)
    return [dish] if dish else []


def _mensa_name_of(table):
    """Return the mensa name from a table's header row, or None."""
    first = table.find('tr')
    if not first:
        return None
    th = first.find('th')
    if not th:
        return None
    ms = th.find('strong')
    return ms.get_text(strip=True) if ms else None


def _fetch(url):
    """GET a URL; return text if it looks like a real page, else None."""
    try:
        resp = requests.get(url, timeout=10)
    except requests.RequestException:
        return None
    if resp.status_code != 200 or len(resp.text) < 1000:
        return None
    return resp.text


def _mensa_tables_for_date(date_str, all_url, cache_url):
    """Return {mensa_name: <table>} for a date, trying alle.html then per-mensa URLs."""
    tables = {}

    html = _fetch(all_url.format(date=date_str))
    if html:
        soup = BeautifulSoup(html, 'html.parser')
        for table in soup.find_all('table', class_='sp_tab'):
            name = _mensa_name_of(table)
            if name:
                tables.setdefault(name, table)
        if tables:
            return tables

    # Fallback: individual mensa pages
    for alias, fullname in ALIAS_MAP.items():
        html = _fetch(cache_url.format(date=date_str, mensa=alias))
        if not html:
            continue
        soup = BeautifulSoup(html, 'html.parser')
        for table in soup.find_all('table', class_='sp_tab'):
            name = _mensa_name_of(table) or fullname
            tables.setdefault(name, table)

    return tables


def _dish_rows(table):
    """Return the data rows of a mensa table (everything after the header row)."""
    return table.find_all('tr')[1:]


def _get_or_create_mensa(db, name):
    mensa_obj = db.query(DBMensa).filter(DBMensa.name == name).first()
    if not mensa_obj:
        mensa_obj = DBMensa(name=name)
        db.add(mensa_obj)
        db.commit()
        db.refresh(mensa_obj)
    return mensa_obj


def _upsert_meal(db, mensa_obj, date_obj, de_dish, en_dish):
    """Insert or update a single Meal row carrying both languages. Returns 'new'|'updated'."""
    name = de_dish['name']
    description = de_dish.get('description')
    tags = json.dumps(de_dish.get('tags') or []) if de_dish.get('tags') else None
    name_en = en_dish['name'] if en_dish else None
    description_en = en_dish.get('description') if en_dish else None

    exists = db.query(DBMeal).filter(
        DBMeal.name == name,
        DBMeal.date == date_obj,
        DBMeal.mensa_id == mensa_obj.id,
    ).first()

    if exists:
        exists.description = description
        exists.name_de = name
        exists.description_de = description
        exists.tags = tags
        exists.type = de_dish['type']
        exists.is_available = True
        # Only overwrite English fields when we actually have a value, so a
        # temporarily-missing English page doesn't wipe a good translation.
        if name_en:
            exists.name_en = name_en
            exists.description_en = description_en
        db.add(exists)
        return 'updated'

    db.add(DBMeal(
        name=name,
        name_de=name,
        name_en=name_en,
        description=description,
        description_de=description,
        description_en=description_en,
        tags=tags,
        type=de_dish['type'],
        date=date_obj,
        mensa_id=mensa_obj.id,
        is_available=True,
    ))
    return 'new'


def _reconcile(db, mensa_obj, date_obj, keep_names):
    """Mark stale rows as unavailable for this date+mensa not in the current German name set.

    Rows that already have ratings are preserved to avoid orphaning data, but
    marked as unavailable since they no longer appear on the official site.

    Returns count of dishes marked as unavailable.
    """
    rows = db.query(DBMeal).filter(
        DBMeal.date == date_obj,
        DBMeal.mensa_id == mensa_obj.id,
    ).all()
    unavailable_count = 0
    for row in rows:
        # Keep side entries (they're extracted from main dish descriptions)
        if row.type == 'side':
            continue
        if row.name in keep_names:
            continue
        has_rating = db.query(DBRating).filter(DBRating.meal_id == row.id).first()
        has_side = db.query(DBSideRating).filter(DBSideRating.meal_id == row.id).first()
        if has_rating or has_side:
            if row.is_available:
                row.is_available = False
                db.add(row)
                unavailable_count += 1
        else:
            db.delete(row)
    return unavailable_count


def _extract_and_create_sides(db, mensa_obj, date_obj, description, created_sides):
    """Extract side names from a main dish description and create side meal entries."""
    # Split description by comma and extract unique side names
    sides = set()
    for part in description.split(','):
        side_name = part.strip()
        # Filter out common non-side items (sauces, dressings, etc.)
        if not side_name:
            continue
        # Skip if it looks like a sauce/dressing (contains "sauce", "dressing", "ketchup", etc.)
        if any(kw in side_name.lower() for kw in ['sauce', 'dressing', 'ketchup', 'remoulade', 'mayo', 'senf', 'mit ', 'mit']):
            continue
        # Skip if too short
        if len(side_name) < 5:
            continue
        # Skip if it looks like a topping/dessert component
        if any(kw in side_name.lower() for kw in ['kompott', 'kompott', 'topping', 'zusätzlich', 'zusätzlich']):
            continue
        sides.add(side_name)

    # Track sides created in this call to avoid duplicates within same extraction
    mensa_key = (mensa_obj.id, date_obj)
    if mensa_key not in created_sides:
        created_sides[mensa_key] = set()
    
    for side_name in sides:
        # Check if side entry already exists in DB or was created in this run
        exists = db.query(DBMeal).filter(
            DBMeal.name == side_name,
            DBMeal.date == date_obj,
            DBMeal.mensa_id == mensa_obj.id,
        ).first()
        
        if not exists and side_name not in created_sides[mensa_key]:
            db.add(DBMeal(
                name=side_name,
                name_de=side_name,
                name_en=side_name,
                description=None,
                description_de=None,
                description_en=None,
                tags=None,
                type='side',
                date=date_obj,
                mensa_id=mensa_obj.id,
                is_available=True,
            ))
            created_sides[mensa_key].add(side_name)


def _fetch_day(date_str):
    """Fetch and parse one date's German + English tables. Does NO database work.

    Deliberately kept apart from _write_day. Each request in here can take up to
    _fetch's 10s timeout, and until 2026-09-02 they all ran *inside* an open
    session: scrape_menus() opened one session, looped 7 days of fetches and
    committed only at the very end, pinning a pool connection for the whole
    scrape. Readers were never blocked by its locks -- Postgres MVCC means a
    SELECT does not wait on a writer -- but one connection permanently missing
    from a pool of 10 was enough, back when a single page load fired 66
    requests, to push the surplus onto pool_timeout and stall the site for 10s.
    Keep the network out of the session.
    """
    de_tables = _mensa_tables_for_date(date_str, ALL_URL, CACHE_URL)
    en_tables = _mensa_tables_for_date(date_str, ALL_URL_EN, CACHE_URL_EN)
    return de_tables, en_tables


def _write_day(scrape_date, de_tables, en_tables):
    """Apply one date's already-fetched tables in one short transaction.

    Opens and closes its own session so the write transaction lives exactly as
    long as the writes. Returns (new, updated, removed).

    An empty `de_tables` is a no-op, which is what preserves existing data when
    the official site is unreachable: _reconcile only runs for a mensa that was
    actually scraped, so nothing gets marked unavailable on a failed fetch.
    """
    date_str = scrape_date.strftime('%Y-%m-%d')
    valid_names = set(ALIAS_MAP.values())

    # Keyed by (mensa_id, date), so scoping this per call is equivalent to the
    # single dict the old 7-day loop shared across every date.
    created_sides = {}

    new_count = 0
    updated_count = 0
    removed_count = 0

    db = SessionLocal()
    try:
        for mensa_name, de_table in de_tables.items():
            if mensa_name not in valid_names:
                continue

            mensa_obj = _get_or_create_mensa(db, mensa_name)

            de_rows = _dish_rows(de_table)
            en_table = en_tables.get(mensa_name)
            en_rows = _dish_rows(en_table) if en_table is not None else []

            if en_table is not None and len(en_rows) != len(de_rows):
                log.info(
                    f'WARNING: DE/EN row count mismatch for "{mensa_name}" on {date_str}: '
                    f'{len(de_rows)} DE vs {len(en_rows)} EN - pairing by index'
                )

            german_names = set()
            seen = set()

            for i, de_row in enumerate(de_rows):
                de_dishes = _parse_dish_rows(de_row)
                if not de_dishes:
                    continue  # German row decides inclusion

                # A multi-item row has no English counterpart worth pairing: the English
                # page serves unrelated Last Minute text in that slot, and _parse_dish_row
                # rejects it, so leave English empty and let main.py fall back to German.
                multi = de_dishes[0].get('multi_item')
                en_dish = None if multi else (_parse_dish_row(en_rows[i]) if i < len(en_rows) else None)

                for de_dish in de_dishes:
                    dedup_key = (de_dish['name'].lower(), (de_dish.get('description') or '').lower())
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)
                    german_names.add(de_dish['name'])

                    result = _upsert_meal(db, mensa_obj, scrape_date, de_dish, en_dish)
                    if result == 'new':
                        new_count += 1
                    else:
                        updated_count += 1

                    # Extract sides from main dish descriptions and create side entries.
                    # Multi-item rows are already split per item, and their text carries
                    # prices whose decimal comma would shred a comma split.
                    if not multi and de_dish['type'] == 'main' and de_dish.get('description'):
                        _extract_and_create_sides(db, mensa_obj, scrape_date, de_dish['description'], created_sides)

            removed_count += _reconcile(db, mensa_obj, scrape_date, german_names)

        db.commit()
    except Exception:
        # log.exception writes the message AND the traceback through the logging
        # handler, so it lands in the docker json log with the rest. The old
        # traceback.print_exc() went straight to stderr, unformatted and
        # unattributed, and the message itself was logged at INFO.
        db.rollback()
        log.exception(f'scraper failed writing {date_str}')
        return 0, 0, 0
    finally:
        db.close()

    return new_count, updated_count, removed_count


def scrape_today():
    """Scrape only today's menus. Lightweight — used for the precise lunch-time pre-open updates."""
    today = date.today()
    de_tables, en_tables = _fetch_day(today.strftime('%Y-%m-%d'))
    new_count, updated_count, _ = _write_day(today, de_tables, en_tables)
    log.info(f'scrape_today OK - {new_count} new, {updated_count} updated')


def scrape_menus():
    """Scrape German + English menus for the next 7 days and merge them into one row per dish.

    Each day is fetched with no session open, then written and committed before
    the next day is fetched. The old shape committed all 7 days in a single
    transaction, so a failure on day 5 threw away days 1-4; now every committed
    day stands on its own.
    """
    today = date.today()
    new_count = 0
    updated_count = 0
    removed_count = 0

    for offset in range(7):
        scrape_date = today + timedelta(days=offset)
        de_tables, en_tables = _fetch_day(scrape_date.strftime('%Y-%m-%d'))
        new, updated, removed = _write_day(scrape_date, de_tables, en_tables)
        new_count += new
        updated_count += updated
        removed_count += removed

    log.info(
        f'Scraper OK - scraped {today} + 6 days, '
        f'{new_count} new, {updated_count} updated, {removed_count} stale removed'
    )
