import logging

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import Session, select

from . import analytics, config, insights, pipeline
from .db import engine, get_session, init_db
from .models import TriageResult

log = logging.getLogger(__name__)
app = FastAPI(title="Triage Service", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health():
    return {"service": "triage", "status": "ok"}


@app.post("/run/{issue_id}")
def run_triage(issue_id: str, session: Session = Depends(get_session)):
    try:
        return pipeline.to_response(session, pipeline.run_triage(session, issue_id))
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"could not fetch issue from reporting: {exc}")


@app.get("/results/{issue_id}")
def get_result(issue_id: str, session: Session = Depends(get_session)):
    result = session.exec(
        select(TriageResult)
        .where(TriageResult.issue_id == issue_id)
        .order_by(TriageResult.created_at.desc())  # type: ignore[attr-defined]
    ).first()
    if not result:
        raise HTTPException(404, "no triage result for this issue")
    return pipeline.to_response(session, result)


class ConfirmRequest(BaseModel):
    severity: str | None = None
    urgency: str | None = None


@app.post("/results/{issue_id}/confirm")
def confirm_result(
    issue_id: str,
    body: ConfirmRequest,
    session: Session = Depends(get_session),
    x_user: str = Header("admin"),
):
    result = session.exec(
        select(TriageResult)
        .where(TriageResult.issue_id == issue_id)
        .order_by(TriageResult.created_at.desc())  # type: ignore[attr-defined]
    ).first()
    if not result:
        raise HTTPException(404, "no triage result for this issue")
    result.admin_confirmed = True
    result.admin_override_severity = body.severity
    result.admin_override_urgency = body.urgency
    session.add(result)
    session.commit()

    severity = body.severity or result.suggested_severity
    urgency = body.urgency or result.suggested_urgency
    try:
        httpx.post(
            f"{config.REPORTING_URL}/issues/{issue_id}/triage-result",
            json={"severity": severity, "urgency": urgency,
                  "equipment_name": result.equipment_extracted},
            timeout=10,
        ).raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(502, "confirmed locally but failed to update reporting")
    session.refresh(result)
    return pipeline.to_response(session, result)


@app.get("/")
def overview(
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    by: str = Query("location", pattern="^(location|category|equipment)$"),
):
    """The whole analytics output, in one call (docs/05).

    Clusters are ranked by how many members they have *now*, not by the peak the
    detector last recorded — a remediated cluster stops accruing members and drops
    off the list instead of topping it forever. MTBF and MTTR are computed here to
    feed `insights` but are not returned: raw metrics are generated elsewhere, and
    what this endpoint owes a caller is the findings over them.

    `by` shapes the `profiles` block only. The cards span locations, assets and
    assignees whatever it is set to, because a finding is not the admin's choice
    of grouping.

    ponytail: `analytics.insights` recomputes the three blocks below rather than
    being handed them, so a request scans the snapshot a few times over. Pass the
    computed rows in if the snapshot ever grows enough for that to show.
    """
    cards = analytics.insights(session)
    # The LLM work behind the cards happens after the response, never in it: a
    # card with no written action serves its template and is filled for next
    # time, which is the same "null until it lands" rule systemic_payload
    # follows. Bounded per run in config, so a burst of reads cannot fan out.
    background.add_task(_refresh_insights)
    return {
        "group_by": analytics.group_for(by),
        "systemic": analytics.systemic_clusters(session),
        "profiles": analytics.profiles(session, by),
        "vendor_performance": analytics.vendor_performance(session),
        # Ranked worst-first and cut here, not in the rules: a caller wants the
        # worst few, and `insight_count` says how much was behind them.
        "insights": cards[:insights.LIMIT],
        "insight_count": len(cards),
    }


@app.post("/analytics/sync")
def sync_snapshot(session: Session = Depends(get_session)):
    """Full refresh of the issue_facts snapshot from reporting."""
    resp = httpx.get(f"{config.REPORTING_URL}/issues", params={"limit": 500}, timeout=30)
    resp.raise_for_status()
    issues = resp.json()
    for issue in issues:
        pipeline.sync_issue_fact(session, issue)
    session.commit()
    return {"synced": len(issues)}


def _refresh_insights() -> None:
    """Background fill with its own DB session, as `_handle_event` has."""
    from sqlmodel import Session as _Session

    with _Session(engine) as session:
        try:
            analytics.refresh_insights(session)
        except Exception:
            log.warning("insight refresh failed", exc_info=True)


def _handle_event(event: dict) -> None:
    """Background webhook handling with its own DB session."""
    from sqlmodel import Session as _Session

    event_type = event.get("event_type")
    issue_id = (event.get("payload") or {}).get("issue_id")
    with _Session(engine) as session:
        try:
            if event_type == "issue.created" and issue_id:
                pipeline.run_triage(session, issue_id)
            # Both mean "the issue's state moved"; the fact is re-synced whole
            # either way. Without status_changed a cancelled or reopened issue
            # stays "reported" in the snapshot, where it goes on counting as an
            # open duplicate candidate and a live cluster member.
            elif event_type in ("issue.closed", "issue.status_changed") and issue_id:
                resp = httpx.get(f"{config.REPORTING_URL}/issues/{issue_id}", timeout=10)
                resp.raise_for_status()
                pipeline.sync_issue_fact(session, resp.json()["issue"])
                session.commit()
        except Exception:
            log.warning("event handling failed for %s", event_type, exc_info=True)


@app.post("/webhooks/events")
def webhook(event: dict, background: BackgroundTasks):
    background.add_task(_handle_event, event)
    return {"accepted": True}
