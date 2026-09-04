from fastapi import FastAPI, Depends, Query, HTTPException, Request, File, Form, UploadFile, Response, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
import uvicorn
from anyio import to_thread
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
import locale
import os
import uuid
import re
from datetime import datetime

import logging
import time
import uuid
from sqlalchemy.exc import OperationalError
from starlette.responses import JSONResponse

from logging_config import configure_logging, request_id_var

configure_logging()
log = logging.getLogger("api")

from database import Meal as DBMeal, Rating as DBRating, SideRating as DBSideRating, Mensa as DBMensa, User as DBUser, AuthToken as DBAuthToken, CommentVote as DBCommentVote, PhotoVote as DBPhotoVote, init_db, get_db, POOL_CAPACITY
import auth
from images import strip_metadata
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

# Every route below is a sync `def`, so it runs on the anyio worker thread pool.
# ContextVars propagate into those threads, so request_id_var is visible from
# route code and from anything it calls.
@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:8]
    token = request_id_var.set(rid)
    started = time.monotonic()
    try:
        response = await call_next(request)
        ms = (time.monotonic() - started) * 1000
        # The container healthcheck hits /api/v1/health every 30s; do not log
        # 2880 lines a day of it. Slow or failing requests go to WARNING.
        #
        # This must happen BEFORE the reset below -- logging after
        # request_id_var.reset(token) emits `rid=-` on every line, which is
        # exactly what the first version of this middleware did.
        if request.url.path != "/api/v1/health":
            level = (logging.WARNING if (response.status_code >= 500 or ms > 1000)
                     else logging.INFO)
            log.log(level, "%s %s -> %d in %.0fms", request.method,
                    request.url.path, response.status_code, ms)
        response.headers["X-Request-Id"] = rid
        return response
    finally:
        request_id_var.reset(token)


@app.exception_handler(OperationalError)
async def db_unavailable(request: Request, exc):
    """Pairs with pool_pre_ping in database.py: a genuinely unreachable database
    is a 503 the client can retry, not an opaque 500."""
    log.error("database unavailable on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=503, content={"detail": "database unavailable"})


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    """Nothing in this file had a single try/except before 2026-09-01, so any
    unexpected error produced a bare 500 with the traceback going nowhere."""
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "internal server error", "request_id": request_id_var.get()},
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

# Mirrored by COMMENT_MAX in frontend/src/App.js, which caps the textarea so
# the limit is visible while typing rather than a rejection afterwards. The
# column is Text, so raising this needs no migration -- and lowering it would
# not invalidate rows already stored above it.
COMMENT_MAX_LENGTH = 1000


class RatingInput(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=COMMENT_MAX_LENGTH)
    user_name: Optional[str] = None

class SideRatingInput(BaseModel):
    side_name: str
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=COMMENT_MAX_LENGTH)

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
    # Optional: an entry may be a photo with no text at all. Those are shown so
    # their picture can be voted on.
    comment: Optional[str] = None
    user_name: Optional[str]
    date: date
    created_at: datetime
    photo_url: Optional[str] = None
    is_recent: bool = False
    score: int = 0
    vote_direction: Optional[int] = None
    photo_score: int = 0
    photo_vote_direction: Optional[int] = None

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
    comment: Optional[str] = Field(None, max_length=COMMENT_MAX_LENGTH)

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

    # Assert, do not lower. The worker thread pool also runs the cleanup of the
    # sync get_db dependency, so capping it below the connection pool deadlocks
    # connection release under load -- see the long note in database.py. This
    # just fails loudly if someone ever tightens it below what the pool can
    # serve.
    tokens = to_thread.current_default_thread_limiter().total_tokens
    if tokens < POOL_CAPACITY:
        raise RuntimeError(
            f"anyio thread limiter ({tokens}) is below the connection pool "
            f"capacity ({POOL_CAPACITY}); connection release would deadlock"
        )
    log.info("thread limiter %s vs pool capacity %d", tokens, POOL_CAPACITY)

    # One scrape at a time, ever. APScheduler's max_instances only stops a job
    # overlapping *itself*, and the default executor has 10 threads -- so the
    # 11:30 cron and the 4-hourly refresh used to be able to run concurrently,
    # at lunch peak, each holding a connection. coalesce collapses a backlog of
    # missed runs into one instead of firing them back to back.
    scheduler = BackgroundScheduler(
        daemon=True,
        timezone="Europe/Berlin",
        executors={'default': ThreadPoolExecutor(1)},
        job_defaults={'coalesce': True, 'max_instances': 1},
    )

    # Precise lunch-time pre-open updates (mensas open at 11:30, dishes change right before)
    scheduler.add_job(scrape_today, 'cron', hour=11, minute=0, misfire_grace_time=300)
    scheduler.add_job(scrape_today, 'cron', hour=11, minute=15, misfire_grace_time=300)
    scheduler.add_job(scrape_today, 'cron', hour=11, minute=30, misfire_grace_time=300)

    # Background fallback: full 7-day refresh through the day
    scheduler.add_job(scrape_menus, 'interval', hours=4, misfire_grace_time=3600)

    # The first scrape is a scheduled job, not a blocking startup call. It used
    # to run inline here, so uvicorn served nothing until up to 14 fetches at a
    # 10s timeout had finished -- which is what `start_period: 180s` on the
    # healthcheck was covering for. Going through the scheduler also means it
    # shares the single-threaded executor above and cannot overlap a cron run.
    scheduler.add_job(scrape_menus, 'date', run_date=datetime.now() + timedelta(seconds=15))

    scheduler.start()

@app.get("/api/v1/health", include_in_schema=False)
def health():
    """Liveness only -- deliberately does NOT touch the database.

    The container healthcheck uses this endpoint, so a Postgres blip cannot get
    the backend killed at the moment when restarting the backend is exactly the
    thing that cannot help. Readiness lives at /api/v1/health/db.
    """
    return {"status": "ok"}


@app.get("/api/v1/health/db", include_in_schema=False)
def health_db(db: Session = Depends(get_db)):
    """Readiness. ops/check-host.sh reports on this; nothing restarts on it."""
    from sqlalchemy import text as _text
    db.execute(_text("SELECT 1"))
    return {"status": "ok"}


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
        # Every language column, regardless of `lang`. `name`/`description` hold
        # the German text (scraper.py sets name and name_de to the same string),
        # so matching only those made an English query return nothing while the
        # results were being rendered from name_en. Searching all of them also
        # covers the common case of typing a German dish name on the English UI.
        DBMeal.name.ilike(qf) | DBMeal.description.ilike(qf)
        | DBMeal.name_de.ilike(qf) | DBMeal.description_de.ilike(qf)
        | DBMeal.name_en.ilike(qf) | DBMeal.description_en.ilike(qf)
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
def create_rating_with_photo(meal_id: int, rating: int = Form(..., ge=1, le=5), comment: Optional[str] = Form(None, max_length=COMMENT_MAX_LENGTH), photo: Optional[UploadFile] = File(None), db: Session = Depends(get_db), user: Optional[DBUser] = Depends(auth.optional_user)):
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
        content = photo.file.read()
        file_size = len(content)

        if file_size > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File size exceeds 5MB limit")

        # The uploader's own file name used to be kept as a prefix, which put
        # it in a public, permanently cached URL -- a camera name like
        # IMG_2109 says nothing, but a name does. Pure random now.
        new_filename = f"{uuid.uuid4().hex}{file_ext}"
        photo_path = os.path.join(UPLOAD_DIR, new_filename)

        # Photos are world-readable and cached for 30 days, so EXIF/XMP left
        # in the file is published: device model, capture time, and GPS if the
        # camera recorded it. strip_metadata copies the pixel data through
        # untouched -- see backend/images.py.
        with open(photo_path, 'wb') as f:
            f.write(strip_metadata(content, file_ext))

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


def _top_photo_rating(meal_ids, db: Session):
    """The rating whose photo represents a dish.

    Ranked by photo votes only -- comment votes deliberately have no say. Ties
    (including the all-zero case, which is every photo until someone votes) go
    to the oldest photo, so the dish picture does not churn on every upload.
    """
    score = func.coalesce(func.sum(DBPhotoVote.direction), 0).label('total_score')
    return db.query(
        DBRating.id.label('rating_id'),
        DBRating.photo_url,
        score
    ).join(
        DBMeal, DBRating.meal_id == DBMeal.id
    ).outerjoin(
        DBPhotoVote, DBPhotoVote.rating_id == DBRating.id
    ).filter(
        DBMeal.id.in_(meal_ids),
        DBRating.photo_url.isnot(None)
    ).group_by(
        DBRating.id, DBRating.photo_url
    ).order_by(
        score.desc(), DBRating.created_at.asc(), DBRating.id.asc()
    ).first()


def _top_photos_by_dish(dish_keys, db: Session):
    """Top photo per dish, resolved for many dishes in one query.

    Same ranking as _top_photo_rating -- photo votes only, ties to the oldest
    photo -- but keyed by (name, mensa_id) so a whole page of cards costs one
    query instead of one per card.

    The ORDER BY is what makes this deterministic: rows arrive best-first, so the
    first row seen for a dish is its winner. Do NOT reduce this with max() in
    Python; picking from an unordered query is the exact bug the photo-ranking
    note in AGENTS.md records.
    """
    if not dish_keys:
        return {}

    score = func.coalesce(func.sum(DBPhotoVote.direction), 0).label('total_score')
    rows = db.query(
        DBMeal.name.label('dish_name'),
        DBMeal.mensa_id.label('dish_mensa_id'),
        DBRating.photo_url,
        score,
    ).join(
        DBMeal, DBRating.meal_id == DBMeal.id
    ).outerjoin(
        DBPhotoVote, DBPhotoVote.rating_id == DBRating.id
    ).filter(
        # A superset of dish_keys (the cross product of the names and mensa ids
        # asked for); keying the result by the exact pair discards the rest.
        DBMeal.name.in_({k[0] for k in dish_keys}),
        DBMeal.mensa_id.in_({k[1] for k in dish_keys}),
        DBRating.photo_url.isnot(None),
    ).group_by(
        DBMeal.name, DBMeal.mensa_id, DBRating.id, DBRating.photo_url
    ).order_by(
        score.desc(), DBRating.created_at.asc(), DBRating.id.asc()
    ).all()

    top = {}
    for r in rows:
        top.setdefault((r.dish_name, r.dish_mensa_id), r.photo_url)
    return top


# A page of cards asks about every dish on the menu at once. 200 is well clear of
# the ~35 a day the four mensas produce, and stops a hand-built URL from turning
# into an unbounded IN list.
MAX_SUMMARY_IDS = 200


def _parse_id_list(raw: str):
    """Parse a `?ids=1,2,3` parameter into a list of ints."""
    ids = []
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"not an integer id: {part!r}")
    if len(ids) > MAX_SUMMARY_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"at most {MAX_SUMMARY_IDS} ids per request, got {len(ids)}",
        )
    return ids


@app.get("/api/v1/meals-summary", tags=["Meals"])
def get_meals_summary(ids: str = Query(..., description="Comma-separated meal ids"),
                      db: Session = Depends(get_db)):
    """Everything a *collapsed* dish card needs, for a whole page in one request.

    Replaces the two requests each card used to fire on mount
    (`/ratings-breakdown` and `/top-photo`). A 33-dish menu meant 66 requests,
    each checking out one of the 10 pool connections; that storm is what turned
    any brief contention -- a scrape holding a connection, say -- into the ~10s
    stall users saw, because the surplus waited out `pool_timeout`.

    `overall` is deliberately absent: GET /api/v1/meals already returns it as
    avg_rating/rating_count, grouped by exactly the same (name, mensa_id).
    The full breakdown is absent too -- it is ~6 queries per dish and the card
    only needs it once expanded.
    """
    meal_ids = _parse_id_list(ids)
    if not meal_ids:
        return {}

    meals = db.query(DBMeal.id, DBMeal.name, DBMeal.mensa_id).filter(
        DBMeal.id.in_(meal_ids)
    ).all()
    dish_of = {m.id: (m.name, m.mensa_id) for m in meals}
    dish_keys = set(dish_of.values())

    # "recent" means today's instance of this dish, matching get_ratings_breakdown
    # -- which is not the same as the card's own date when the user is browsing
    # another day.
    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    recent = {}
    if dish_keys:
        rows = db.query(
            DBMeal.name.label('dish_name'),
            DBMeal.mensa_id.label('dish_mensa_id'),
            func.avg(DBRating.rating).label('avg_rating'),
            func.count(DBRating.id).label('rating_count'),
        ).join(
            DBRating, DBRating.meal_id == DBMeal.id
        ).filter(
            DBMeal.date == today,
            DBMeal.name.in_({k[0] for k in dish_keys}),
            DBMeal.mensa_id.in_({k[1] for k in dish_keys}),
        ).group_by(DBMeal.name, DBMeal.mensa_id).all()
        recent = {(r.dish_name, r.dish_mensa_id): r for r in rows}

    top_photos = _top_photos_by_dish(dish_keys, db)

    out = {}
    for meal_id, key in dish_of.items():
        agg = recent.get(key)
        out[str(meal_id)] = {
            "recent": {
                "avg": round(float(agg.avg_rating), 1) if agg else 0,
                "count": agg.rating_count if agg else 0,
            },
            "top_photo": top_photos.get(key),
        }
    return out


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

    # Get entries for display (most recent 15 across all ratings for this dish).
    # A row qualifies on a comment OR a photo: a photo posted without text is
    # still something people vote on, and it used to be invisible here.
    comments_query = db.query(DBRating, DBMeal.date, DBRating.created_at).join(
        DBMeal, DBRating.meal_id == DBMeal.id
    ).filter(
        DBMeal.id.in_(all_meal_ids),
        or_(DBRating.comment.isnot(None), DBRating.photo_url.isnot(None))
    ).order_by(DBRating.created_at.desc()).limit(15).all()

    # The photo currently representing the dish must always be votable, even
    # when it is older than the 15 most recent entries -- otherwise nobody can
    # ever vote it back down and the selection is a one-way ratchet.
    top_photo = _top_photo_rating(all_meal_ids, db)
    if top_photo and top_photo.rating_id not in {r.Rating.id for r in comments_query}:
        extra = db.query(DBRating, DBMeal.date, DBRating.created_at).join(
            DBMeal, DBRating.meal_id == DBMeal.id
        ).filter(DBRating.id == top_photo.rating_id).first()
        if extra:
            comments_query = list(comments_query) + [extra]

    comment_ids = [r.Rating.id for r in comments_query]
    photo_ids = [r.Rating.id for r in comments_query if r.Rating.photo_url]
    
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

    photo_scores = {}
    if photo_ids:
        photo_score_results = db.query(
            DBPhotoVote.rating_id,
            func.sum(DBPhotoVote.direction).label('score')
        ).filter(
            DBPhotoVote.rating_id.in_(photo_ids)
        ).group_by(DBPhotoVote.rating_id).all()
        photo_scores = {r.rating_id: r.score if r.score is not None else 0 for r in photo_score_results}

    viewer_photo_votes = {}
    if voter_id and photo_ids:
        photo_vote_results = db.query(
            DBPhotoVote.rating_id,
            DBPhotoVote.direction
        ).filter(
            DBPhotoVote.rating_id.in_(photo_ids),
            DBPhotoVote.voter_id == voter_id
        ).all()
        viewer_photo_votes = {r.rating_id: r.direction for r in photo_vote_results}

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
            vote_direction=viewer_votes.get(r.Rating.id),
            photo_score=photo_scores.get(r.Rating.id, 0),
            photo_vote_direction=viewer_photo_votes.get(r.Rating.id)
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
                "vote_direction": c.vote_direction,
                "photo_score": c.photo_score,
                "photo_vote_direction": c.photo_vote_direction
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
    # This route takes a raw dict rather than a model, so the length cap the
    # other three write paths get from Field(max_length=...) is manual here.
    if len(comment) > COMMENT_MAX_LENGTH:
        raise HTTPException(status_code=400, detail=f"comment exceeds {COMMENT_MAX_LENGTH} characters")
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
    
    user = auth._lookup(db, authorization)
    
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


def get_photo_score(rating_id: int, db: Session) -> int:
    result = db.query(func.sum(DBPhotoVote.direction)).filter(
        DBPhotoVote.rating_id == rating_id
    ).scalar()
    return result if result is not None else 0


@app.put("/api/v1/ratings/{rating_id}/photo-vote")
def vote_on_photo(rating_id: int, data: dict, db: Session = Depends(get_db), voter_id: Optional[str] = Header(None, alias="X-Voter-Id"), authorization: Optional[str] = Header(None)):
    """Vote on the photo attached to a rating. Toggle: same direction removes, opposite switches.

    Separate from vote_on_comment on purpose -- these votes, and only these,
    decide which photo represents the dish (get_top_photo).
    """
    if not voter_id:
        raise HTTPException(status_code=400, detail="X-Voter-Id header required")

    rating = db.query(DBRating).filter(DBRating.id == rating_id).first()
    if not rating:
        raise HTTPException(status_code=404, detail="Rating not found")
    if not rating.photo_url:
        raise HTTPException(status_code=400, detail="Rating has no photo")

    direction = data.get("direction")
    if direction not in (1, -1):
        raise HTTPException(status_code=400, detail="direction must be 1 (up) or -1 (down)")

    user = auth._lookup(db, authorization)

    existing = db.query(DBPhotoVote).filter(
        DBPhotoVote.rating_id == rating_id,
        DBPhotoVote.voter_id == voter_id
    ).first()

    if existing:
        if existing.direction == direction:
            db.delete(existing)
            db.commit()
            return {"direction": None, "score": get_photo_score(rating_id, db)}
        existing.direction = direction
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return {"direction": direction, "score": get_photo_score(rating_id, db)}

    vote = DBPhotoVote(
        rating_id=rating_id,
        voter_id=voter_id,
        user_id=user.id if user else None,
        direction=direction
    )
    db.add(vote)
    db.commit()
    db.refresh(vote)
    return {"direction": direction, "score": get_photo_score(rating_id, db)}


@app.get("/api/v1/ratings/{rating_id}/photo-vote")
def get_photo_vote_status(rating_id: int, db: Session = Depends(get_db), voter_id: Optional[str] = Header(None, alias="X-Voter-Id")):
    """Get current photo vote status, including the viewer's vote and total score."""
    if not voter_id:
        raise HTTPException(status_code=400, detail="X-Voter-Id header required")

    rating = db.query(DBRating).filter(DBRating.id == rating_id).first()
    if not rating:
        raise HTTPException(status_code=404, detail="Rating not found")
    if not rating.photo_url:
        raise HTTPException(status_code=400, detail="Rating has no photo")

    vote = db.query(DBPhotoVote).filter(
        DBPhotoVote.rating_id == rating_id,
        DBPhotoVote.voter_id == voter_id
    ).first()

    return {
        "direction": vote.direction if vote else None,
        "score": get_photo_score(rating_id, db)
    }


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


@app.delete("/api/v1/me", status_code=204, tags=["Auth"])
def delete_me(user: DBUser = Depends(auth.current_user), db: Session = Depends(get_db)):
    """Erase the account, keeping the ratings as anonymous rows (DSGVO Art. 17).

    Ratings are not deleted, they are detached: user_id goes to NULL and
    user_name is replaced with a fresh generated pseudonym, which is exactly
    the shape an anonymous rating has always had (both columns are nullable by
    design). So the dish averages and the photo ranking survive, while nothing
    published stays attributable to a person. Someone who wants the reviews
    gone as well is told in the privacy notice to ask by email.

    Nothing in the schema declares ON DELETE, so every table that references
    users.id has to be handled here explicitly and in this order, or Postgres
    raises a foreign-key violation on the final delete.
    """
    for row in db.query(DBRating).filter(DBRating.user_id == user.id).all():
        row.user_id = None
        row.user_name = generate_funny_name()
    for row in db.query(DBSideRating).filter(DBSideRating.user_id == user.id).all():
        row.user_id = None
        row.user_name = generate_funny_name()

    # The votes stay -- they are counted per voter_id, so dropping them would
    # reshuffle which photo represents a dish. Only the account link goes.
    db.query(DBCommentVote).filter(DBCommentVote.user_id == user.id).update(
        {DBCommentVote.user_id: None}, synchronize_session=False)
    db.query(DBPhotoVote).filter(DBPhotoVote.user_id == user.id).update(
        {DBPhotoVote.user_id: None}, synchronize_session=False)

    # Every session, not just the token that made this request.
    db.query(DBAuthToken).filter(DBAuthToken.user_id == user.id).delete(
        synchronize_session=False)

    # Flush before the delete rather than trusting the unit of work to order
    # the pending rating UPDATEs ahead of it. The unit tests run on SQLite,
    # which does not enforce foreign keys by default, so a wrong order here
    # would only ever fail on Postgres -- i.e. in production.
    db.flush()

    db.delete(user)
    db.commit()
    return Response(status_code=204)


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

    # Both vote tables reference ratings.id with NO ACTION, and Rating declares
    # no relationship() to either, so a bare DELETE raised a foreign-key
    # violation that the catch-all handler turned into a 500. Any review that
    # someone had voted on was undeletable by its author.
    db.query(DBCommentVote).filter(DBCommentVote.rating_id == rating.id).delete()
    db.query(DBPhotoVote).filter(DBPhotoVote.rating_id == rating.id).delete()

    # basename() so a crafted photo_url can't escape the upload directory.
    photo_path = None
    if rating.photo_url:
        photo_path = os.path.join(UPLOAD_DIR, os.path.basename(rating.photo_url))

    db.delete(rating)
    db.commit()

    # Unlink only once the row is really gone. Removing the file first meant a
    # failed commit left a visible review pointing at a photo that no longer
    # existed.
    if photo_path and os.path.isfile(photo_path):
        os.remove(photo_path)
    return Response(status_code=204)


# Both PostgreSQL EXTRACT(DOW ...) and SQLite STRFTIME('%w', ...) number the week
# 0 = Sunday .. 6 = Saturday. Mapping each one to a name explicitly beats offset
# arithmetic against a Monday-first list, which is what shifted every bar in the
# weekly-trends chart two days.
DOW_TO_KEY = {1: "monday", 2: "tuesday", 3: "wednesday", 4: "thursday",
              5: "friday", 6: "saturday", 0: "sunday"}
WEEK_ORDER = ["monday", "tuesday", "wednesday", "thursday",
              "friday", "saturday", "sunday"]


def _local_dow(bind):
    """Weekday of Rating.created_at in Europe/Berlin.

    created_at is a naive TIMESTAMP holding UTC: the db container sets no TZ, so
    the server-side func.now() default lands as UTC, while the rest of this
    module reasons in Berlin time (see the ZoneInfo calls above). Postgres can
    reinterpret it; SQLite has no timezone database, so the test default buckets
    on UTC -- see test_api_stats.py.
    """
    col = DBRating.created_at
    if bind.dialect.name == "postgresql":
        # timezone('UTC', naive) -> timestamptz, then
        # timezone('Europe/Berlin', tz) -> Berlin-local naive. Handles CET/CEST.
        col = func.timezone("Europe/Berlin", func.timezone("UTC", col))
    return func.extract("dow", col)


@app.get("/api/v1/stats/overview", response_model=dict, tags=["Stats"])
def get_dashboard_stats(db: Session = Depends(get_db), lang: str = "de"):
    """Main dashboard statistics"""
    # Total ratings
    total_ratings = db.query(func.count(DBRating.id)).scalar() or 0
    
    # Distinct dishes, not menu rows. DBMeal.id is the primary key, so the old
    # count(DISTINCT id) removed nothing and counted every row the scraper has
    # ever written -- one per (date, mensa_id, name) -- which grows without
    # bound as the same dish is served again. (name, mensa_id) is the dish
    # identity used everywhere else here: see the rating_agg group_by in
    # get_meals and the filters in get_ratings.
    total_meals = db.query(DBMeal.name, DBMeal.mensa_id).distinct().count()
    
    # Total mensas
    total_mensas = db.query(func.count(DBMensa.id)).scalar() or 0
    
    # Top rated dishes (with at least 5 ratings)
    top_dishes = db.query(
        DBMeal.id,
        DBMeal.name,
        DBMeal.name_en,
        DBMeal.name_de,
        DBMensa.name.label('mensa'),
        func.avg(DBRating.rating).label('avg_rating'),
        func.count(DBRating.id).label('rating_count')
    ).join(
        DBMensa, DBMeal.mensa_id == DBMensa.id
    ).join(
        DBRating, DBRating.meal_id == DBMeal.id
    ).group_by(DBMeal.id, DBMensa.name).having(func.count(DBRating.id) >= 5).order_by(
        func.avg(DBRating.rating).desc()
    ).limit(10).all()
    
    top_dishes_list = []
    for dish in top_dishes:
        if lang == "en":
            name = dish.name_en or dish.name_de or dish.name
        else:
            name = dish.name_de or dish.name
        top_dishes_list.append({
            "id": dish.id,
            "name": name,
            "mensa": dish.mensa,
            "avg_rating": round(float(dish.avg_rating), 1),
            "rating_count": dish.rating_count
        })
    
    # Mensa rankings (with at least 5 ratings)
    mensa_stats = db.query(
        DBMensa.name,
        func.count(DBRating.id).label('total_ratings'),
        func.avg(DBRating.rating).label('avg_rating')
    ).join(DBMeal, DBMeal.mensa_id == DBMensa.id).join(
        DBRating, DBRating.meal_id == DBMeal.id
    ).group_by(DBMensa.name).having(func.count(DBRating.id) >= 5).order_by(
        func.avg(DBRating.rating).desc()
    ).all()
    
    mensa_rankings = []
    for stat in mensa_stats:
        mensa_rankings.append({
            "name": stat.name,
            "total_ratings": stat.total_ratings,
            "avg_rating": round(float(stat.avg_rating), 1)
        })
    
    # Weekly trends (ratings by day of week, in Berlin time)
    dow = _local_dow(db.get_bind())
    rows = db.query(dow.label('dow'), func.count(DBRating.id)).group_by(dow).all()
    counts = {DOW_TO_KEY[int(d)]: n for d, n in rows if int(d) in DOW_TO_KEY}
    # Zero-fill so all seven keys are always present, Monday first: the frontend
    # renders Object.entries() in insertion order.
    weekly_trends = {key: counts.get(key, 0) for key in WEEK_ORDER}
    
    return {
        "total_ratings": total_ratings,
        "total_meals": total_meals,
        "total_mensas": total_mensas,
        "top_rated_dishes": top_dishes_list,
        "mensa_rankings": mensa_rankings,
        "weekly_trends": weekly_trends
    }

@app.get("/api/v1/stats/mensas")
def get_mensa_stats(db: Session = Depends(get_db)):
    """Per-mensa statistics"""
    # outerjoin, not join: a mensa whose meals have no ratings yet still has a
    # meal count worth reporting and must not drop out of the list. Without any
    # join at all, `ratings` lands in the FROM clause unconstrained and every
    # mensa is paired with every rating in the database.
    mensa_stats = db.query(
        DBMensa.name,
        func.count(DBRating.id).label('total_ratings'),
        func.coalesce(func.avg(DBRating.rating), 0).label('avg_rating'),
        func.count(DBMeal.id.distinct()).label('total_meals')
    ).join(DBMeal, DBMeal.mensa_id == DBMensa.id
    ).outerjoin(DBRating, DBRating.meal_id == DBMeal.id
    ).group_by(DBMensa.name).order_by(
        func.coalesce(func.avg(DBRating.rating), 0).desc()
    ).all()
    
    return [
        {
            "name": stat.name,
            "total_ratings": stat.total_ratings,
            "avg_rating": round(float(stat.avg_rating), 1),
            "total_meals": stat.total_meals
        }
        for stat in mensa_stats
    ]

@app.get("/api/v1/stats/top-dishes")
def get_top_dishes(limit: int = 10, db: Session = Depends(get_db)):
    """Top rated dishes across all mensas"""
    top_dishes = db.query(
        DBMeal.id,
        DBMeal.name,
        DBMeal.name_en,
        DBMeal.name_de,
        DBMensa.name.label('mensa'),
        func.avg(DBRating.rating).label('avg_rating'),
        func.count(DBRating.id).label('rating_count')
    ).join(
        DBMensa, DBMeal.mensa_id == DBMensa.id
    ).join(
        # Inner join: an unrated dish has no average and does not belong in a
        # "top rated" list. Omitting it cross-joined every meal with every rating.
        DBRating, DBRating.meal_id == DBMeal.id
    ).group_by(DBMeal.id, DBMensa.name).order_by(
        func.avg(DBRating.rating).desc()
    ).limit(limit).all()
    
    return [
        {
            "id": dish.id,
            "name": dish.name_en or dish.name_de or dish.name,
            "mensa": dish.mensa,
            "avg_rating": round(float(dish.avg_rating), 1),
            "rating_count": dish.rating_count
        }
        for dish in top_dishes
    ]

@app.get("/api/v1/stats/top-photo")
def get_top_photo_global(db: Session = Depends(get_db)):
    """Get the photo with the highest photo-vote score across all meals"""
    score = func.coalesce(func.sum(DBPhotoVote.direction), 0).label('total_score')
    top_photo = db.query(
        DBRating.id.label('rating_id'),
        DBRating.photo_url,
        DBMeal.name.label('meal_name'),
        DBMensa.name.label('mensa'),
        score
    ).join(
        DBMeal, DBRating.meal_id == DBMeal.id
    ).join(
        DBMensa, DBMeal.mensa_id == DBMensa.id
    ).outerjoin(
        DBPhotoVote, DBPhotoVote.rating_id == DBRating.id
    ).filter(
        DBRating.photo_url.isnot(None)
    ).group_by(
        DBRating.id, DBRating.photo_url, DBMeal.name, DBMensa.name
    ).order_by(
        score.desc(), DBRating.created_at.asc(), DBRating.id.asc()
    ).first()

    if not top_photo:
        return {"photo_url": None, "meal_name": None, "mensa": None}
    
    return {
        "photo_url": top_photo.photo_url,
        "meal_name": top_photo.meal_name,
        "mensa": top_photo.mensa
    }

@app.get("/api/v1/mensas")
def get_mensas(db: Session = Depends(get_db)):
    return [m.name for m in db.query(DBMensa).order_by(DBMensa.name).all()]

@app.get("/api/v1/meals/{meal_id}/top-photo")
def get_top_photo(meal_id: int, db: Session = Depends(get_db)):
    """Get the photo with the highest photo-vote score for this dish"""
    # Find all meal instances with same (name, mensa_id) combination
    meal = db.query(DBMeal).filter(DBMeal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")
    
    all_meals = db.query(DBMeal).filter(
        DBMeal.name == meal.name,
        DBMeal.mensa_id == meal.mensa_id
    ).all()
    
    all_meal_ids = [m.id for m in all_meals]

    top_photo = _top_photo_rating(all_meal_ids, db)
    if not top_photo:
        return {"photo_url": None}

    return {"photo_url": top_photo.photo_url}

# Serves the photos written by create_rating_with_photo. StaticFiles handles
# content types, conditional requests (ETag/Last-Modified) and range requests,
# and refuses to resolve a path outside `directory`.
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)