import os

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine

from . import config
from .config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def _create_pg_trgm() -> None:
    # pg_trgm powers the fuzzy `q` search on issues (docs/02).
    # `IF NOT EXISTS` is not atomic across concurrent connections: when
    # sibling services (triage, reporting) boot together under docker compose,
    # both can pass the existence check and race to insert into pg_extension,
    # and the loser hits a UniqueViolation on pg_extension_name_index. Run it
    # in its own transaction and treat that race as success — the extension is
    # there once anyone wins.
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    except IntegrityError:
        pass


def init_db() -> None:
    os.makedirs(config.UPLOAD_DIR, exist_ok=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS reporting"))
    _create_pg_trgm()
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS issues_search_trgm "
            "ON reporting.issues USING gin ((title || ' ' || description) gin_trgm_ops)"
        ))


def get_session():
    with Session(engine) as session:
        yield session
