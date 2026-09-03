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
    # create_all never ALTERs an existing table, so columns added after the
    # first deploy ship as idempotent DDL here. Existing proofs predate the
    # confirm step and were finalised under the old one-shot flow, so they
    # backfill as submitted=true.
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE fixverify.proofs "
            "ADD COLUMN IF NOT EXISTS submitted BOOLEAN NOT NULL DEFAULT true"
        ))
        conn.execute(text(
            "ALTER TABLE fixverify.proofs "
            "ADD COLUMN IF NOT EXISTS ai_overridden BOOLEAN NOT NULL DEFAULT false"
        ))


def get_session():
    with Session(engine) as session:
        yield session
