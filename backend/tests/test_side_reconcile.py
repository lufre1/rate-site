"""Pruning of stale side rows (issue #22).

Sides are not listed on the menu page, they are extracted from a main dish's
description, so _reconcile used to skip every type='side' row and a mis-split
side ("Basmatireis oder Truffel Pommes") stayed rateable forever. These tests
pin the guards that make pruning safe, on a private SQLite database.
"""
from datetime import date

import pytest

import scraper
from database import Meal as DBMeal, Mensa as DBMensa, Rating as DBRating

DAY = date(2026, 9, 11)


@pytest.fixture()
def db(sqlite_db):
    db = sqlite_db()  # create a session from the sessionmaker
    db.add(DBMensa(name='Zentralmensa'))
    db.commit()
    yield db
    db.close()


@pytest.fixture()
def mensa(db):
    return db.query(DBMensa).first()


def _add(db, mensa, name, type='side', available=True):
    row = DBMeal(name=name, name_de=name, name_en=name, type=type,
                 date=DAY, mensa_id=mensa.id, is_available=available)
    db.add(row)
    db.commit()
    return row


def _names(db, type='side'):
    return {m.name for m in db.query(DBMeal).filter(DBMeal.type == type).all()}


def test_stale_unrated_side_is_deleted(db, mensa):
    _add(db, mensa, 'Basmatireis oder Trüffel Pommes')
    _add(db, mensa, 'Basmatireis')

    scraper._reconcile(db, mensa, DAY, keep_names=set(),
                       side_names={'Basmatireis'}, prune_sides=True)
    db.commit()

    assert _names(db) == {'Basmatireis'}


def test_rated_side_is_kept_but_marked_unavailable(db, mensa):
    row = _add(db, mensa, 'Basmatireis oder Trüffel Pommes')
    db.add(DBRating(meal_id=row.id, rating=4))
    db.commit()

    scraper._reconcile(db, mensa, DAY, keep_names=set(),
                       side_names={'Basmatireis'}, prune_sides=True)
    db.commit()

    kept = db.query(DBMeal).filter(DBMeal.name == 'Basmatireis oder Trüffel Pommes').one()
    assert kept.is_available is False
    assert db.query(DBRating).count() == 1


def test_page_listed_side_survives_pruning(db, mensa):
    """A "Beilage"/"Salat" row is typed 'side' but comes from the page itself."""
    _add(db, mensa, 'Gemischter Salat')

    scraper._reconcile(db, mensa, DAY, keep_names={'Gemischter Salat'},
                       side_names=set(), prune_sides=True)
    db.commit()

    assert _names(db) == {'Gemischter Salat'}


def test_nothing_extracted_never_prunes(db, mensa):
    """An empty page or a markup change must not wipe the day's sides."""
    _add(db, mensa, 'Basmatireis')
    _add(db, mensa, 'Pommes frites')

    scraper._reconcile(db, mensa, DAY, keep_names=set(),
                       side_names=set(), prune_sides=False)
    db.commit()

    assert _names(db) == {'Basmatireis', 'Pommes frites'}


def test_gate_off_leaves_sides_alone(db, mensa):
    """Default call signature = the old behaviour, sides are immortal."""
    _add(db, mensa, 'Basmatireis oder Trüffel Pommes')

    scraper._reconcile(db, mensa, DAY, keep_names=set())
    db.commit()

    assert _names(db) == {'Basmatireis oder Trüffel Pommes'}


def test_stale_main_still_reconciled_with_pruning_on(db, mensa):
    _add(db, mensa, 'Gestrichenes Gericht', type='main')

    scraper._reconcile(db, mensa, DAY, keep_names=set(),
                       side_names=set(), prune_sides=True)
    db.commit()

    assert _names(db, type='main') == set()


def test_today_reconcile_off_does_not_delete(db, mensa):
    """Today's mains should not be deleted even if the page drops them mid-day."""
    today = date.today()
    _add(db, mensa, 'Gestrichenes Gericht', type='main', available=True)

    scraper._reconcile(db, mensa, today, keep_names=set(),
                       side_names=set(), prune_sides=True, reconcile=False)
    db.commit()

    # The row should still exist (not deleted), and still available
    assert _names(db, type='main') == {'Gestrichenes Gericht'}
    row = db.query(DBMeal).filter(DBMeal.name == 'Gestrichenes Gericht').one()
    assert row.is_available is True


def test_past_date_reconcile_still_deletes(db, mensa):
    """Past dates should still be reconciled (delete unrated stale rows)."""
    # Use a future date that is NOT today, so reconcile=True should delete
    future = date(2030, 1, 1)
    # Add with the same date we'll reconcile
    _add(db, mensa, 'Gestrichenes Gericht', type='main', available=True)
    # Update the row's date to match the reconcile target
    row = db.query(DBMeal).filter(DBMeal.name == 'Gestrichenes Gericht').one()
    row.date = future
    db.commit()

    result = scraper._reconcile(db, mensa, future, keep_names=set(),
                                side_names=set(), prune_sides=True, reconcile=True)
    db.commit()

    assert _names(db, type='main') == set()


def test_extract_side_parts_keeps_dressing_sauce_ketchup(db):
    """Comma-listed dressings/sauces should now be rateable sides."""
    from scraper import _extract_side_parts

    # The Kebab row's sides
    desc = 'Tzatziki mit Joghurt, Country frites, Blattsalatmix, hausgemachtes Tomatendressing'
    assert set(_extract_side_parts(desc)) == {
        'Tzatziki mit Joghurt',
        'Country frites',
        'Blattsalatmix',
        'hausgemachtes Tomatendressing',
    }

    # Currywurst row's sides
    desc2 = 'Curryketchup Berliner Blume, Pommes frites, Farmermixsalat'
    assert set(_extract_side_parts(desc2)) == {
        'Curryketchup Berliner Blume',
        'Pommes frites',
        'Farmermixsalat',
    }

    # ZM Schnitzel row's sides
    desc3 = 'Paprikarahmsauce, Pommes frites, Pariser Karotten'
    assert set(_extract_side_parts(desc3)) == {
        'Paprikarahmsauce',
        'Pommes frites',
        'Pariser Karotten',
    }


def test_extract_side_parts_still_rejects_garnish(db):
    """Run-on garnish with 'mit' prefix should still be rejected."""
    from scraper import _extract_side_parts

    # "mit hausgemachte Vanillesauce" is a garnish, not a side
    desc = '4 Nuss Nougatbällchen, mit hausgemachte Vanillesauce'
    # The "mit" part is rejected, but "4 Nuss Nougatbällchen" is a valid side
    assert set(_extract_side_parts(desc)) == {'4 Nuss Nougatbällchen'}

    # "mit" in the middle of a side name is kept
    desc2 = 'Kartoffelsalat mit Ei und Gurke'
    assert _extract_side_parts(desc2) == ['Kartoffelsalat mit Ei und Gurke']

    # ketchup/sauce/sauce in a run-on garnish is rejected
    desc3 = 'Hähnchenbrustfilet mit cremiger Kräutersauce'
    assert _extract_side_parts(desc3) == ['Hähnchenbrustfilet mit cremiger Kräutersauce']
