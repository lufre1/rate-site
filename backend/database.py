from sqlalchemy import create_engine, Column, Integer, String, Date, ForeignKey, Float, Text, Boolean, text, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os

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

engine = create_engine(DATABASE_URL)
migration_engine = (
    engine if MIGRATION_DATABASE_URL == DATABASE_URL
    else create_engine(MIGRATION_DATABASE_URL)
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
            print("Added description column to meals table")
        # Add tags column if missing
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='meals' AND column_name='tags'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE meals ADD COLUMN tags TEXT"))
            conn.commit()
            print("Added tags column to meals table")
        # Add name_de column if missing
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='meals' AND column_name='name_de'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE meals ADD COLUMN name_de VARCHAR"))
            conn.commit()
            print("Added name_de column to meals table")
        # Add name_en column if missing
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='meals' AND column_name='name_en'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE meals ADD COLUMN name_en VARCHAR"))
            conn.commit()
            print("Added name_en column to meals table")
        # Add description_de column if missing
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='meals' AND column_name='description_de'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE meals ADD COLUMN description_de TEXT"))
            conn.commit()
            print("Added description_de column to meals table")
        # Add description_en column if missing
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='meals' AND column_name='description_en'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE meals ADD COLUMN description_en TEXT"))
            conn.commit()
            print("Added description_en column to meals table")
        # Add photo_url column if missing
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='ratings' AND column_name='photo_url'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE ratings ADD COLUMN photo_url VARCHAR"))
            conn.commit()
            print("Added photo_url column to ratings table")
        # Add is_available column if missing
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='meals' AND column_name='is_available'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE meals ADD COLUMN is_available BOOLEAN DEFAULT TRUE"))
            conn.commit()
            print("Added is_available column to meals table")
        # Add user_id column to ratings if missing (accounts feature)
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='ratings' AND column_name='user_id'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE ratings ADD COLUMN user_id INTEGER REFERENCES users(id)"))
            conn.commit()
            print("Added user_id column to ratings table")
        # Add user_id column to side_ratings if missing (accounts feature)
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='side_ratings' AND column_name='user_id'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE side_ratings ADD COLUMN user_id INTEGER REFERENCES users(id)"))
            conn.commit()
            print("Added user_id column to side_ratings table")
        # Add display_name column to users if missing
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='users' AND column_name='display_name'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE users ADD COLUMN display_name VARCHAR"))
            conn.commit()
            print("Added display_name column to users table")
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
            print("Created comment_votes table")
