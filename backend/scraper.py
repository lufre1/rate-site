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
    ))
    return 'new'


def _reconcile(db, mensa_obj, date_obj, keep_names):
    """Delete stale rows for this date+mensa not in the current German name set.

    Removes leftovers from earlier buggy scrapes (e.g. English-named duplicate
    rows). Rows that already have ratings are preserved to avoid orphaning data.
    
    Never deletes rows for today or future dates — this preserves dishes that
    appear and disappear during the same day while still cleaning up old data.
    """
    from datetime import date as date_type
    today = date_type.today()
    if date_obj >= today:
        return 0  # never delete current/future rows
    
    rows = db.query(DBMeal).filter(
        DBMeal.date == date_obj,
        DBMeal.mensa_id == mensa_obj.id,
    ).all()
    removed = 0
    for row in rows:
        if row.name in keep_names:
            continue
        has_rating = db.query(DBRating).filter(DBRating.meal_id == row.id).first()
        has_side = db.query(DBSideRating).filter(DBSideRating.meal_id == row.id).first()
        if has_rating or has_side:
            continue
        db.delete(row)
        removed += 1
    return removed


def scrape_today():
    """Scrape only today's menus. Lightweight — used for the precise lunch-time pre-open updates."""
    db = SessionLocal()
    valid_names = set(ALIAS_MAP.values())
    try:
        today = date.today()
        date_str = today.strftime('%Y-%m-%d')

        de_tables = _mensa_tables_for_date(date_str, ALL_URL, CACHE_URL)
        en_tables = _mensa_tables_for_date(date_str, ALL_URL_EN, CACHE_URL_EN)

        new_count = 0
        updated_count = 0

        for mensa_name, de_table in de_tables.items():
            if mensa_name not in valid_names:
                continue

            mensa_obj = _get_or_create_mensa(db, mensa_name)

            de_rows = _dish_rows(de_table)
            en_table = en_tables.get(mensa_name)
            en_rows = _dish_rows(en_table) if en_table is not None else []

            if en_table is not None and len(en_rows) != len(de_rows):
                print(
                    f'WARNING: DE/EN row count mismatch for "{mensa_name}" on {date_str}: '
                    f'{len(de_rows)} DE vs {len(en_rows)} EN - pairing by index'
                )

            german_names = set()
            seen = set()

            for i, de_row in enumerate(de_rows):
                de_dish = _parse_dish_row(de_row)
                if not de_dish:
                    continue

                dedup_key = (de_dish['name'].lower(), (de_dish.get('description') or '').lower())
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                german_names.add(de_dish['name'])

                en_dish = _parse_dish_row(en_rows[i]) if i < len(en_rows) else None

                result = _upsert_meal(db, mensa_obj, today, de_dish, en_dish)
                if result == 'new':
                    new_count += 1
                else:
                    updated_count += 1

            _reconcile(db, mensa_obj, today, german_names)

        db.commit()
        print(f'scrape_today OK - {new_count} new, {updated_count} updated')
    except Exception as e:
        import traceback
        traceback.print_exc()
        db.rollback()
        print(f'scrape_today error: {e}')
    finally:
        db.close()


def scrape_menus():
    """Scrape German + English menus and merge them into one row per dish."""
    db = SessionLocal()
    valid_names = set(ALIAS_MAP.values())
    try:
        today = date.today()
        new_count = 0
        updated_count = 0
        removed_count = 0

        for offset in range(7):
            scrape_date = today + timedelta(days=offset)
            date_str = scrape_date.strftime('%Y-%m-%d')

            de_tables = _mensa_tables_for_date(date_str, ALL_URL, CACHE_URL)
            en_tables = _mensa_tables_for_date(date_str, ALL_URL_EN, CACHE_URL_EN)

            for mensa_name, de_table in de_tables.items():
                if mensa_name not in valid_names:
                    continue

                mensa_obj = _get_or_create_mensa(db, mensa_name)

                de_rows = _dish_rows(de_table)
                en_table = en_tables.get(mensa_name)
                en_rows = _dish_rows(en_table) if en_table is not None else []

                if en_table is not None and len(en_rows) != len(de_rows):
                    print(
                        f'WARNING: DE/EN row count mismatch for "{mensa_name}" on {date_str}: '
                        f'{len(de_rows)} DE vs {len(en_rows)} EN - pairing by index'
                    )

                german_names = set()
                seen = set()

                for i, de_row in enumerate(de_rows):
                    de_dish = _parse_dish_row(de_row)
                    if not de_dish:
                        continue  # German row decides inclusion

                    dedup_key = (de_dish['name'].lower(), (de_dish.get('description') or '').lower())
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)
                    german_names.add(de_dish['name'])

                    en_dish = _parse_dish_row(en_rows[i]) if i < len(en_rows) else None

                    result = _upsert_meal(db, mensa_obj, scrape_date, de_dish, en_dish)
                    if result == 'new':
                        new_count += 1
                    else:
                        updated_count += 1

                removed_count += _reconcile(db, mensa_obj, scrape_date, german_names)

        db.commit()
        print(
            f'Scraper OK - scraped {today} + 6 days, '
            f'{new_count} new, {updated_count} updated, {removed_count} stale removed'
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        db.rollback()
        print(f'Scraper error: {e}')
    finally:
        db.close()
