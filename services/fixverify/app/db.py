import os

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from .config import DATABASE_URL, UPLOAD_DIR

os.makedirs(UPLOAD_DIR, exist_ok=True)
engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def init_db() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS fixverify"))
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
