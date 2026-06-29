from sqlalchemy import create_engine, Column, Integer, String, Date, ForeignKey, Float, Text, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/mensa_db")

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
    description = Column(Text, nullable=True)
    type = Column(String)
    date = Column(Date, index=True)
    mensa_id = Column(Integer, ForeignKey("mensas.id"))
    mensa = relationship("Mensa", back_populates="meals")
    ratings = relationship("Rating", back_populates="meal")

class Rating(Base):
    __tablename__ = "ratings"
    id = Column(Integer, primary_key=True, index=True)
    meal_id = Column(Integer, ForeignKey("meals.id"))
    rating = Column(Integer)
    comment = Column(Text, nullable=True)
    user_name = Column(String, nullable=True)
    meal = relationship("Meal", back_populates="ratings")

def init_db():
    Base.metadata.create_all(bind=engine)
    # Add description column if it doesn't exist
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='meals' AND column_name='description'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE meals ADD COLUMN description TEXT"))
            conn.commit()
            print("Added description column to meals table")
