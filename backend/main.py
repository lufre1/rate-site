from fastapi import FastAPI, Depends, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func
import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
import locale

from database import SessionLocal, Meal as DBMeal, Rating as DBRating, SideRating as DBSideRating, Mensa as DBMensa, init_db
from scraper import scrape_menus

app = FastAPI(
    title="Mensa Rating API",
    version="1.0",
    openapi_tags=[
        {"name": "Mensas", "description": "Operations on mensas"},
        {"name": "Meals", "description": "Operations on meals"},
        {"name": "Ratings", "description": "Operations on ratings"},
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_user_language(request: Request) -> str:
    """Determine user's preferred language"""
    # Check Accept-Language header
    accept_lang = request.headers.get("Accept-Language", "")
    if accept_lang:
        # Parse the header to get the first preferred language
        langs = [lang.split(';')[0].strip() for lang in accept_lang.split(',')]
        for lang in langs:
            if lang.startswith('de'):
                return 'de'
            elif lang.startswith('en'):
                return 'en'
    
    # Default to German
    return 'de'

def resolve_language(r, lang: str):
    """Pick name/description for the requested language.

    Falls back (EN -> DE -> legacy name) so a missing translation never causes a
    dish to disappear from the menu.
    """
    if lang == "en":
        name = r.name_en or r.name_de or r.name
        description = r.description_en or r.description_de or r.description
    else:  # "de" (default)
        name = r.name_de or r.name
        description = r.description_de or r.description
    if not name:
        name = r.name
        description = r.description
    return name, description

class RatingInput(BaseModel):
    rating: int
    comment: Optional[str] = None
    user_name: Optional[str] = None

class SideRatingInput(BaseModel):
    side_name: str
    rating: int
    comment: Optional[str] = None

import random

FAKES = {
    "adj": [
        "deep fried", "mildly", "super spicy", "grumpy", "burnt",
        "extra crispy", "soggy", "zesty", "tanzy", "slightly burnt",
        "aggressively", "underseasoned", "overcooked", "partially",
        "definitely", "questionably", "suspiciously", "mysteriously",
        "aggressively", "deeply", "mildly", "heavily",
    ],
    "noun": [
        "cucumber", "taco", "pickle", "burrito", "lasagna", "nachos",
        "gravy", "ketchup", "mayo", "mustard", "relish", "hummus",
        "guacamole", "salsa", "cheddar", "provolone", "brie",
        "pretzel", "bagel", "waffle", "pancake", "wonton",
    ],
    "name": [
        "Fred", "Steve", "Chad", "Gary", "Beth", "Larry", "Nancy",
        "Norm", "Doris", "Barry", "Gladys", "Walter", "Marjorie",
        "Evelyn", "Bertram", "Wilma", "Ethel", "Herbert",
    ],
}

def generate_funny_name() -> str:
    adj = random.choice(FAKES["adj"])
    noun = random.choice(FAKES["noun"])
    name = random.choice(FAKES["name"])
    if random.random() < 0.3:
        return f"{adj} {name}"
    return f"{adj} {noun} {name}"


class MealOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    tags: Optional[str]
    type: str
    mensa: str  # This should match the 'mensa_name' label in the query
    date: date
    avg_rating: float
    rating_count: int
    class Config:
        from_attributes = True

class RatingOut(BaseModel):
    id: int
    rating: int
    comment: Optional[str]
    user_name: Optional[str]
    class Config:
        from_attributes = True


class RatingOutWithDate(RatingOut):
    date: date
    meal_id: int

class SideRatingOut(BaseModel):
    side_name: str
    avg_rating: float
    rating_count: int

@app.on_event("startup")
def on_startup():
    init_db()
    scrape_menus()

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(scrape_menus, 'interval', hours=4, misfire_grace_time=3600)
    scheduler.start()

@app.get("/api/v1/meals/search")
def search_menu(q: str, past: bool = False, lang: str = "de", request: Request = None, db: Session = Depends(get_db)):
    from datetime import date as _date
    today = _date.today()
    qf = f"%{q}%"
    
    # Determine language preference
    if lang != "de" and lang != "en":
        lang = get_user_language(request) if request else "de"
    
    rating_agg = db.query(
        DBMeal.name.label('agg_name'),
        DBMeal.mensa_id.label('agg_mensa_id'),
        func.avg(DBRating.rating).label('avg_rating'),
        func.count(DBRating.id).label('rating_count'),
    ).join(DBRating, DBRating.meal_id == DBMeal.id
    ).group_by(DBMeal.name, DBMeal.mensa_id).subquery()

    results = db.query(
        DBMeal.id,
        DBMeal.name,
        DBMeal.name_de,
        DBMeal.name_en,
        DBMeal.description,
        DBMeal.description_de,
        DBMeal.description_en,
        DBMeal.tags,
        DBMeal.type,
        DBMensa.name.label('mensa_name'),
        DBMeal.date,
        func.coalesce(rating_agg.c.avg_rating, 0).label('avg_rating'),
        func.coalesce(rating_agg.c.rating_count, 0).label('rating_count'),
    ).join(DBMensa, DBMeal.mensa_id == DBMensa.id).outerjoin(
        rating_agg, (rating_agg.c.agg_name == DBMeal.name) & (rating_agg.c.agg_mensa_id == DBMeal.mensa_id)
    ).filter(
        DBMeal.name.ilike(qf) | DBMeal.description.ilike(qf)
    )
    if not past:
        results = results.filter(DBMeal.date >= today)
    results = results.order_by(
        DBMeal.date.desc(), DBMensa.name, DBMeal.type
    ).all()

    out = []
    # Guard against residual duplicate rows: one entry per (mensa, name, date).
    seen = set()

    for r in results:
        name, description = resolve_language(r, lang)
        if not name or not name.strip():
            continue

        key = (r.mensa_name, name, r.date)
        if key in seen:
            continue
        seen.add(key)

        out.append(MealOut(
            id=r.id,
            name=name,
            description=description,
            tags=r.tags,
            type=r.type,
            mensa=r.mensa_name,
            date=r.date,
            avg_rating=round(float(r.avg_rating), 1),
            rating_count=r.rating_count if r.rating_count else 0,
        ))

    return out

@app.get("/api/v1/meals", response_model=List[MealOut], tags=["Meals"])
def get_meals(date: date = Query(None), lang: str = "de", request: Request = None, db: Session = Depends(get_db)):
    # Determine language preference
    if lang != "de" and lang != "en":
        lang = get_user_language(request) if request else "de"
    
    rating_agg = db.query(
        DBMeal.name.label('agg_name'),
        DBMeal.mensa_id.label('agg_mensa_id'),
        func.avg(DBRating.rating).label('avg_rating'),
        func.count(DBRating.id).label('rating_count'),
    ).join(DBRating, DBRating.meal_id == DBMeal.id
    ).group_by(DBMeal.name, DBMeal.mensa_id).subquery()

    query = db.query(
        DBMeal.id,
        DBMeal.name,
        DBMeal.name_de,
        DBMeal.name_en,
        DBMeal.description,
        DBMeal.description_de,
        DBMeal.description_en,
        DBMeal.tags,
        DBMeal.type,
        DBMensa.name.label('mensa'),
        DBMeal.date,
        func.coalesce(rating_agg.c.avg_rating, 0).label('avg_rating'),
        func.coalesce(rating_agg.c.rating_count, 0).label('rating_count'),
    ).join(DBMensa, DBMeal.mensa_id == DBMensa.id).outerjoin(
        rating_agg, (rating_agg.c.agg_name == DBMeal.name) & (rating_agg.c.agg_mensa_id == DBMeal.mensa_id)
    )

    if date:
        query = query.filter(DBMeal.date == date)

    results = query.order_by(
        DBMensa.name, DBMeal.type
    ).all()

    out = []
    # Guard against residual duplicate rows: one entry per (mensa, name, date).
    seen = set()

    for r in results:
        name, description = resolve_language(r, lang)
        if not name or not name.strip():
            continue

        key = (r.mensa, name, r.date)
        if key in seen:
            continue
        seen.add(key)

        out.append(MealOut(
            id=r.id,
            name=name,
            description=description,
            tags=r.tags,
            type=r.type,
            mensa=r.mensa,
            date=r.date,
            avg_rating=round(float(r.avg_rating), 1),
            rating_count=r.rating_count if r.rating_count else 0,
        ))

    return out

@app.post("/api/v1/meals/{meal_id}/ratings", status_code=201, tags=["Ratings"])
def create_rating(meal_id: int, data: RatingInput, db: Session = Depends(get_db)):
    # Check if meal exists
    meal = db.query(DBMeal).filter(DBMeal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")

    rating = DBRating(
        meal_id=meal_id,
        rating=data.rating,
        comment=data.comment,
        user_name=generate_funny_name(),
    )
    db.add(rating)
    db.commit()
    db.refresh(rating)
    return rating

@app.get("/api/v1/meals/{meal_id}/ratings", response_model=List[RatingOutWithDate], tags=["Ratings"])
def get_ratings(meal_id: int, db: Session = Depends(get_db)):
    # Check if meal exists
    meal = db.query(DBMeal).filter(DBMeal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")

    rows = db.query(DBRating, DBMeal.date).join(
        DBMeal, DBRating.meal_id == DBMeal.id
    ).filter(
        DBMeal.name == meal.name,
        DBMeal.mensa_id == meal.mensa_id,
    ).order_by(DBMeal.date.desc(), DBRating.id.desc()).all()

    return [
        RatingOutWithDate(id=r.Rating.id, rating=r.Rating.rating, comment=r.Rating.comment,
                           user_name=r.Rating.user_name, date=r.date)
        for r in rows
    ]

@app.post("/api/v1/meals/{meal_id}/side-ratings", status_code=201, tags=["Ratings"])
def create_side_rating(meal_id: int, data: SideRatingInput, db: Session = Depends(get_db)):
    meal = db.query(DBMeal).filter(DBMeal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")
    if not data.side_name.strip():
        raise HTTPException(status_code=400, detail="side_name must not be empty")

    side_rating = DBSideRating(
        meal_id=meal_id,
        side_name=data.side_name,
        rating=data.rating,
        comment=data.comment,
        user_name=generate_funny_name(),
    )
    db.add(side_rating)
    db.commit()
    db.refresh(side_rating)
    return side_rating

@app.get("/api/v1/meals/{meal_id}/side-ratings", response_model=List[SideRatingOut], tags=["Ratings"])
def get_side_ratings(meal_id: int, db: Session = Depends(get_db)):
    meal = db.query(DBMeal).filter(DBMeal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")

    results = db.query(
        DBSideRating.side_name,
        func.coalesce(func.avg(DBSideRating.rating), 0).label('avg_rating'),
        func.count(DBSideRating.id).label('rating_count'),
    ).join(DBMeal, DBSideRating.meal_id == DBMeal.id
    ).filter(DBMeal.mensa_id == meal.mensa_id
    ).group_by(DBSideRating.side_name).all()

    return [
        SideRatingOut(side_name=r.side_name, avg_rating=round(float(r.avg_rating), 1), rating_count=r.rating_count)
        for r in results
    ]

@app.get("/api/v1/ratings/{rating_id}", response_model=RatingOut, tags=["Ratings"])
def get_rating(rating_id: int, db: Session = Depends(get_db)):
    rating = db.query(DBRating).filter(DBRating.id == rating_id).first()
    if not rating:
        raise HTTPException(status_code=404, detail="Rating not found")
    return rating

@app.get("/api/v1/mensas")
def get_mensas(db: Session = Depends(get_db)):
    return [m.name for m in db.query(DBMensa).order_by(DBMensa.name).all()]

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)