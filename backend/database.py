from sqlalchemy import create_engine, Column, Integer, String, Date, ForeignKey, Float, Text, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import os

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Mensa(Base):
    __tablename__ = "mensas"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    meals = relationship("Meal", back_populates="mensa")

class Meal(Base):
    __tablename__ = "meals"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    name_de = Column(String, index=True)  # German name
    name_en = Column(String, index=True)  # English name
    description = Column(Text, nullable=True)
    description_de = Column(Text, nullable=True)  # German description
    description_en = Column(Text, nullable=True)  # English description
    tags = Column(Text, nullable=True)
    type = Column(String)
    date = Column(Date, index=True)
    mensa_id = Column(Integer, ForeignKey("mensas.id"))
    mensa = relationship("Mensa", back_populates="meals")
    ratings = relationship("Rating", back_populates="meal")
    side_ratings = relationship("SideRating", back_populates="meal")

class Rating(Base):
    __tablename__ = "ratings"
    id = Column(Integer, primary_key=True, index=True)
    meal_id = Column(Integer, ForeignKey("meals.id"))
    rating = Column(Integer)
    comment = Column(Text, nullable=True)
    user_name = Column(String, nullable=True)
    photo_url = Column(String, nullable=True)
    meal = relationship("Meal", back_populates="ratings")

class SideRating(Base):
    __tablename__ = "side_ratings"
    id = Column(Integer, primary_key=True, index=True)
    meal_id = Column(Integer, ForeignKey("meals.id"))
    side_name = Column(String)
    rating = Column(Integer)
    comment = Column(Text, nullable=True)
    user_name = Column(String, nullable=True)
    meal = relationship("Meal", back_populates="side_ratings")

def init_db():
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
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
