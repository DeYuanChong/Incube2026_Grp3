import uuid
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Notification(SQLModel, table=True):
    __tablename__ = "notification_inbox"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    target_role: str = Field(index=True)  # reporter | maintenance | admin
    target_user: str | None = Field(default=None, index=True)  # narrows to a person
    issue_id: str | None = None
    event_type: str = ""
    title: str
    body: str = ""
    is_read: bool = Field(default=False, index=True)
    created_at: str = Field(default_factory=now_iso)
