from sqlalchemy import create_engine, Column, Integer, String, Date, ForeignKey, Float, Text, Boolean, text, DateTime, UniqueConstraint, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os
import logging

log = logging.getLogger("database")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")

# Schema changes run as the table OWNER; the request path deliberately does not.
# In production DATABASE_URL is the `mensa_app` role, which holds DML rights only
# (no ownership, no DDL), so a stray Base.metadata.drop_all() cannot drop
# anything -- Postgres refuses with "must be owner of table". That is enforcement
# rather than convention, and it is the last line of defence behind the test
# safety rail in backend/tests/conftest.py. See ops/setup-db-roles.sh.
#
# Falls back to DATABASE_URL when unset, so dev/test/SQLite keep working with a
# single URL and one privileged role.
MIGRATION_DATABASE_URL = os.getenv("MIGRATION_DATABASE_URL") or DATABASE_URL

# pool_pre_ping issues a cheap SELECT 1 before handing out a pooled connection
# and transparently replaces it if the socket is dead. Without it, every
# connection in the pool is poisoned by a `docker restart db` -- or by the host
# crashing, which happened twice in two days -- and every request 500s with
# OperationalError until someone restarts the backend by hand. That is why the
# site stayed broken AFTER the machine came back, not just during.
#
# NEVER cap the anyio worker thread pool below this capacity.
#
# Every route in main.py is a sync `def`, so FastAPI runs it on the anyio worker
# thread pool (40 threads by default) -- and it runs the CLEANUP of the sync
# `get_db` generator dependency there too. Releasing a connection therefore
# needs a worker thread, exactly like acquiring one does.
#
# An earlier attempt on 2026-09-02 to "make the pool and the threads agree" by
# lowering the limiter to the pool size deadlocked the app under load: with
# fewer tokens than connections, the exit tasks that call db.close() queue
# behind pending requests that are themselves blocked in pool.connect() waiting
# for a connection only those exits can free. The queue only drains as each
# waiter gives up after pool_timeout. Measured on dev: 60 concurrent requests
# went from ~50ms each to 30-40s with 102 of 180 failing, and every pooled
# connection sat in `idle in transaction`. The limiter must stay at or above
# POOL_CAPACITY; the default 40 is fine.
#
# So the pool is sized for the concurrency instead. Waiting for a connection is
# safe when tokens are plentiful -- requests are ~50ms, so a brief spike drains
# in well under a second and pool_timeout is never reached.
_ENGINE_KWARGS = dict(
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=10,
    max_overflow=10,
    pool_timeout=10,
)

# Documentation and a floor for the limiter, not a cap on requests. Each Postgres
# backend costs ~10 MB, so 20 is the ceiling this 3.8 GiB host can spare against
# the db container's 768 MB limit.
POOL_CAPACITY = _ENGINE_KWARGS["pool_size"] + _ENGINE_KWARGS["max_overflow"]

# connect_timeout/application_name are libpq arguments; the test suite runs
# against SQLite (see backend/tests/conftest.py), which would reject them.
if DATABASE_URL.startswith("postgresql"):
    _ENGINE_KWARGS["connect_args"] = {
        "connect_timeout": 5,
        "application_name": "mensa-api",
    }

engine = create_engine(DATABASE_URL, **_ENGINE_KWARGS)
migration_engine = (
    engine if MIGRATION_DATABASE_URL == DATABASE_URL
    else create_engine(MIGRATION_DATABASE_URL, pool_pre_ping=True, pool_size=1)
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class Mensa(Base):
    __tablename__ = "mensas"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    meals = relationship("Meal", back_populates="mensa")

class Meal(Base):
    __tablename__ = "meals"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    name_de = Column(String, index=True)
    name_en = Column(String, index=True)
    description = Column(Text, nullable=True)
    description_de = Column(Text, nullable=True)
    description_en = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)
    type = Column(String)
    date = Column(Date, index=True)
    mensa_id = Column(Integer, ForeignKey("mensas.id"))
    mensa = relationship("Mensa", back_populates="meals")
    ratings = relationship("Rating", back_populates="meal")
    side_ratings = relationship("SideRating", back_populates="meal")
    is_available = Column(Boolean, default=True)

class Rating(Base):
    __tablename__ = "ratings"
    id = Column(Integer, primary_key=True, index=True)
    meal_id = Column(Integer, ForeignKey("meals.id"))
    rating = Column(Integer)
    comment = Column(Text, nullable=True)
    user_name = Column(String, nullable=True)
    # Nullable: anonymous ratings stay supported, and every pre-accounts row is valid.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    photo_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now())
    meal = relationship("Meal", back_populates="ratings")

class SideRating(Base):
    __tablename__ = "side_ratings"
    id = Column(Integer, primary_key=True, index=True)
    meal_id = Column(Integer, ForeignKey("meals.id"))
    side_name = Column(String)
    rating = Column(Integer)
    comment = Column(Text, nullable=True)
    user_name = Column(String, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=func.now())
    meal = relationship("Meal", back_populates="side_ratings")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    display_name = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=func.now())

class AuthToken(Base):
    # Not "Session" -- that name is already sqlalchemy.orm.Session throughout this codebase.
    __tablename__ = "auth_tokens"
    token = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    created_at = Column(DateTime, default=func.now())

class CommentVote(Base):
    __tablename__ = "comment_votes"
    id = Column(Integer, primary_key=True, index=True)
    rating_id = Column(Integer, ForeignKey("ratings.id"), index=True)
    voter_id = Column(String, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    direction = Column(Integer)
    created_at = Column(DateTime, default=func.now())

class PhotoVote(Base):
    # Deliberately separate from CommentVote: an upvote on a review is not an
    # upvote on the picture attached to it, and only this table decides which
    # photo represents a dish (see get_top_photo in main.py).
    __tablename__ = "photo_votes"
    id = Column(Integer, primary_key=True, index=True)
    rating_id = Column(Integer, ForeignKey("ratings.id"), index=True)
    voter_id = Column(String, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    direction = Column(Integer)
    created_at = Column(DateTime, default=func.now())
    # comment_votes has no such constraint and can accumulate duplicate rows for
    # one voter. This table starts empty, so the constraint costs nothing here.
    __table_args__ = (UniqueConstraint("rating_id", "voter_id", name="uq_photo_vote_voter"),)

def init_db():
    """Create/upgrade the schema. Runs as the owner (see MIGRATION_DATABASE_URL)."""
    Base.metadata.create_all(bind=migration_engine)
    with migration_engine.connect() as conn:
        # Add description column if missing
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='meals' AND column_name='description'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE meals ADD COLUMN description TEXT"))
            conn.commit()
            log.info("Added description column to meals table")
        # Add tags column if missing
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='meals' AND column_name='tags'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE meals ADD COLUMN tags TEXT"))
            conn.commit()
            log.info("Added tags column to meals table")
        # Add name_de column if missing
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='meals' AND column_name='name_de'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE meals ADD COLUMN name_de VARCHAR"))
            conn.commit()
            log.info("Added name_de column to meals table")
        # Add name_en column if missing
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='meals' AND column_name='name_en'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE meals ADD COLUMN name_en VARCHAR"))
            conn.commit()
            log.info("Added name_en column to meals table")
        # Add description_de column if missing
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='meals' AND column_name='description_de'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE meals ADD COLUMN description_de TEXT"))
            conn.commit()
            log.info("Added description_de column to meals table")
        # Add description_en column if missing
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='meals' AND column_name='description_en'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE meals ADD COLUMN description_en TEXT"))
            conn.commit()
            log.info("Added description_en column to meals table")
        # Add photo_url column if missing
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='ratings' AND column_name='photo_url'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE ratings ADD COLUMN photo_url VARCHAR"))
            conn.commit()
            log.info("Added photo_url column to ratings table")
        # Add is_available column if missing
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='meals' AND column_name='is_available'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE meals ADD COLUMN is_available BOOLEAN DEFAULT TRUE"))
            conn.commit()
            log.info("Added is_available column to meals table")
        # Add user_id column to ratings if missing (accounts feature)
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='ratings' AND column_name='user_id'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE ratings ADD COLUMN user_id INTEGER REFERENCES users(id)"))
            conn.commit()
            log.info("Added user_id column to ratings table")
        # Add user_id column to side_ratings if missing (accounts feature)
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='side_ratings' AND column_name='user_id'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE side_ratings ADD COLUMN user_id INTEGER REFERENCES users(id)"))
            conn.commit()
            log.info("Added user_id column to side_ratings table")
        # Add display_name column to users if missing
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='users' AND column_name='display_name'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE users ADD COLUMN display_name VARCHAR"))
            conn.commit()
            log.info("Added display_name column to users table")
        # Create comment_votes table if not exists
        result = conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='comment_votes'"
        ))
        if not result.fetchone():
            conn.execute(text("""
                CREATE TABLE comment_votes (
                    id SERIAL PRIMARY KEY,
                    rating_id INTEGER REFERENCES ratings(id),
                    voter_id VARCHAR NOT NULL,
                    user_id INTEGER REFERENCES users(id),
                    direction INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()
            log.info("Created comment_votes table")
        # Create photo_votes table if not exists
        result = conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='photo_votes'"
        ))
        if not result.fetchone():
            conn.execute(text("""
                CREATE TABLE photo_votes (
                    id SERIAL PRIMARY KEY,
                    rating_id INTEGER REFERENCES ratings(id),
                    voter_id VARCHAR NOT NULL,
                    user_id INTEGER REFERENCES users(id),
                    direction INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    CONSTRAINT uq_photo_vote_voter UNIQUE (rating_id, voter_id)
                )
            """))
            conn.execute(text("CREATE INDEX ix_photo_votes_rating_id ON photo_votes (rating_id)"))
            conn.execute(text("CREATE INDEX ix_photo_votes_voter_id ON photo_votes (voter_id)"))
            conn.commit()
            log.info("Created photo_votes table")
