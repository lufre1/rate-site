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
