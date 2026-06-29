from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func
import uvicorn

from database import SessionLocal, Meal as DBMeal, Rating as DBRating, Mensa as DBMensa, init_db
from scraper import scrape_menus

app = FastAPI(title="Mensa Rating API")

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

class RatingInput(BaseModel):
    meal_id: int
    rating: int
    comment: Optional[str] = None
    user_name: Optional[str] = None

class RatingOut(BaseModel):
    id: int
    rating: int
    comment: Optional[str]
    user_name: Optional[str]
    class Config:
        from_attributes = True

class MealOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    type: str
    mensa: str
    date: date
    avg_rating: float
    rating_count: int
    class Config:
        from_attributes = True

class RatingOutWithMeal(BaseModel):
    id: int
    rating: int
    comment: Optional[str]
    user_name: Optional[str]
    class Config:
        from_attributes = True

@app.on_event("startup")
def on_startup():
    init_db()
    scrape_menus()

@app.get("/menu/{menu_date}", response_model=list[MealOut])
def get_menu(menu_date: date, db: Session = Depends(get_db)):
    scrape_menus()
    results = db.query(
        DBMeal.id,
        DBMeal.name,
        DBMeal.description,
        DBMeal.type,
        DBMensa.name.label('mensa_name'),
        DBMeal.date,
        func.coalesce(func.avg(DBRating.rating), 0).label('avg_rating'),
        func.count(DBRating.id).label('rating_count'),
    ).join(DBMensa, DBMeal.mensa_id == DBMensa.id).outerjoin(
        DBRating, DBMeal.id == DBRating.meal_id
    ).filter(DBMeal.date == menu_date).group_by(
        DBMeal.id, DBMensa.name
    ).order_by(
        DBMensa.name, DBMeal.type
    ).all()

    out = []
    for r in results:
        out.append(MealOut(
            id=r.id,
            name=r.name,
            description=r.description,
            type=r.type,
            mensa=r.mensa_name,
            date=r.date,
            avg_rating=round(float(r.avg_rating), 1),
            rating_count=r.rating_count,
        ))
    return out

@app.post("/rate")
def rate_meal(data: RatingInput, db: Session = Depends(get_db)):
    rating = DBRating(**data.model_dump())
    db.add(rating)
    db.commit()
    db.refresh(rating)
    return rating

@app.get("/ratings/{meal_id}", response_model=list[RatingOutWithMeal])
def get_ratings(meal_id: int, db: Session = Depends(get_db)):
    return db.query(DBRating).filter(DBRating.meal_id == meal_id).order_by(
        DBRating.id.desc()
    ).all()

@app.get("/mensas")
def get_mensas(db: Session = Depends(get_db)):
    return [m.name for m in db.query(DBMensa).order_by(DBMensa.name).all()]

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
