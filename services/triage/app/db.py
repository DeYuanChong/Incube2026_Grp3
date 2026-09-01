from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from .config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def init_db() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS triage"))
        # pg_trgm powers the duplicate-detection similarity pre-filter (docs/05)
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
