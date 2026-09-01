from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine

from .config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def _create_pg_trgm() -> None:
    # pg_trgm powers the duplicate-detection similarity pre-filter (docs/05).
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
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS triage"))
    _create_pg_trgm()
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        # create_all creates missing tables and never ALTERs existing ones,
        # and pg-data is a persistent volume — so a column added after the
        # first deploy ships as idempotent DDL here or silently does not
        # exist. Must run after create_all: the table has to be there first.
        # ponytail: hand-written DDL, one line per column. Alembic when the
        # changes stop being additive.
        conn.execute(text(
            "ALTER TABLE triage.issue_facts "
            "ADD COLUMN IF NOT EXISTS duplicate_group_id TEXT"
        ))


def get_session():
    with Session(engine) as session:
        yield session
