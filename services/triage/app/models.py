import uuid
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


class TriageResult(SQLModel, table=True):
    __tablename__ = "triage_results"

    id: str = Field(default_factory=new_id, primary_key=True)
    issue_id: str = Field(index=True)
    suggested_severity: str
    suggested_urgency: str
    severity_rationale: str = ""
    equipment_extracted: str | None = None
    duplicate_of_issue_id: str | None = None
    duplicate_confidence: float | None = None
    systemic_flag: bool = False
    systemic_cluster_id: str | None = None
    admin_confirmed: bool = False
    admin_override_severity: str | None = None
    admin_override_urgency: str | None = None
    created_at: str = Field(default_factory=now_iso)


class IssueFact(SQLModel, table=True):
    """Denormalized analytics snapshot of an issue, synced from reporting."""

    __tablename__ = "issue_facts"

    issue_id: str = Field(primary_key=True)
    reference_no: str = ""
    category: str = Field(index=True)
    building: str = Field(index=True)
    floor: str = Field(index=True)
    room: str | None = None
    equipment_name: str | None = None
    severity: str | None = None
    status: str = "reported"
    description: str = ""
    created_at: str = ""
    fixed_at: str | None = None
    closed_at: str | None = None
    synced_at: str = Field(default_factory=now_iso)


class SystemicCluster(SQLModel, table=True):
    __tablename__ = "systemic_clusters"

    id: str = Field(default_factory=new_id, primary_key=True)
    cluster_key: str = Field(index=True, unique=True)  # e.g. "lighting|BlockA|L3"
    issue_count: int = 0
    first_seen: str = ""
    last_seen: str = ""
    recommendation: str | None = None  # LLM preventive/prescriptive advice
    updated_at: str = Field(default_factory=now_iso)
