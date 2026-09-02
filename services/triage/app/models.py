import uuid
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


class TriageResult(SQLModel, table=True):
    __tablename__ = "results"
    __table_args__ = {"schema": "triage"}

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
    __table_args__ = {"schema": "triage"}

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
    # Set by reporting on the triage write-back; mirrored here so the
    # duplicate rate is countable without re-reading append-only results.
    duplicate_group_id: str | None = None
    created_at: str = ""
    fixed_at: str | None = None
    closed_at: str | None = None
    synced_at: str = Field(default_factory=now_iso)


class SystemicCluster(SQLModel, table=True):
    __tablename__ = "systemic_clusters"
    __table_args__ = {"schema": "triage"}

    id: str = Field(default_factory=new_id, primary_key=True)
    cluster_key: str = Field(index=True, unique=True)  # e.g. "lighting|BlockA|L3"
    issue_count: int = 0
    first_seen: str = ""
    last_seen: str = ""
    recommendation: str | None = None  # LLM preventive/prescriptive advice
    updated_at: str = Field(default_factory=now_iso)


class InsightAction(SQLModel, table=True):
    """An LLM-written `action` for one insight card.

    The id is `<card_id>@<evidence_key>`, so a card whose evidence has moved on
    misses the lookup and is rewritten rather than serving advice about issues
    that have since rolled out of the window. That is the one thing
    `SystemicCluster.recommendation` gets wrong (docs/05) and the fix costs a
    hash — the old row is left as the record of what was said at the time.
    """

    __tablename__ = "insight_actions"
    __table_args__ = {"schema": "triage"}

    id: str = Field(primary_key=True)  # f"{card_id}@{evidence_key}"
    card_id: str = Field(index=True)
    action: str
    created_at: str = Field(default_factory=now_iso)


class PatternScan(SQLModel, table=True):
    """One LLM pass over a location's free text: the recurring faults it found
    across categories the cluster key cannot span (`category|building|floor`
    keys on one category, so nothing spanning several is expressible).

    One row per location, replaced when it goes stale — including a row with an
    empty `patterns`, so "scanned, found nothing" is a stored answer and not a
    reason to scan again on the next request.
    """

    __tablename__ = "pattern_scans"
    __table_args__ = {"schema": "triage"}

    group_key: str = Field(primary_key=True)  # "building|floor"
    # JSON list of {name, issue_ids, shared_root_cause, why}. Members are the
    # issue ids the LLM's indices resolved to, so a pattern's count is the
    # length of a list we built — never a number the model stated.
    patterns: str = "[]"
    scanned_at: str = Field(default_factory=now_iso)
