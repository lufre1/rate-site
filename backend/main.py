from fastapi import FastAPI, Depends, Query, HTTPException, Request, File, Form, UploadFile, Response, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from sqlalchemy import func
import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
import locale
import os
import shutil
import uuid
import re
from datetime import datetime

from database import Meal as DBMeal, Rating as DBRating, SideRating as DBSideRating, Mensa as DBMensa, User as DBUser, AuthToken as DBAuthToken, CommentVote as DBCommentVote, init_db, get_db
import auth
from scraper import scrape_menus, scrape_today

app = FastAPI(
    title="Mensa Rating API",
    version="1.0",
    openapi_tags=[
        {"name": "Mensas", "description": "Operations on mensas"},
        {"name": "Meals", "description": "Operations on meals"},
        {"name": "Ratings", "description": "Operations on ratings"},
        {"name": "Auth", "description": "Accounts and sessions"},
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Upload directory
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/app/uploads")

def ensure_upload_dir():
    """Ensure upload directory exists"""
    os.makedirs(UPLOAD_DIR, exist_ok=True)

# Must exist before the StaticFiles mount below (module import time), not just
# at app startup -- otherwise running outside the docker-compose volume mount
# (e.g. local dev, tests) crashes on import.
ensure_upload_dir()

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
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = None
    user_name: Optional[str] = None

class SideRatingInput(BaseModel):
    side_name: str
    rating: int = Field(ge=1, le=5)
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


def rating_identity(user: Optional[DBUser]):
    """(user_name, user_id) to stamp on a new rating.

    Signed in -> the real username or display_name if set. Anonymous -> a generated
    funny name, exactly as before accounts existed. Every rating-creation route goes
    through here so main dishes and side dishes can't drift apart.
    """
    if user:
        return (user.display_name or user.username), user.id
    return generate_funny_name(), None


class MealOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    tags: Optional[str]
    type: str
    mensa: str
    date: date
    avg_rating: float
    rating_count: int
    is_available: bool
    class Config:
        from_attributes = True

class RatingOut(BaseModel):
    id: int
    rating: int
    comment: Optional[str]
    user_name: Optional[str]
    photo_url: Optional[str] = None
    class Config:
        from_attributes = True


class RatingOutWithDate(RatingOut):
    date: date
    meal_id: int

class RatingBadgeSection(BaseModel):
    ratings: List[RatingOutWithDate]
    avg: float
    count: int

class CommentDisplay(BaseModel):
    id: int
    rating: int
    comment: str
    user_name: Optional[str]
    date: date
    created_at: datetime
    photo_url: Optional[str] = None
    is_recent: bool = False
    score: int = 0
    vote_direction: Optional[int] = None

    class Config:
        from_attributes = True

class PhotoOut(BaseModel):
    id: int
    photo_url: str
    rating: int
    user_name: Optional[str]
    class Config:
        from_attributes = True

class CredentialsInput(BaseModel):
    username: str
    password: str

class TokenOut(BaseModel):
    token: str
    username: str

class MeOut(BaseModel):
    username: str
    display_name: Optional[str] = None
    rating_count: int
    created_at: Optional[datetime] = None

class MyRatingOut(BaseModel):
    id: int
    meal_id: int
    rating: int
    comment: Optional[str] = None
    photo_url: Optional[str] = None
    meal_name: str
    mensa: str
    date: date
    created_at: Optional[datetime] = None

class RatingUpdate(BaseModel):
    rating: Optional[int] = Field(None, ge=1, le=5)
    comment: Optional[str] = None

class SideRatingOut(BaseModel):
    side_name: str
    avg_rating: float
    rating_count: int
    recent_avg: float = 0
    recent_count: int = 0

@app.on_event("startup")
def on_startup():
    init_db()
    ensure_upload_dir()
    scrape_menus()

    scheduler = BackgroundScheduler(daemon=True, timezone="Europe/Berlin")

    # Precise lunch-time pre-open updates (mensas open at 11:30, dishes change right before)
    scheduler.add_job(scrape_today, 'cron', hour=11, minute=0, misfire_grace_time=300)
    scheduler.add_job(scrape_today, 'cron', hour=11, minute=15, misfire_grace_time=300)
    scheduler.add_job(scrape_today, 'cron', hour=11, minute=30, misfire_grace_time=300)

    # Background fallback: full 7-day refresh through the day
    scheduler.add_job(scrape_menus, 'interval', hours=4, misfire_grace_time=3600)
    scheduler.start()

@app.get("/api/v1/meals/search")
def search_menu(q: str, past: bool = False, lang: str = "de", request: Request = None, db: Session = Depends(get_db)):
    from datetime import date as _date
    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
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
        DBMeal.is_available,
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
            is_available=r.is_available,
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
        DBMeal.is_available,
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
            is_available=r.is_available,
        ))

    return out

@app.post("/api/v1/meals/{meal_id}/ratings", status_code=201, tags=["Ratings"])
def create_rating(meal_id: int, data: RatingInput, db: Session = Depends(get_db), user: Optional[DBUser] = Depends(auth.optional_user)):
    # Check if meal exists
    meal = db.query(DBMeal).filter(DBMeal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")

    user_name, user_id = rating_identity(user)
    rating = DBRating(
        meal_id=meal_id,
        rating=data.rating,
        comment=data.comment,
        user_name=user_name,
        user_id=user_id,
    )
    db.add(rating)
    db.commit()
    db.refresh(rating)
    return rating


@app.post("/api/v1/meals/{meal_id}/ratings-with-photo", status_code=201, tags=["Ratings"])
def create_rating_with_photo(meal_id: int, rating: int = Form(..., ge=1, le=5), comment: Optional[str] = Form(None), photo: Optional[UploadFile] = File(None), db: Session = Depends(get_db), user: Optional[DBUser] = Depends(auth.optional_user)):
    """Create a rating with optional photo upload"""
    # Check if meal exists
    meal = db.query(DBMeal).filter(DBMeal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")

    # Validate photo if provided
    photo_url = None
    if photo is not None:
        # Check file extension
        valid_extensions = {'.jpg', '.jpeg', '.png', '.webp'}
        file_ext = os.path.splitext(photo.filename)[1].lower()
        if file_ext not in valid_extensions:
            raise HTTPException(status_code=400, detail="Invalid file type. Only JPG, PNG, and WebP images are allowed")
        
        # Check content type
        content_type = photo.content_type
        if content_type not in ['image/jpeg', 'image/png', 'image/webp']:
            raise HTTPException(status_code=400, detail="Invalid file type. Only JPG, PNG, and WebP images are allowed")
        
        # Check file size (max 5MB)
        file_size = 0
        content = photo.file.read()
        file_size = len(content)
        photo.file.seek(0)
        
        if file_size > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File size exceeds 5MB limit")
        
        # Generate unique filename
        original_name = os.path.splitext(photo.filename)[0]
        safe_name = "".join(c for c in original_name if c.isalnum() or c in " -_")
        new_filename = f"{safe_name}_{uuid.uuid4().hex[:8]}{file_ext}"
        photo_path = os.path.join(UPLOAD_DIR, new_filename)
        
        # Save file
        with open(photo_path, 'wb') as f:
            shutil.copyfileobj(photo.file, f)
        
        photo_url = f"/uploads/{new_filename}"

    user_name, user_id = rating_identity(user)
    rating_obj = DBRating(
        meal_id=meal_id,
        rating=rating,
        comment=comment,
        user_name=user_name,
        user_id=user_id,
        photo_url=photo_url,
    )
    db.add(rating_obj)
    db.commit()
    db.refresh(rating_obj)
    return rating_obj


@app.get("/api/v1/meals/{meal_id}/ratings", response_model=List[RatingOutWithDate], tags=["Ratings"])
def get_ratings(meal_id: int, db: Session = Depends(get_db)):
    """Get ratings for all instances of this dish across all dates."""
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
        RatingOutWithDate(id=r.Rating.id, meal_id=r.Rating.meal_id, rating=r.Rating.rating,
                           comment=r.Rating.comment, user_name=r.Rating.user_name, date=r.date,
                           photo_url=r.Rating.photo_url)
        for r in rows
    ]


@app.get("/api/v1/meals/{meal_id}/ratings-breakdown", response_model=dict, tags=["Ratings"])
def get_ratings_breakdown(meal_id: int, db: Session = Depends(get_db), voter_id: Optional[str] = Header(None, alias="X-Voter-Id")):
    """Get detailed rating breakdown with recent vs overall sections and comments."""
    # Check if meal exists
    meal = db.query(DBMeal).filter(DBMeal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")

    today = datetime.now(ZoneInfo("Europe/Berlin")).date()

    # Find all meal instances with same (name, mensa_id) combination
    all_meals = db.query(DBMeal).filter(
        DBMeal.name == meal.name,
        DBMeal.mensa_id == meal.mensa_id
    ).all()

    # Recent = today's meal only (by date)
    recent_meal_ids = [m.id for m in all_meals if m.date == today]
    # Overall = all meals (recent + old)
    all_meal_ids = [m.id for m in all_meals]

    # Get recent ratings with full details
    recent_ratings = db.query(DBRating).join(
        DBMeal, DBRating.meal_id == DBMeal.id
    ).filter(
        DBMeal.id.in_(recent_meal_ids)
    ).order_by(DBRating.created_at.desc(), DBRating.id.desc()).all()

    # Calculate recent average and count
    recent_avg = 0
    if recent_ratings:
        recent_avg = round(float(sum(r.rating for r in recent_ratings)) / len(recent_ratings), 1)

    # Get overall ratings with average
    overall_result = db.query(
        func.coalesce(func.avg(DBRating.rating), 0).label('avg_rating'),
        func.count(DBRating.id).label('rating_count')
    ).join(DBMeal, DBRating.meal_id == DBMeal.id).filter(
        DBMeal.id.in_(all_meal_ids)
    ).first()

    overall_avg = round(float(overall_result.avg_rating), 1) if overall_result else 0
    overall_count = overall_result.rating_count if overall_result else 0

    # Get comments for display (most recent 15 across all ratings for this dish)
    comments_query = db.query(DBRating, DBMeal.date, DBRating.created_at).join(
        DBMeal, DBRating.meal_id == DBMeal.id
    ).filter(
        DBMeal.id.in_(all_meal_ids),
        DBRating.comment.isnot(None)
    ).order_by(DBRating.created_at.desc()).limit(15).all()

    comment_ids = [r.Rating.id for r in comments_query]
    
    comment_scores = {}
    if comment_ids:
        score_results = db.query(
            DBCommentVote.rating_id,
            func.sum(DBCommentVote.direction).label('score')
        ).filter(
            DBCommentVote.rating_id.in_(comment_ids)
        ).group_by(DBCommentVote.rating_id).all()
        comment_scores = {r.rating_id: r.score if r.score is not None else 0 for r in score_results}
    
    viewer_votes = {}
    if voter_id and comment_ids:
        vote_results = db.query(
            DBCommentVote.rating_id,
            DBCommentVote.direction
        ).filter(
            DBCommentVote.rating_id.in_(comment_ids),
            DBCommentVote.voter_id == voter_id
        ).all()
        viewer_votes = {r.rating_id: r.direction for r in vote_results}

    comments = [
        CommentDisplay(
            id=r.Rating.id,
            rating=r.Rating.rating,
            comment=r.Rating.comment,
            user_name=r.Rating.user_name,
            date=r.date,
            created_at=r.Rating.created_at,
            photo_url=r.Rating.photo_url,
            score=comment_scores.get(r.Rating.id, 0),
            vote_direction=viewer_votes.get(r.Rating.id)
        )
        for r in comments_query
    ]

    return {
        "recent": {
            "ratings": [
                RatingOutWithDate(
                    id=r.id,
                    rating=r.rating,
                    comment=r.comment,
                    user_name=r.user_name,
                    photo_url=r.photo_url,
                    date=meal.date,
                    meal_id=r.meal_id
                )
                for r in recent_ratings
            ],
            "avg": recent_avg,
            "count": len(recent_ratings)
        },
        "overall": {
            "avg": overall_avg,
            "count": overall_count
        },
        "comments": [
            {
                "id": c.id,
                "rating": c.rating,
                "comment": c.comment,
                "user_name": c.user_name,
                "date": c.date.isoformat(),
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "photo_url": c.photo_url,
                "is_recent": c.date == today,
                "score": c.score,
                "vote_direction": c.vote_direction
            }
            for c in comments
        ]
    }

@app.post("/api/v1/meals/{meal_id}/side-ratings", status_code=201, tags=["Ratings"])
def create_side_rating(meal_id: int, data: SideRatingInput, db: Session = Depends(get_db), user: Optional[DBUser] = Depends(auth.optional_user)):
    meal = db.query(DBMeal).filter(DBMeal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")
    if not data.side_name.strip():
        raise HTTPException(status_code=400, detail="side_name must not be empty")

    user_name, user_id = rating_identity(user)
    side_rating = DBSideRating(
        meal_id=meal_id,
        side_name=data.side_name,
        rating=data.rating,
        comment=data.comment,
        user_name=user_name,
        user_id=user_id,
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

    today = datetime.now(ZoneInfo("Europe/Berlin")).date()

    # Find all meal instances with same (name, mensa_id) combination
    all_meals = db.query(DBMeal).filter(
        DBMeal.name == meal.name,
        DBMeal.mensa_id == meal.mensa_id
    ).all()

    # Recent = today's meal only (by date)
    recent_meal_ids = [m.id for m in all_meals if m.date == today]
    # Overall = all meals (recent + old)
    all_meal_ids = [m.id for m in all_meals]

    # Get side ratings for overall (all meals)
    overall_results = db.query(
        DBSideRating.side_name,
        func.coalesce(func.avg(DBSideRating.rating), 0).label('avg_rating'),
        func.count(DBSideRating.id).label('rating_count'),
    ).join(DBMeal, DBSideRating.meal_id == DBMeal.id
    ).filter(DBMeal.id.in_(all_meal_ids)
    ).group_by(DBSideRating.side_name).all()

    # Get side ratings for recent (today only)
    recent_results = db.query(
        DBSideRating.side_name,
        func.coalesce(func.avg(DBSideRating.rating), 0).label('recent_avg_rating'),
        func.count(DBSideRating.id).label('recent_rating_count'),
    ).join(DBMeal, DBSideRating.meal_id == DBMeal.id
    ).filter(DBMeal.id.in_(recent_meal_ids)
    ).group_by(DBSideRating.side_name).all()
# Merge recent and overall data
    recent_map = {r.side_name: r for r in recent_results}
    
    side_ratings_out = []
    for r in overall_results:
        if r.side_name in recent_map:
            recent = recent_map[r.side_name]
            side_ratings_out.append(SideRatingOut(
                side_name=r.side_name,
                avg_rating=round(float(r.avg_rating), 1),
                rating_count=r.rating_count,
                recent_avg=round(float(recent.recent_avg_rating), 1),
                recent_count=recent.recent_rating_count
            ))
        else:
            side_ratings_out.append(SideRatingOut(
                side_name=r.side_name,
                avg_rating=round(float(r.avg_rating), 1),
                rating_count=r.rating_count,
                recent_avg=0,
                recent_count=0
            ))
    
    return side_ratings_out

@app.get("/api/v1/ratings/{rating_id}", response_model=RatingOut, tags=["Ratings"])
def get_rating(rating_id: int, db: Session = Depends(get_db)):
    rating = db.query(DBRating).filter(DBRating.id == rating_id).first()
    if not rating:
        raise HTTPException(status_code=404, detail="Rating not found")
    return rating


@app.patch("/api/v1/ratings/{rating_id}/comment", response_model=RatingOut, tags=["Ratings"])
def update_rating_comment(rating_id: int, data: dict, db: Session = Depends(get_db), user: Optional[DBUser] = Depends(auth.optional_user)):
    """Set or update the comment on an existing rating.

    Predates accounts and stays open for anonymous rows (nobody owns them), but a
    rating that belongs to an account may only be edited by that account.
    """
    rating = db.query(DBRating).filter(DBRating.id == rating_id).first()
    if not rating:
        raise HTTPException(status_code=404, detail="Rating not found")
    if rating.user_id is not None and (user is None or user.id != rating.user_id):
        raise HTTPException(status_code=403, detail="Not your rating")
    comment = data.get("comment")
    if not isinstance(comment, str):
        raise HTTPException(status_code=400, detail="comment must be a string")
    rating.comment = comment
    db.add(rating)
    db.commit()
    db.refresh(rating)
    return rating

@app.get("/api/v1/meals/{meal_id}/photos", response_model=List[dict], tags=["Ratings"])
def get_photos_for_meal(meal_id: int, db: Session = Depends(get_db)):
    """Get all photos for a specific meal"""
    meal = db.query(DBMeal).filter(DBMeal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")

    photos = db.query(DBRating).filter(DBRating.meal_id == meal_id).filter(DBRating.photo_url.isnot(None)).all()
    # Rating rows have no timestamp column; use the meal's own date instead,
    # consistent with how /ratings reports a review's date.
    return [{"id": p.id, "photo_url": p.photo_url, "rating": p.rating, "user_name": p.user_name, "date": meal.date.isoformat()} for p in photos]


@app.put("/api/v1/ratings/{rating_id}/vote")
def vote_on_comment(rating_id: int, data: dict, db: Session = Depends(get_db), voter_id: Optional[str] = Header(None, alias="X-Voter-Id"), authorization: Optional[str] = Header(None)):
    """Vote on a comment (upvote or downvote). Toggle: same direction removes vote, opposite switches."""
    if not voter_id:
        raise HTTPException(status_code=400, detail="X-Voter-Id header required")
    
    rating = db.query(DBRating).filter(DBRating.id == rating_id).first()
    if not rating:
        raise HTTPException(status_code=404, detail="Rating not found")
    if not rating.comment:
        raise HTTPException(status_code=400, detail="Rating has no comment")
    
    direction = data.get("direction")
    if direction not in (1, -1):
        raise HTTPException(status_code=400, detail="direction must be 1 (up) or -1 (down)")
    
    user = auth.optional_user(authorization)
    
    existing = db.query(DBCommentVote).filter(
        DBCommentVote.rating_id == rating_id,
        DBCommentVote.voter_id == voter_id
    ).first()
    
    if existing:
        if existing.direction == direction:
            db.delete(existing)
            db.commit()
            return {"direction": None, "score": get_comment_score(rating_id, db)}
        else:
            existing.direction = direction
            db.add(existing)
            db.commit()
            db.refresh(existing)
            return {"direction": direction, "score": get_comment_score(rating_id, db)}
    else:
        vote = DBCommentVote(
            rating_id=rating_id,
            voter_id=voter_id,
            user_id=user.id if user else None,
            direction=direction
        )
        db.add(vote)
        db.commit()
        db.refresh(vote)
        return {"direction": direction, "score": get_comment_score(rating_id, db)}


@app.get("/api/v1/ratings/{rating_id}/vote")
def get_vote_status(rating_id: int, db: Session = Depends(get_db), voter_id: Optional[str] = Header(None, alias="X-Voter-Id")):
    """Get current vote status for a comment, including viewer's vote and total score."""
    if not voter_id:
        raise HTTPException(status_code=400, detail="X-Voter-Id header required")
    
    rating = db.query(DBRating).filter(DBRating.id == rating_id).first()
    if not rating:
        raise HTTPException(status_code=404, detail="Rating not found")
    if not rating.comment:
        raise HTTPException(status_code=400, detail="Rating has no comment")
    
    score = get_comment_score(rating_id, db)
    
    vote = db.query(DBCommentVote).filter(
        DBCommentVote.rating_id == rating_id,
        DBCommentVote.voter_id == voter_id
    ).first()
    
    return {
        "direction": vote.direction if vote else None,
        "score": score
    }


def get_comment_score(rating_id: int, db: Session) -> int:
    result = db.query(func.sum(DBCommentVote.direction)).filter(
        DBCommentVote.rating_id == rating_id
    ).scalar()
    return result if result is not None else 0


@app.get("/uploads/{filename}")
def serve_photo(filename: str):
    """Serve uploaded photos"""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Photo not found")
    
    content_type = "image/jpeg"
    if filename.lower().endswith('.png'):
        content_type = "image/png"
    elif filename.lower().endswith('.webp'):
        content_type = "image/webp"
    
    return FileResponse(file_path, media_type=content_type)

# ---------------------------------------------------------------- Accounts

@app.post("/api/v1/auth/register", response_model=TokenOut, status_code=201, tags=["Auth"])
def register(data: CredentialsInput, db: Session = Depends(get_db)):
    username = data.username.strip()
    auth.validate_credentials(username, data.password)
    if db.query(DBUser).filter(func.lower(DBUser.username) == username.lower()).first():
        raise HTTPException(status_code=409, detail="Username already taken")

    user = DBUser(username=username, password_hash=auth.hash_password(data.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenOut(token=auth.issue_token(db, user), username=user.username)


@app.post("/api/v1/auth/login", response_model=TokenOut, tags=["Auth"])
def login(data: CredentialsInput, db: Session = Depends(get_db)):
    username = data.username.strip()
    user = db.query(DBUser).filter(func.lower(DBUser.username) == username.lower()).first()
    # Same message and same code for "no such user" and "wrong password" so this
    # endpoint can't be used to enumerate which usernames exist.
    if not user or not auth.verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return TokenOut(token=auth.issue_token(db, user), username=user.username)


@app.post("/api/v1/auth/logout", status_code=204, tags=["Auth"])
def logout(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    token = auth.token_from_header(authorization)
    if token:
        db.query(DBAuthToken).filter(DBAuthToken.token == token).delete()
        db.commit()
    return Response(status_code=204)


@app.get("/api/v1/me", response_model=MeOut, tags=["Auth"])
def get_me(user: DBUser = Depends(auth.current_user), db: Session = Depends(get_db)):
    count = db.query(func.count(DBRating.id)).filter(DBRating.user_id == user.id).scalar()
    return MeOut(username=user.username, display_name=user.display_name, rating_count=count or 0, created_at=user.created_at)


@app.patch("/api/v1/me/display-name", response_model=MeOut, tags=["Auth"])
def set_display_name(data: dict, user: DBUser = Depends(auth.current_user), db: Session = Depends(get_db)):
    """Set or clear the display name for the current user."""
    display_name = data.get("display_name")
    if display_name is not None:
        if not isinstance(display_name, str):
            raise HTTPException(status_code=400, detail="display_name must be a string or null")
        display_name = display_name.strip()
        if len(display_name) == 0:
            display_name = None
        elif len(display_name) > 30:
            raise HTTPException(status_code=400, detail="display_name must be at most 30 characters")
        elif not re.match(r"^[A-Za-z0-9 _-]+$", display_name):
            raise HTTPException(status_code=400, detail="display_name must contain only letters, digits, spaces, underscore, or hyphen")
    user.display_name = display_name
    db.add(user)
    db.commit()
    db.refresh(user)
    count = db.query(func.count(DBRating.id)).filter(DBRating.user_id == user.id).scalar()
    return MeOut(username=user.username, display_name=user.display_name, rating_count=count or 0, created_at=user.created_at)


@app.get("/api/v1/me/ratings", response_model=List[MyRatingOut], tags=["Auth"])
def get_my_ratings(
    min_rating: int = Query(1, ge=1, le=5),
    sort: str = Query("date", pattern="^(date|rating)$"),
    lang: str = "de",
    user: DBUser = Depends(auth.current_user),
    db: Session = Depends(get_db),
):
    """The caller's own ratings.

    Also backs the "favourites" view -- that is just this endpoint called with
    ?min_rating=4&sort=rating, so there is no separate favourites table to keep
    in sync with what people actually rated.
    """
    if lang not in ("de", "en"):
        lang = "de"

    rows = db.query(DBRating, DBMeal, DBMensa.name.label("mensa_name")).join(
        DBMeal, DBRating.meal_id == DBMeal.id
    ).join(
        DBMensa, DBMeal.mensa_id == DBMensa.id
    ).filter(
        DBRating.user_id == user.id,
        DBRating.rating >= min_rating,
    )

    if sort == "rating":
        rows = rows.order_by(DBRating.rating.desc(), DBMeal.date.desc())
    else:
        rows = rows.order_by(DBMeal.date.desc(), DBRating.id.desc())

    out = []
    for r in rows.all():
        name, _ = resolve_language(r.Meal, lang)
        out.append(MyRatingOut(
            id=r.Rating.id,
            meal_id=r.Rating.meal_id,
            rating=r.Rating.rating,
            comment=r.Rating.comment,
            photo_url=r.Rating.photo_url,
            meal_name=name or r.Meal.name,
            mensa=r.mensa_name,
            date=r.Meal.date,
            created_at=r.Rating.created_at,
        ))
    return out


def owned_rating(rating_id: int, user: DBUser, db: Session) -> DBRating:
    """Fetch a rating, or fail unless it belongs to this user.

    Anonymous rows (user_id IS NULL) match no account, so they can never be
    edited or deleted through the authenticated routes.
    """
    rating = db.query(DBRating).filter(DBRating.id == rating_id).first()
    if not rating:
        raise HTTPException(status_code=404, detail="Rating not found")
    if rating.user_id is None or rating.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your rating")
    return rating


@app.patch("/api/v1/ratings/{rating_id}", response_model=RatingOut, tags=["Ratings"])
def update_own_rating(
    rating_id: int,
    data: RatingUpdate,
    user: DBUser = Depends(auth.current_user),
    db: Session = Depends(get_db),
):
    rating = owned_rating(rating_id, user, db)
    if data.rating is not None:
        rating.rating = data.rating
    if data.comment is not None:
        rating.comment = data.comment
    db.add(rating)
    db.commit()
    db.refresh(rating)
    return rating


@app.delete("/api/v1/ratings/{rating_id}", status_code=204, tags=["Ratings"])
def delete_own_rating(
    rating_id: int,
    user: DBUser = Depends(auth.current_user),
    db: Session = Depends(get_db),
):
    rating = owned_rating(rating_id, user, db)
    # Drop the attached photo too -- otherwise deleted ratings leave their
    # uploads on disk forever. basename() so a crafted photo_url can't escape
    # the upload directory.
    if rating.photo_url:
        photo_path = os.path.join(UPLOAD_DIR, os.path.basename(rating.photo_url))
        if os.path.isfile(photo_path):
            os.remove(photo_path)
    db.delete(rating)
    db.commit()
    return Response(status_code=204)


@app.get("/api/v1/mensas")
def get_mensas(db: Session = Depends(get_db)):
    return [m.name for m in db.query(DBMensa).order_by(DBMensa.name).all()]

# Mount static files for photos
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)