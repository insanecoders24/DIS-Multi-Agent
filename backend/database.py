"""
SQLAlchemy Database Setup for DIS.
Uses SQLite in development; swap DATABASE_URL for PostgreSQL in production.
"""
from __future__ import annotations
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///storage/dis.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    echo=False,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Called at startup."""
    os.makedirs("storage/pdfs", exist_ok=True)
    os.makedirs("storage/page_images", exist_ok=True)
    Base.metadata.create_all(bind=engine)
