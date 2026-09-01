import os

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from .config import DATABASE_URL

os.makedirs("data", exist_ok=True)
# One unified SQLite file shared by all services; WAL + busy timeout so
# concurrent writers from different services don't collide (docs/02).
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30}
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
