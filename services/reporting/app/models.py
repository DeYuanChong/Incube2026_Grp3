import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlmodel import Field, SQLModel


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


class Category(str, Enum):
    air_conditioning = "air_conditioning"
    lighting = "lighting"
    cleanliness = "cleanliness"
    toilet = "toilet"
    physical_security = "physical_security"
    others = "others"


class Status(str, Enum):
    reported = "reported"
    triaged = "triaged"
    in_progress = "in_progress"
    pending_verification = "pending_verification"
    verified = "verified"
    closed = "closed"
    cancelled = "cancelled"


# Valid state-machine transitions (docs/00-design-overview.md)
TRANSITIONS: dict[Status, set[Status]] = {
    Status.reported: {Status.triaged, Status.cancelled},
    # triaged → pending_verification: resolved on arrival (someone already
    # cleaned up / reporter self-serviced) — proof still required, work never starts
    Status.triaged: {Status.in_progress, Status.pending_verification},
    Status.in_progress: {Status.pending_verification},
    Status.pending_verification: {Status.verified, Status.in_progress},
    Status.verified: {Status.closed, Status.in_progress},
    Status.closed: set(),
    Status.cancelled: set(),
}


class Issue(SQLModel, table=True):
    __tablename__ = "issues"
    __table_args__ = {"schema": "reporting"}

    id: str = Field(default_factory=new_id, primary_key=True)
    reference_no: str = Field(index=True, unique=True)
    category: Category
    ai_suggested_category: Category | None = None
    ai_category_confidence: float | None = None
    category_source: str = "user"  # user | ai_accepted
    title: str
    description: str
    building: str
    floor: str
    room: str | None = None
    equipment_name: str | None = None
    reporter_name: str
    status: Status = Field(default=Status.reported, index=True)
    severity: str | None = Field(default=None, index=True)  # low|medium|high|critical
    urgency: str | None = None  # routine|urgent|emergency
    is_critical_system: bool = False
    duplicate_group_id: str | None = Field(default=None, index=True)
    duplicate_count: int = 1
    estimated_resolution_days: float | None = None
    estimate_basis: str | None = None
    ai_suggested_title: str | None = None
    ai_suggested_description: str | None = None
    photo_note: str | None = None
    photo_mismatch_reason: str | None = None
    resolution_type: str | None = None
    resolution_notes: str | None = None
    cancellation_reason: str | None = None
    closed_by: str | None = None  # reporter | auto | admin
    created_at: str = Field(default_factory=now_iso)
    triaged_at: str | None = None
    work_started_at: str | None = None
    fixed_at: str | None = None
    verified_at: str | None = None
    closed_at: str | None = None
    updated_at: str = Field(default_factory=now_iso)


class IssueEvent(SQLModel, table=True):
    __tablename__ = "issue_events"
    __table_args__ = {"schema": "reporting"}

    id: str = Field(default_factory=new_id, primary_key=True)
    issue_id: str = Field(index=True, foreign_key="reporting.issues.id")
    event_type: str
    detail: str = "{}"  # JSON blob
    actor: str = "system"
    created_at: str = Field(default_factory=now_iso)


class IssuePhoto(SQLModel, table=True):
    __tablename__ = "issue_photos"
    __table_args__ = {"schema": "reporting"}

    id: str = Field(default_factory=new_id, primary_key=True)
    issue_id: str = Field(index=True, foreign_key="reporting.issues.id")
    file_path: str
    uploaded_by: str = "unknown"
    checked_against_category: Category
    ai_verdict: str | None = None  # aligned | misaligned | inconclusive
    ai_confidence: float | None = None
    ai_reason: str | None = None
    ai_suggested_category: Category | None = None
    ai_suggested_title: str | None = None
    ai_suggested_description: str | None = None
    created_at: str = Field(default_factory=now_iso)
