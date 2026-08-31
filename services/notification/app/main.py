import os

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, SQLModel, create_engine, func, or_, select

from .models import Notification
from .rules import notifications_for

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/notification.db")
os.makedirs("data", exist_ok=True)
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

app = FastAPI(title="Notification Service", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


@app.on_event("startup")
def startup() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


def _inbox_filter(stmt, x_user: str, x_role: str):
    """A notification reaches the caller when it targets their role broadly
    (no specific user) or targets them by name."""
    return stmt.where(
        or_(
            (Notification.target_role == x_role) & (Notification.target_user.is_(None)),  # type: ignore[union-attr]
            Notification.target_user == x_user,
        )
    )


@app.get("/health")
def health():
    return {"service": "notification", "status": "ok"}


@app.get("/notifications")
def inbox(
    session: Session = Depends(get_session),
    unread_only: bool = False,
    x_user: str = Header("anonymous"),
    x_role: str = Header("reporter"),
):
    stmt = _inbox_filter(select(Notification), x_user, x_role)
    if unread_only:
        stmt = stmt.where(Notification.is_read == False)  # noqa: E712
    stmt = stmt.order_by(Notification.created_at.desc()).limit(100)  # type: ignore[attr-defined]
    return session.exec(stmt).all()


@app.get("/notifications/unread-count")
def unread_count(
    session: Session = Depends(get_session),
    x_user: str = Header("anonymous"),
    x_role: str = Header("reporter"),
):
    stmt = _inbox_filter(
        select(func.count()).select_from(Notification), x_user, x_role
    ).where(Notification.is_read == False)  # noqa: E712
    return {"unread": session.exec(stmt).one()}


@app.post("/notifications/{notification_id}/read")
def mark_read(notification_id: str, session: Session = Depends(get_session)):
    notification = session.get(Notification, notification_id)
    if not notification:
        raise HTTPException(404, "notification not found")
    notification.is_read = True
    session.commit()
    return notification


@app.post("/notifications/read-all")
def mark_all_read(
    session: Session = Depends(get_session),
    x_user: str = Header("anonymous"),
    x_role: str = Header("reporter"),
):
    stmt = _inbox_filter(select(Notification), x_user, x_role).where(
        Notification.is_read == False  # noqa: E712
    )
    rows = session.exec(stmt).all()
    for row in rows:
        row.is_read = True
    session.commit()
    return {"marked_read": len(rows)}


@app.post("/webhooks/events")
def webhook(event: dict, session: Session = Depends(get_session)):
    created = [Notification(**kwargs) for kwargs in notifications_for(event)]
    for notification in created:
        session.add(notification)
    session.commit()
    return {"created": len(created)}
