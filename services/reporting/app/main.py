import json
import statistics
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import or_, text
from sqlmodel import Session, func, select

from . import ai_client, config, estimator, events
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


def resolve_scope(who: dict) -> dict:
    """What this caller is allowed to see, by role.

    Resolved once here and applied by both GET /issues and GET /stats/dashboard,
    so the table and the KPI tiles above it can never disagree about the
    population they describe.
    """
    if who["role"] == "reporter":
        return {"reporter": who["user"], "statuses": None}
    if who["role"] == "maintenance":
        return {"reporter": None, "statuses": list(config.MAINTENANCE_STATUSES)}
    return {"reporter": None, "statuses": None}  # admin: unrestricted


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
    who: dict = Depends(caller),
    status: list[Status] | None = Query(None),
    severity: list[str] | None = Query(None),
    category: str | None = None,
    building: str | None = None,
    floor: str | None = None,
    reporter: str | None = None,
    q: str | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
):
    scope = resolve_scope(who)
    stmt = select(Issue)
    if status:
        stmt = stmt.where(Issue.status.in_(status))
    if severity:
        # "untriaged" is the absence of a severity, not a value of it
        wanted = [s for s in severity if s != "untriaged"]
        clauses = []
        if wanted:
            clauses.append(Issue.severity.in_(wanted))
        if "untriaged" in severity:
            clauses.append(Issue.severity.is_(None))
        stmt = stmt.where(or_(*clauses)) if len(clauses) > 1 else stmt.where(clauses[0])
    if category:
        stmt = stmt.where(Issue.category == category)
    if building:
        stmt = stmt.where(Issue.building == building)
    if floor:
        stmt = stmt.where(Issue.floor == floor)
    if reporter:
        stmt = stmt.where(Issue.reporter_name == reporter)
    # Role scope applies on top of the caller's own filters, so a reporter
    # asking for someone else's issues still only gets their own.
    if scope["reporter"]:
        stmt = stmt.where(Issue.reporter_name == scope["reporter"])
    if scope["statuses"]:
        stmt = stmt.where(Issue.status.in_(scope["statuses"]))
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


def _parse_ts(value: str | None) -> datetime | None:
    """Timestamps are stored as ISO-8601 strings, not timestamptz."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _age_days(issue: Issue, now: datetime) -> float | None:
    created = _parse_ts(issue.created_at)
    return None if created is None else (now - created).total_seconds() / 86400


def _is_breached(issue: Issue, now: datetime) -> bool:
    """Agreed SLA rule: open longer than SLA_BREACH_DAYS and not yet settled.

    Mirrored on the client in frontend/src/lib/format.js — change both together.
    """
    if issue.status.value in config.SLA_SETTLED_STATUSES:
        return False
    age = _age_days(issue, now)
    return age is not None and age > config.SLA_BREACH_DAYS


def _month_bounds(month: str | None, now: datetime) -> tuple[str, datetime, datetime]:
    """Half-open [start, end) for a YYYY-MM key, defaulting to the current month."""
    if month:
        try:
            year, mon = (int(part) for part in month.split("-", 1))
            start = datetime(year, mon, 1, tzinfo=timezone.utc)
        except (ValueError, TypeError):
            raise HTTPException(422, "month must be formatted YYYY-MM")
    else:
        start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    end = datetime(
        start.year + (start.month == 12),
        1 if start.month == 12 else start.month + 1,
        1,
        tzinfo=timezone.utc,
    )
    return f"{start.year:04d}-{start.month:02d}", start, end


def _mean(values: list[float]) -> float | None:
    """None, not 0, for an empty set — no data is not the same as no delay."""
    return round(statistics.mean(values), 2) if values else None


def _elapsed_days(issue: Issue, stamp: str | None, since: str | None) -> float | None:
    end, start = _parse_ts(stamp), _parse_ts(since)
    if end is None or start is None:
        return None
    return (end - start).total_seconds() / 86400


def _month_metrics(issues: list[Issue], start: datetime, end: datetime) -> dict:
    """Durations averaged over the issues that reached each stamp *in this month*.

    mttc is measured directly rather than derived from mttr, because the two
    means are taken over different sets (docs/05-triage-analytics.md §Metrics).
    """
    def in_window(stamp: str | None) -> bool:
        ts = _parse_ts(stamp)
        return ts is not None and start <= ts < end

    repaired = [i for i in issues if in_window(i.fixed_at)]
    closed = [i for i in issues if in_window(i.closed_at)]
    repair_days = [
        d for d in (_elapsed_days(i, i.fixed_at, i.created_at) for i in repaired)
        if d is not None
    ]
    close_days = [
        d for d in (_elapsed_days(i, i.closed_at, i.created_at) for i in closed)
        if d is not None
    ]
    return {
        "closed": len(closed),
        # Cancelling stamps only updated_at, never closed_at, so that is the
        # only clock available for it.
        "cancelled": sum(
            1 for i in issues
            if i.status == Status.cancelled and in_window(i.updated_at)
        ),
        "verified": sum(1 for i in issues if in_window(i.verified_at)),
        "repaired": len(repaired),
        "avg_mttr_days": _mean(repair_days),
        "avg_mttc_days": _mean(close_days),
        "median_repair_days": (
            round(statistics.median(repair_days), 2) if repair_days else None
        ),
    }


@app.get("/stats/dashboard")
def stats_dashboard(
    session: Session = Depends(get_session),
    who: dict = Depends(caller),
    month: str | None = Query(None, description="YYYY-MM, defaults to current month"),
):
    """Aggregates behind the dashboard KPI tiles.

    Computed over the caller's whole scoped population rather than a page of it,
    so the headline numbers are never capped by the table's limit.
    """
    now = datetime.now(timezone.utc)
    month_key, start, end = _month_bounds(month, now)
    prev_key, prev_start, prev_end = _month_bounds(
        f"{start.year - (start.month == 1):04d}-"
        f"{12 if start.month == 1 else start.month - 1:02d}",
        now,
    )

    scope = resolve_scope(who)
    stmt = select(Issue)
    if scope["reporter"]:
        stmt = stmt.where(Issue.reporter_name == scope["reporter"])
    if scope["statuses"]:
        stmt = stmt.where(Issue.status.in_(scope["statuses"]))
    issues = list(session.exec(stmt).all())

    open_issues = [
        i for i in issues if i.status.value not in config.OPEN_EXCLUDED_STATUSES
    ]
    by_severity: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for issue in open_issues:
        key = issue.severity or "untriaged"
        by_severity[key] = by_severity.get(key, 0) + 1
        by_status[issue.status.value] = by_status.get(issue.status.value, 0) + 1
        by_category[issue.category.value] = by_category.get(issue.category.value, 0) + 1

    breached = [i for i in issues if _is_breached(i, now)]
    buckets = {"0-7": 0, "8-14": 0, "15-30": 0, "30+": 0}
    for issue in open_issues:
        age = _age_days(issue, now)
        if age is None:
            continue
        label = "0-7" if age <= 7 else "8-14" if age <= 14 else "15-30" if age <= 30 else "30+"
        buckets[label] += 1

    groups = {i.duplicate_group_id for i in issues if i.duplicate_group_id}
    this_month = _month_metrics(issues, start, end)
    prev_month = _month_metrics(issues, prev_start, prev_end)
    delta = (
        round(this_month["avg_mttr_days"] - prev_month["avg_mttr_days"], 2)
        if this_month["avg_mttr_days"] is not None
        and prev_month["avg_mttr_days"] is not None
        else None
    )

    return {
        "scope": {
            "role": who["role"],
            "user": who["user"],
            "reporter": scope["reporter"],
            "statuses": scope["statuses"],
        },
        "sla_breach_days": config.SLA_BREACH_DAYS,
        "total_count": len(issues),
        "open_count": len(open_issues),
        "open_by_severity": by_severity,
        "open_by_status": by_status,
        "open_by_category": by_category,
        "sla": {
            "breached": len(breached),
            "within": len(open_issues) - len(breached),
            "breach_rate": (
                round(len(breached) / len(open_issues), 3) if open_issues else None
            ),
        },
        "age_buckets": buckets,
        "duplicates": {
            "groups": len(groups),
            "grouped_issues": sum(1 for i in issues if i.duplicate_group_id),
        },
        "month": {
            "key": month_key,
            **this_month,
            "prev_key": prev_key,
            "prev_avg_mttr_days": prev_month["avg_mttr_days"],
            "mttr_delta_days": delta,
        },
    }


@app.get("/stats/load")
def stats_load(session: Session = Depends(get_session)):
    open_statuses = [s for s in Status if s not in (Status.closed, Status.cancelled)]
    issues = session.exec(select(Issue).where(Issue.status.in_(open_statuses))).all()
    by_severity: dict[str, int] = {}
    for issue in issues:
        key = issue.severity or "untriaged"
        by_severity[key] = by_severity.get(key, 0) + 1
    return {"open_count": len(issues), "open_by_severity": by_severity}
