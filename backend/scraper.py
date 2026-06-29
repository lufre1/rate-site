"""
Menu scraper for the Studierendenwerk Göttingen cached Speiseplan pages.

The cached HTML format per row:
  <td class="sp_type">Vegan</td>
  <td class="sp_bez">
    <strong>MAIN DISH (a,1,a)</strong><br/>
    sub-ingredients, toppings<br/>
    <i class="smaller">(Mittagsangebot)</i>
  </td>
"""
import re
import requests
from bs4 import BeautifulSoup, Tag
from datetime import date, timedelta
from sqlalchemy import text
from sqlalchemy.orm import Session
from database import SessionLocal, Meal as DBMeal, Mensa as DBMensa, Rating as DBRating

CACHE_URL = "https://www.studierendenwerk-goettingen.de/fileadmin/templates/php/mensaspeiseplan/cached/de/{date}/{mensa}.html"

MENSAS_MAP = {
    "zentralmensa": "Zentralmensa",
    "cgin": "CGiN",
    "mensa_am_turm": "Mensa am Turm",
    "bistro_hawk": "Bistro HAWK",
}


def parse_dish_row(row) -> dict | None:
    """Parse one menu row. Returns dict with name, description, type or None."""
    cells = row.find_all('td')
    if len(cells) < 2:
        return None

    type_cell = cells[0].get_text(strip=True).lower()

    # Skip non-rating items
    if 'last minute' in type_cell:
        return None
    desc_text = cells[1].get_text()
    if 'Selbstbedienung' in desc_text or 'Pastabuffet' in type_cell:
        return None

    # Determine type
    if 'dessert' in type_cell or 'Dessert' in type_cell:
        dish_type = 'dessert'
    elif 'eintopf' in type_cell:
        dish_type = 'main'
    elif 'suppe' in desc_text.lower():
        dish_type = 'main'
    else:
        dish_type = 'main'

    # Find the <strong> tag
    strong = cells[1].find('strong')
    if not strong:
        return None

    # Main name: text inside <strong>, minus parenthesized allergen codes
    raw_name = strong.get_text(strip=True)
    name = re.sub(r'\s*\([a-z0-9.,\-\/:() ]+\)', '', raw_name).strip()
    if not name or len(name) < 2:
        return None

    # Description: get text between </strong> and <i class="smaller">
    # The sub-ingredients are inside NavigableString nodes between <br/> tags
    parts = []
    node = strong.next_sibling
    while node:
        if not hasattr(node, 'name') or node.name == 'i' and 'smaller' in node.get('class', []):
            break
        if isinstance(node, Tag) and node.name == 'i':
            break
        text = getattr(node, 'get_text', lambda: '')().strip()
        if text and not re.search(r'Mittagsangebot|Abendangebot', text):
            parts.append(text)
        node = node.next_sibling

    description = ', '.join(parts) if parts else None
    if description:
        description = re.sub(r'\s*\([a-z0-9.,\-\/:() ]+\)\s*', '', description).strip()
        description = re.sub(r'\s+', ' ', description)

    return {
        'name': name,
        'description': description,
        'type': dish_type,
    }


def scrape_menus():
    db = SessionLocal()
    try:
        today = date.today()
        for offset in range(7):
            scrape_date = today + timedelta(days=offset)
            date_str = scrape_date.strftime('%Y-%m-%d')

            for mensa_key, mensa_name in MENSAS_MAP.items():
                url = CACHE_URL.format(date=date_str, mensa=mensa_key)
                resp = requests.get(url, timeout=10)
                if resp.status_code != 200:
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

                    for row in table.find_all('tr')[1:]:
                        dish = parse_dish_row(row)
                        if not dish:
                            continue

                        exists = db.query(DBMeal).filter(
                            DBMeal.name == dish['name'],
                            DBMeal.date == scrape_date,
                            DBMeal.mensa_id == mensa_obj.id
                        ).first()

                        if not exists:
                            db.add(DBMeal(
                                name=dish['name'],
                                description=dish['description'],
                                type=dish['type'],
                                date=scrape_date,
                                mensa_id=mensa_obj.id,
                            ))

        db.commit()
        print(f'Scraper OK - scraped {date.today()} + 6 days')
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f'Scraper error: {e}')
    finally:
        db.close()
