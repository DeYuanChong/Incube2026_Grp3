from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from .config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def init_db() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS reporting"))
        # pg_trgm powers the fuzzy `q` search on issues (docs/02)
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS issues_search_trgm "
            "ON reporting.issues USING gin ((title || ' ' || description) gin_trgm_ops)"
        ))


def get_session():
    with Session(engine) as session:
        yield session
