import json
import os
import uuid

from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlmodel import Session, func, select

from . import ai_client, config, estimator, events
from .db import get_session, init_db
from .models import TRANSITIONS, Category, Issue, IssueEvent, IssuePhoto, Status, now_iso
from .schemas import (
    CancelRequest,
    CloseRequest,
    IssueCreate,
    IssueUpdate,
    StatusChange,
    SuggestDescriptionRequest,
    SuggestDescriptionResponse,
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


def _apply_photo_signal(session: Session, issue: Issue) -> None:
    """Recomputes ai_suggested_category/title/description/photo_note from
    scratch across all of the issue's photos (docs/04 §7 decision matrix)."""
    photos = session.exec(select(IssuePhoto).where(IssuePhoto.issue_id == issue.id)).all()

    votes: dict[Category, int] = {}
    for ph in photos:
        if ph.ai_verdict == "aligned":
            vote = ph.checked_against_category
        elif ph.ai_verdict == "misaligned" and ph.ai_suggested_category:
            vote = ph.ai_suggested_category
        else:
            continue
        votes[vote] = votes.get(vote, 0) + 1
    total = sum(votes.values())
    majority = next((cat for cat, n in votes.items() if n * 2 > total), None)

    u, t, p = issue.category, issue.ai_suggested_category or issue.category, majority

    if p is None:
        pass  # baseline unchanged — leave ai_suggested_category as-is
    elif p == t == u:
        issue.ai_suggested_category, issue.photo_note = None, None
    elif p == t != u:
        issue.ai_suggested_category, issue.photo_note = t, None
    elif p == u != t:
        issue.ai_suggested_category = None
        issue.photo_note = "Your description reads a bit differently than your photo — worth a quick check?"
    else:  # three-way disagreement: trust the description
        issue.ai_suggested_category, issue.photo_note = (t if t != u else None), None
        _log_event(session, issue.id, "photo_category_conflict", "system",
                   {"user_category": u.value, "text_suggested": t.value, "photo_voted": p.value})

    candidates = [ph for ph in photos if ph.ai_verdict == "misaligned"
                  and ph.ai_confidence is not None
                  and ph.ai_confidence >= config.PHOTO_MISALIGN_CONFIDENCE]
    leading = max(candidates, key=lambda ph: ph.ai_confidence, default=None)
    if leading and (leading.ai_suggested_title or leading.ai_suggested_description):
        issue.ai_suggested_title = leading.ai_suggested_title
        issue.ai_suggested_description = leading.ai_suggested_description
        issue.photo_mismatch_reason = leading.ai_reason
    else:
        issue.ai_suggested_title, issue.ai_suggested_description, issue.photo_mismatch_reason = None, None, None


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
    if not body.ack_confirmed:
        raise HTTPException(422, "acknowledgement is required")
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


@app.post("/issues/suggest-description", response_model=SuggestDescriptionResponse)
def suggest_description(body: SuggestDescriptionRequest):
    location = None
    if body.building:
        location = body.building + (f" / {body.floor}" if body.floor else "")
    suggestion = ai_client.suggest_description(
        body.title, body.category.value if body.category else None, location,
    )
    if not suggestion:
        return SuggestDescriptionResponse(description=None, confidence=None)
    return SuggestDescriptionResponse(**suggestion)


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


@app.get("/issues/estimate")
def estimate_issue(category: Category, session: Session = Depends(get_session)):
    days, basis = estimator.estimate(category.value, None, _open_count(session))
    return {"estimated_resolution_days": days, "estimate_basis": basis}


@app.get("/issues/{issue_id}")
def get_issue(issue_id: str, session: Session = Depends(get_session)):
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(404, "issue not found")
    timeline = session.exec(
        select(IssueEvent).where(IssueEvent.issue_id == issue_id).order_by(IssueEvent.created_at)
    ).all()
    photos = session.exec(
        select(IssuePhoto).where(IssuePhoto.issue_id == issue_id).order_by(IssuePhoto.created_at)
    ).all()
    return {"issue": issue, "timeline": timeline, "photos": photos}


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
    # stale-suggestion rule: text/location changed, prior AI reads no longer apply
    issue.ai_suggested_category = None
    issue.ai_suggested_title = None
    issue.ai_suggested_description = None
    issue.photo_note = None
    issue.photo_mismatch_reason = None
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


@app.post("/issues/{issue_id}/accept-suggested-title")
def accept_suggested_title(
    issue_id: str, session: Session = Depends(get_session), who: dict = Depends(caller)
):
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(404, "issue not found")
    if not issue.ai_suggested_title:
        raise HTTPException(409, "no AI title suggestion on this issue")
    issue.title = issue.ai_suggested_title
    issue.ai_suggested_title = None
    issue.updated_at = now_iso()
    _log_event(session, issue_id, "title_accepted", who["user"], {"title": issue.title})
    session.commit()
    session.refresh(issue)
    return issue


@app.post("/issues/{issue_id}/accept-suggested-description")
def accept_suggested_description(
    issue_id: str, session: Session = Depends(get_session), who: dict = Depends(caller)
):
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(404, "issue not found")
    if not issue.ai_suggested_description:
        raise HTTPException(409, "no AI description suggestion on this issue")
    issue.description = issue.ai_suggested_description
    issue.ai_suggested_description = None
    issue.updated_at = now_iso()
    _log_event(session, issue_id, "description_accepted", who["user"], {})
    session.commit()
    session.refresh(issue)
    return issue


@app.post("/issues/{issue_id}/photos", status_code=201)
def upload_photo(
    issue_id: str,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    who: dict = Depends(caller),
):
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(404, "issue not found")
    if issue.status != Status.reported:
        raise HTTPException(409, "photos can only be added while status is 'reported'")
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(422, "file must be an image")

    ext = os.path.splitext(file.filename or "")[1] or ".jpg"
    path = os.path.join(config.UPLOAD_DIR, f"{uuid.uuid4()}{ext}")
    with open(path, "wb") as out:
        out.write(file.file.read())

    result = ai_client.verify_photo(path, issue.category.value, issue.title, issue.description)
    photo = IssuePhoto(
        issue_id=issue_id, file_path=path, uploaded_by=who["user"],
        checked_against_category=issue.category,
        ai_verdict=result["verdict"], ai_confidence=result["confidence"], ai_reason=result["reason"],
        ai_suggested_category=result["suggested_category"],
        ai_suggested_title=result["suggested_title"], ai_suggested_description=result["suggested_description"],
    )
    session.add(photo)
    _apply_photo_signal(session, issue)
    issue.updated_at = now_iso()
    _log_event(session, issue_id, "photo_uploaded", who["user"], {"verdict": result["verdict"]})
    session.commit()
    session.refresh(issue)
    session.refresh(photo)
    background.add_task(
        events.publish, "issue.photo_uploaded",
        {"issue_id": issue.id, "reference_no": issue.reference_no, "photo_id": photo.id},
    )
    return {"issue": issue, "photo": photo}


@app.get("/issues/{issue_id}/photos/{photo_id}/file")
def get_photo_file(issue_id: str, photo_id: str, session: Session = Depends(get_session)):
    photo = session.get(IssuePhoto, photo_id)
    if not photo or photo.issue_id != issue_id:
        raise HTTPException(404, "photo not found")
    return FileResponse(photo.file_path)


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
