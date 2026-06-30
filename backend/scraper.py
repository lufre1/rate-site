"""
Menu scraper for the Studierendenwerk Göttingen cached Speiseplan pages.

Scrapes alle.html (bundled page) first for each date. Falls back to
individual mensa URLs if alle.html is unavailable or incomplete.

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
from database import SessionLocal, Meal as DBMeal, Mensa as DBMensa

ALL_URL = "https://www.studierendenwerk-goettingen.de/fileadmin/templates/php/mensaspeiseplan/cached/de/{date}/alle.html"
CACHE_URL = "https://www.studierendenwerk-goettingen.de/fileadmin/templates/php/mensaspeiseplan/cached/de/{date}/{mensa}.html"

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


def _scrape_table(db, table, mensa_obj, date_obj, seen_dishes):
    """Scrape rows from one mensa table. Track seen_dishes to avoid duplicates within alle.html."""
    count = 0
    for row in table.find_all('tr')[1:]:
        dish = _parse_dish_row(row)
        if not dish:
            continue

        # Skip duplicates (same name + description, not just name alone)
        desc_key = dish.get('description') or ''
        dedup_key = (dish['name'], desc_key, mensa_obj.id)
        if dedup_key in seen_dishes:
            continue
        seen_dishes.add(dedup_key)

        exists = db.query(DBMeal).filter(
            DBMeal.name == dish['name'],
            DBMeal.date == date_obj,
            DBMeal.mensa_id == mensa_obj.id,
        ).first()

        if not exists:
            db.add(DBMeal(
                name=dish['name'],
                description=dish.get('description'),
                tags=json.dumps(dish.get('tags') or []) if dish.get('tags') else None,
                type=dish['type'],
                date=date_obj,
                mensa_id=mensa_obj.id,
            ))
            count += 1
    return count


# Add json import at the top of the file if not already there (checked below)


def scrape_menus():
    db = SessionLocal()
    try:
        today = date.today()
        new_count = 0
        for offset in range(7):
            scrape_date = today + timedelta(days=offset)
            date_str = scrape_date.strftime('%Y-%m-%d')
            seen_dishes = set()

            # Strategy: try alle.html first (one fetch gets all mensas)
            alle_url = ALL_URL.format(date=date_str)
            resp = requests.get(alle_url, timeout=10)

            if resp.status_code == 200 and len(resp.text) > 1000:
                # alle.html has data — parse all mensas from one document
                soup = BeautifulSoup(resp.text, 'html.parser')
                tables = soup.find_all('table', class_='sp_tab')

                for table in tables:
                    th = table.find('tr').find('th')
                    if th:
                        ms = th.find('strong')
                        current_mensa = ms.get_text(strip=True) if ms else None
                    else:
                        current_mensa = None

                    if not current_mensa:
                        continue

                    mensa_alias = None
                    for alias, fullname in ALIAS_MAP.items():
                        if fullname == current_mensa:
                            mensa_alias = alias
                            break

                    if not mensa_alias:
                        continue

                    mensa_obj = db.query(DBMensa).filter(
                        DBMensa.name == current_mensa
                    ).first()
                    if not mensa_obj:
                        mensa_obj = DBMensa(name=current_mensa)
                        db.add(mensa_obj)
                        db.commit()
                        db.refresh(mensa_obj)

                    new_count += _scrape_table(db, table, mensa_obj, scrape_date, seen_dishes)

            else:
                # alle.html too small or unavailable — fall back to individual URLs
                for mensa_alias, mensa_name in ALIAS_MAP.items():
                    url = CACHE_URL.format(date=date_str, mensa=mensa_alias)
                    resp = requests.get(url, timeout=10)
                    if resp.status_code != 200 or len(resp.text) < 300:
                        continue

                    soup = BeautifulSoup(resp.text, 'html.parser')
                    tables = soup.find_all('table', class_='sp_tab')
                    for table in tables:
                        th = table.find('tr').find('th')
                        if th:
                            ms = th.find('strong')
                            current_mensa = ms.get_text(strip=True) if ms else mensa_name
                        else:
                            current_mensa = mensa_name

                        mensa_obj = db.query(DBMensa).filter(
                            DBMensa.name == current_mensa
                        ).first()
                        if not mensa_obj:
                            mensa_obj = DBMensa(name=current_mensa)
                            db.add(mensa_obj)
                            db.commit()
                            db.refresh(mensa_obj)

                        new_count += _scrape_table(db, table, mensa_obj, scrape_date, seen_dishes)

        db.commit()
        print(f'Scraper OK - scraped {date.today()} + 6 days, {new_count} new meals')
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f'Scraper error: {e}')
    finally:
        db.close()
