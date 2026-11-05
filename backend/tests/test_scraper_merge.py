"""One Meal row per (date, mensa, name), even when the page lists a dish twice.

CGiN's two counters can each serve the same dish with their own sauce, which the
scraper used to store as two rows -- two rating targets for one dish. See issue
#43: the descriptions are merged into one row and both variants' sides are still
extracted.
"""
from datetime import date

import pytest
from bs4 import BeautifulSoup
from sqlalchemy.exc import IntegrityError

import scraper
from database import Meal as DBMeal, Mensa as DBMensa

DAY = date(2026, 1, 15)
NAME = 'Vegane chinesische Reisgemüsepfanne'


def _table(rows):
    """Build a menu table from (type cell, name, description) triples."""
    body = ''.join(
        f'<tr><td>{type_cell}</td><td><strong>{name}</strong> {desc}'
        f'<i class="smaller">(1)</i></td></tr>'
        for type_cell, name, desc in rows
    )
    html = f'<table class="sp_tab"><tr><th><strong>CGiN</strong></th></tr>{body}</table>'
    return BeautifulSoup(html, 'html.parser').find('table')


@pytest.fixture()
def db(sqlite_db, monkeypatch):
    # scraper imports SessionLocal at module level, so patching database (which
    # conftest already does) is not enough for it.
    monkeypatch.setattr(scraper, 'SessionLocal', sqlite_db)
    session = sqlite_db()
    yield session
    session.close()


def _write(db, de_table, en_table=None):
    scraper._write_day(DAY, {'CGiN': de_table}, {'CGiN': en_table} if en_table else {})
    db.expire_all()  # _write_day used its own session


def test_two_counters_become_one_row_with_both_descriptions(db):
    de_table = _table([
        ('Hauptspeise', NAME, 'mit hausgemachte süß-saure Sauce, Basmatireis'),
        ('Hauptspeise', NAME, 'mit hausgemachte scharfe Sauce mit Hühnerfleisch, Trüffel Pommes'),
    ])
    en_table = _table([
        ('Main', NAME, 'with homemade sweet-and-sour sauce, basmati rice'),
        ('Main', NAME, 'with homemade spicy sauce with chicken, truffle fries'),
    ])

    _write(db, de_table, en_table)

    rows = db.query(DBMeal).filter(DBMeal.type == 'main').all()
    assert len(rows) == 1
    row = rows[0]
    assert row.name == NAME
    assert row.date == DAY
    assert row.description_de == (
        'mit hausgemachte süß-saure Sauce, Basmatireis; '
        'mit hausgemachte scharfe Sauce mit Hühnerfleisch, Trüffel Pommes'
    )
    assert row.description_en == (
        'with homemade sweet-and-sour sauce, basmati rice; '
        'with homemade spicy sauce with chicken, truffle fries'
    )
    # Both counters' side choices are still rateable.
    sides = {m.name for m in db.query(DBMeal).filter(DBMeal.type == 'side').all()}
    assert sides == {'Basmatireis', 'Trüffel Pommes'}


def test_rerun_does_not_grow_the_merged_description(db):
    de_table = _table([
        ('Hauptspeise', NAME, 'mit hausgemachte süß-saure Sauce'),
        ('Hauptspeise', NAME, 'mit hausgemachte scharfe Sauce mit Hühnerfleisch'),
    ])

    _write(db, de_table)
    _write(db, de_table)

    rows = db.query(DBMeal).all()
    assert len(rows) == 1
    assert rows[0].description_de == (
        'mit hausgemachte süß-saure Sauce; '
        'mit hausgemachte scharfe Sauce mit Hühnerfleisch'
    )


def test_identical_duplicate_is_merged_once(db):
    de_table = _table([
        ('Hauptspeise', NAME, 'mit hausgemachte süß-saure Sauce'),
        ('Hauptspeise', NAME, 'mit hausgemachte süß-saure Sauce'),
    ])

    _write(db, de_table)

    assert db.query(DBMeal).count() == 1
    assert db.query(DBMeal).one().description_de == 'mit hausgemachte süß-saure Sauce'


def test_database_rejects_a_second_row_with_the_same_identity(db):
    """The model constraint, not just the scraper, holds the identity rule."""
    mensa = DBMensa(name='CGiN')
    db.add(mensa)
    db.commit()

    for _ in range(2):
        db.add(DBMeal(name=NAME, name_de=NAME, type='main',
                      date=DAY, mensa_id=mensa.id, is_available=True))
    with pytest.raises(IntegrityError):
        db.commit()
