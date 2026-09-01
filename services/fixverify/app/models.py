import uuid
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


class WorkOrder(SQLModel, table=True):
    __tablename__ = "work_orders"
    __table_args__ = {"schema": "fixverify"}

    id: str = Field(default_factory=new_id, primary_key=True)
    issue_id: str = Field(index=True, unique=True)
    issue_reference_no: str = ""
    issue_title: str = ""
    issue_description: str = ""
    status: str = Field(default="open", index=True)
    # open | in_progress | awaiting_proof | pending_human_verification | verified | rejected
    assignee: str | None = None
    is_temporary_fix: bool = False
    resolved_on_arrival: bool = False  # already fixed when maintenance arrived / self-resolved
    evidence_recommendation: str | None = None  # JSON (docs/04 §5)
    requires_human_verification: bool = False  # not visually verifiable (e.g. smells)
    created_at: str = Field(default_factory=now_iso)
    started_at: str | None = None
    completed_at: str | None = None


class Proof(SQLModel, table=True):
    __tablename__ = "proofs"
    __table_args__ = {"schema": "fixverify"}

    id: str = Field(default_factory=new_id, primary_key=True)
    work_order_id: str = Field(index=True, foreign_key="fixverify.work_orders.id")
    file_path: str
    media_type: str = "image"  # image | audio | other
    uploaded_by: str = "unknown"
    note: str | None = None
    ai_verdict: str | None = None  # relevant | irrelevant | inconclusive
    ai_reason: str | None = None  # shown to uploader on rejection
    ai_confidence: float | None = None
    human_verdict: str | None = None  # approved | rejected
    human_verifier: str | None = None
    human_notes: str | None = None
    created_at: str = Field(default_factory=now_iso)
