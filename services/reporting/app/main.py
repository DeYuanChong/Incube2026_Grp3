import json

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlmodel import Session, func, select

from . import ai_client, estimator, events
from .db import get_session, init_db
from .models import TRANSITIONS, Issue, IssueEvent, Status, now_iso
from .schemas import (
    CancelRequest,
    CloseRequest,
    IssueCreate,
    IssueUpdate,
    StatusChange,
    TriageResultIn,
)

app = FastAPI(title="Reporting Service", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


@app.on_event("startup")
def startup() -> None:
    init_db()


def caller(x_user: str = Header("anonymous"), x_role: str = Header("reporter")):
    return {"user": x_user, "role": x_role}


def _log_event(session: Session, issue_id: str, event_type: str, actor: str, detail: dict):
    session.add(
        IssueEvent(
            issue_id=issue_id, event_type=event_type, actor=actor, detail=json.dumps(detail)
        )
    )


def _open_count(session: Session) -> int:
    open_statuses = [s for s in Status if s not in (Status.closed, Status.cancelled)]
    return session.exec(
        select(func.count()).select_from(Issue).where(Issue.status.in_(open_statuses))
    ).one()


def _next_reference_no(session: Session) -> str:
    count = session.exec(select(func.count()).select_from(Issue)).one()
    return f"DEF-2026-{count + 1:04d}"


@app.get("/health")
def health():
    return {"service": "reporting", "status": "ok"}


@app.post("/issues", status_code=201)
def create_issue(
    body: IssueCreate,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    who: dict = Depends(caller),
):
    issue = Issue(
        **body.model_dump(),
        reference_no=_next_reference_no(session),
        reporter_name=who["user"],
    )

    # Smart categorization — suggestion only, never overrides the user (doc 04 §1)
    location = f"{body.building} / {body.floor}" + (f" / {body.room}" if body.room else "")
    suggestion = ai_client.suggest_category(
        body.title, body.description, location, body.category.value
    )
    if suggestion:
        issue.ai_suggested_category = suggestion["category"]
        issue.ai_category_confidence = suggestion["confidence"]

    # Expectation management: ETA from category + live open-issue load (doc 04 §2)
    days, basis = estimator.estimate(body.category.value, None, _open_count(session))
    issue.estimated_resolution_days = days
    issue.estimate_basis = basis

    session.add(issue)
    _log_event(session, issue.id, "created", who["user"], {"category": body.category.value})
    session.commit()
    session.refresh(issue)

    background.add_task(
        events.publish,
        "issue.created",
        {"issue_id": issue.id, "reference_no": issue.reference_no,
         "category": issue.category.value, "building": issue.building,
         "floor": issue.floor, "reporter": issue.reporter_name, "title": issue.title},
    )
    return issue


@app.get("/issues")
def list_issues(
    session: Session = Depends(get_session),
    status: Status | None = None,
    category: str | None = None,
    building: str | None = None,
    floor: str | None = None,
    reporter: str | None = None,
    q: str | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
):
    stmt = select(Issue)
    if status:
        stmt = stmt.where(Issue.status == status)
    if category:
        stmt = stmt.where(Issue.category == category)
    if building:
        stmt = stmt.where(Issue.building == building)
    if floor:
        stmt = stmt.where(Issue.floor == floor)
    if reporter:
        stmt = stmt.where(Issue.reporter_name == reporter)
    if q:
        # Fuzzy search: pg_trgm word similarity (typo-tolerant) OR plain substring
        # match, ranked by similarity (GIN index created in db.init_db)
        fuzzy = text(
            "(word_similarity(:q, title || ' ' || description) > 0.3"
            " OR title ILIKE :like OR description ILIKE :like)"
        ).bindparams(q=q, like=f"%{q}%")
        rank = text(
            "word_similarity(:rq, title || ' ' || description) DESC"
        ).bindparams(rq=q)
        stmt = stmt.where(fuzzy).order_by(rank)
    else:
        stmt = stmt.order_by(Issue.created_at.desc())  # type: ignore[attr-defined]
    stmt = stmt.limit(limit).offset(offset)
    return session.exec(stmt).all()


@app.get("/issues/{issue_id}")
def get_issue(issue_id: str, session: Session = Depends(get_session)):
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(404, "issue not found")
    timeline = session.exec(
        select(IssueEvent).where(IssueEvent.issue_id == issue_id).order_by(IssueEvent.created_at)
    ).all()
    return {"issue": issue, "timeline": timeline}


@app.patch("/issues/{issue_id}")
def update_issue(
    issue_id: str,
    body: IssueUpdate,
    session: Session = Depends(get_session),
    who: dict = Depends(caller),
):
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(404, "issue not found")
    if issue.status != Status.reported:
        raise HTTPException(409, "issue can only be edited while status is 'reported'")
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(issue, key, value)
    issue.updated_at = now_iso()
    _log_event(session, issue_id, "updated", who["user"], changes)
    session.commit()
    session.refresh(issue)
    return issue


@app.post("/issues/{issue_id}/accept-suggested-category")
def accept_suggested_category(
    issue_id: str, session: Session = Depends(get_session), who: dict = Depends(caller)
):
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(404, "issue not found")
    if not issue.ai_suggested_category:
        raise HTTPException(409, "no AI category suggestion on this issue")
    issue.category = issue.ai_suggested_category
    issue.category_source = "ai_accepted"
    issue.updated_at = now_iso()
    _log_event(session, issue_id, "category_accepted", who["user"],
               {"category": issue.category.value})
    session.commit()
    session.refresh(issue)
    return issue


@app.post("/issues/{issue_id}/triage-result")
def apply_triage_result(
    issue_id: str,
    body: TriageResultIn,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """Internal: called by the triage service."""
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(404, "issue not found")
    issue.severity = body.severity
    issue.urgency = body.urgency
    if body.is_critical_system is not None:
        issue.is_critical_system = body.is_critical_system
    if body.equipment_name:
        issue.equipment_name = body.equipment_name
    if body.duplicate_group_id:
        issue.duplicate_group_id = body.duplicate_group_id
    if body.duplicate_count:
        issue.duplicate_count = body.duplicate_count
    if issue.status == Status.reported:
        issue.status = Status.triaged
        issue.triaged_at = now_iso()
    # Severity is now known — refine the reporter-facing ETA
    days, basis = estimator.estimate(issue.category.value, body.severity, _open_count(session))
    issue.estimated_resolution_days = days
    issue.estimate_basis = basis
    issue.updated_at = now_iso()
    _log_event(session, issue_id, "triaged", "triage-service",
               {"severity": body.severity, "urgency": body.urgency})
    session.commit()
    session.refresh(issue)
    background.add_task(
        events.publish, "issue.triaged",
        {"issue_id": issue.id, "reference_no": issue.reference_no,
         "severity": issue.severity, "urgency": issue.urgency,
         "reporter": issue.reporter_name, "title": issue.title},
    )
    return issue


@app.post("/issues/{issue_id}/status")
def change_status(
    issue_id: str,
    body: StatusChange,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    who: dict = Depends(caller),
):
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(404, "issue not found")
    if body.status not in TRANSITIONS[issue.status]:
        raise HTTPException(409, f"invalid transition {issue.status.value} → {body.status.value}")
    issue.status = body.status
    stamp = now_iso()
    if body.status == Status.in_progress and not issue.work_started_at:
        issue.work_started_at = stamp
    elif body.status == Status.pending_verification:
        issue.fixed_at = stamp
    elif body.status == Status.verified:
        issue.verified_at = stamp
    issue.updated_at = stamp
    _log_event(session, issue_id, f"status:{body.status.value}", who["user"],
               {"detail": body.detail})
    session.commit()
    session.refresh(issue)
    background.add_task(
        events.publish, "issue.status_changed",
        {"issue_id": issue.id, "reference_no": issue.reference_no,
         "status": issue.status.value, "reporter": issue.reporter_name,
         "title": issue.title, "detail": body.detail},
    )
    return issue


@app.post("/issues/{issue_id}/close")
def close_issue(
    issue_id: str,
    body: CloseRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    who: dict = Depends(caller),
):
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(404, "issue not found")
    if issue.status != Status.verified:
        raise HTTPException(409, "only verified issues can be closed")
    issue.status = Status.closed
    issue.closed_by = body.closed_by
    issue.resolution_type = body.resolution_type or issue.resolution_type
    issue.resolution_notes = body.resolution_notes or issue.resolution_notes
    issue.closed_at = now_iso()
    issue.updated_at = issue.closed_at
    _log_event(session, issue_id, "closed", who["user"], {"closed_by": body.closed_by})
    session.commit()
    session.refresh(issue)
    background.add_task(
        events.publish, "issue.closed",
        {"issue_id": issue.id, "reference_no": issue.reference_no,
         "closed_by": body.closed_by, "reporter": issue.reporter_name,
         "title": issue.title},
    )
    return issue


@app.post("/issues/{issue_id}/cancel")
def cancel_issue(
    issue_id: str,
    body: CancelRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    who: dict = Depends(caller),
):
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(404, "issue not found")
    if issue.status != Status.reported:
        raise HTTPException(409, "only newly reported issues can be cancelled")
    issue.status = Status.cancelled
    issue.cancellation_reason = body.reason
    issue.updated_at = now_iso()
    _log_event(session, issue_id, "cancelled", who["user"], {"reason": body.reason})
    session.commit()
    session.refresh(issue)
    # Cancelling is a status change like any other. It published nothing, so
    # triage's snapshot kept the issue at "reported" forever and went on
    # counting it as open work (docs/05 §Profiles).
    background.add_task(
        events.publish, "issue.status_changed",
        {"issue_id": issue.id, "reference_no": issue.reference_no,
         "status": issue.status.value, "reporter": issue.reporter_name,
         "title": issue.title, "detail": body.reason},
    )
    return issue


@app.get("/stats/load")
def stats_load(session: Session = Depends(get_session)):
    open_statuses = [s for s in Status if s not in (Status.closed, Status.cancelled)]
    issues = session.exec(select(Issue).where(Issue.status.in_(open_statuses))).all()
    by_severity: dict[str, int] = {}
    for issue in issues:
        key = issue.severity or "untriaged"
        by_severity[key] = by_severity.get(key, 0) + 1
    return {"open_count": len(issues), "open_by_severity": by_severity}
