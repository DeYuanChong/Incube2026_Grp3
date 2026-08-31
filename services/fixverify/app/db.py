import os

from sqlmodel import Session, SQLModel, create_engine

from .config import DATABASE_URL, UPLOAD_DIR

os.makedirs("data", exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
