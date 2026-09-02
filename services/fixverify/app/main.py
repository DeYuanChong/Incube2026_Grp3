import json
import logging
import os
import uuid

import httpx
from fastapi import (
    BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from . import ai_client, config, dedupe, events
from .db import engine, get_session, init_db
from .models import Proof, WorkOrder, now_iso

log = logging.getLogger(__name__)
app = FastAPI(title="Fix & Verify Service", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


@app.on_event("startup")
def startup() -> None:
    init_db()


def _set_issue_status(issue_id: str, status: str, detail: str | None = None) -> None:
    try:
        httpx.post(
            f"{config.REPORTING_URL}/issues/{issue_id}/status",
            json={"status": status, "detail": detail},
            headers={"X-User": "fixverify-service", "X-Role": "maintenance"},
            timeout=10,
        ).raise_for_status()
    except httpx.HTTPError:
        log.warning("failed to set issue %s status=%s", issue_id, status, exc_info=True)


@app.get("/health")
def health():
    return {"service": "fixverify", "status": "ok"}


@app.get("/work-orders")
def list_work_orders(
    session: Session = Depends(get_session),
    status: str | None = None,
    assignee: str | None = None,
    issue_id: str | None = None,
):
    stmt = select(WorkOrder)
    if status:
        stmt = stmt.where(WorkOrder.status == status)
    if assignee:
        stmt = stmt.where(WorkOrder.assignee == assignee)
    if issue_id:
        stmt = stmt.where(WorkOrder.issue_id == issue_id)
    return session.exec(stmt.order_by(WorkOrder.created_at.desc())).all()  # type: ignore[attr-defined]


@app.get("/work-orders/{wo_id}")
def get_work_order(wo_id: str, session: Session = Depends(get_session)):
    wo = session.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(404, "work order not found")
    # staged proofs are not part of the record until they are submitted
    proofs = session.exec(
        select(Proof)
        .where(Proof.work_order_id == wo_id, Proof.staged == False)  # noqa: E712
        .order_by(Proof.created_at)
    ).all()
    return {"work_order": wo, "proofs": proofs}


class StartRequest(BaseModel):
    assignee: str


@app.post("/work-orders/{wo_id}/start")
def start_work_order(
    wo_id: str,
    body: StartRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    wo = session.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(404, "work order not found")
    if wo.status not in ("open", "rejected"):
        raise HTTPException(409, f"cannot start a work order in status '{wo.status}'")
    wo.status = "in_progress"
    wo.assignee = body.assignee
    wo.started_at = wo.started_at or now_iso()
    session.commit()
    session.refresh(wo)
    _set_issue_status(wo.issue_id, "in_progress", f"assigned to {body.assignee}")
    background.add_task(events.publish, "work_order.started",
                        {"issue_id": wo.issue_id, "work_order_id": wo.id,
                         "assignee": body.assignee})
    return wo


@app.get("/work-orders/{wo_id}/evidence-recommendation")
def evidence_recommendation(wo_id: str, session: Session = Depends(get_session)):
    """LLM proof-of-work recommendation (docs/04 §5) — cached on the work order."""
    wo = session.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(404, "work order not found")
    if wo.evidence_recommendation:
        return json.loads(wo.evidence_recommendation)
    resp = httpx.get(f"{config.REPORTING_URL}/issues/{wo.issue_id}", timeout=10)
    resp.raise_for_status()
    issue = resp.json()["issue"]
    rec = ai_client.recommend_evidence(issue["category"], issue["title"], issue["description"])
    if not rec.pop("fallback", False):
        # Only cache real AI output — a fallback would otherwise be served
        # forever even after the AI endpoint comes back up
        wo.evidence_recommendation = json.dumps(rec)
        wo.requires_human_verification = bool(rec.get("requires_human_verification", False))
        session.commit()
    return rec


@app.post("/work-orders/{wo_id}/proofs", status_code=201)
def stage_proof(
    wo_id: str,
    file: UploadFile = File(...),
    note: str | None = Form(None),
    session: Session = Depends(get_session),
    x_user: str = Header("unknown"),
):
    """Phase 1 of two: store the file, run the AI relevance check, stop there.

    Nothing is put forward yet — the work order and the issue are untouched and
    no event fires. The AI's verdict is advisory: it is returned to the uploader
    so they can decide, and even an `irrelevant` verdict does not block them
    (admin sign-off downstream is the real gate). The uploader then calls
    POST /proofs/{id}/submit to put it forward, or DELETE /proofs/{id} to
    discard it.
    """
    wo = session.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(404, "work order not found")
    if wo.status not in ("open", "in_progress", "awaiting_proof"):
        raise HTTPException(409, f"work order status '{wo.status}' does not accept proofs")

    ext = os.path.splitext(file.filename or "")[1] or ".bin"
    path = os.path.join(config.UPLOAD_DIR, f"{uuid.uuid4()}{ext}")
    with open(path, "wb") as out:
        out.write(file.file.read())
    content_type = file.content_type or ""
    media_type = ("image" if content_type.startswith("image/")
                  else "audio" if content_type.startswith("audio/") else "other")

    proof = Proof(work_order_id=wo_id, file_path=path, media_type=media_type,
                  uploaded_by=x_user, note=note, staged=True)

    if media_type == "image" and not wo.requires_human_verification:
        verdict = ai_client.check_relevance(
            path, wo.issue_description, wo.evidence_recommendation or "", note or ""
        )
    else:
        # Non-image proof or a defect that isn't visually verifiable → human judges
        verdict = {"verdict": "inconclusive", "confidence": 0.0,
                   "reason": "Not automatically verifiable; routed to human review."}

    proof.ai_verdict = verdict["verdict"]
    proof.ai_reason = verdict["reason"]
    proof.ai_confidence = verdict["confidence"]
    session.add(proof)
    session.commit()
    session.refresh(proof)
    return proof


@app.post("/proofs/{proof_id}/submit")
def submit_proof(
    proof_id: str,
    background: BackgroundTasks,
    note: str | None = Form(None),
    session: Session = Depends(get_session),
    x_user: str = Header("unknown"),
):
    """Phase 2: the uploader stands behind a staged proof and puts it forward.

    This is where the work order and the issue finally move. A proof submitted
    against an 'open' work order means the defect was already resolved on
    arrival (someone else fixed it / the reporter self-serviced): the issue
    jumps triaged → pending_verification without ever entering in_progress.
    """
    proof = session.get(Proof, proof_id)
    if not proof:
        raise HTTPException(404, "proof not found")
    if not proof.staged:
        raise HTTPException(409, "proof has already been submitted")
    wo = session.get(WorkOrder, proof.work_order_id)
    if not wo:
        raise HTTPException(404, "work order not found")
    if wo.status not in ("open", "in_progress", "awaiting_proof"):
        raise HTTPException(409, f"work order status '{wo.status}' does not accept proofs")

    # The note may have been written or edited after the AI check ran; the
    # stored note is what the uploader finally meant, even if the model saw less.
    if note is not None:
        proof.note = note
    proof.staged = False

    resolved_on_arrival = wo.status == "open"
    wo.status = "pending_human_verification"
    if resolved_on_arrival:
        wo.resolved_on_arrival = True
        wo.assignee = wo.assignee or x_user
    session.commit()
    session.refresh(proof)

    _set_issue_status(
        wo.issue_id, "pending_verification",
        "already resolved on arrival — proof uploaded" if resolved_on_arrival
        else "proof of work uploaded",
    )
    background.add_task(events.publish, "proof.uploaded",
                        {"issue_id": wo.issue_id, "work_order_id": wo.id,
                         "proof_id": proof.id, "uploaded_by": x_user,
                         "ai_verdict": proof.ai_verdict,
                         "resolved_on_arrival": resolved_on_arrival,
                         "passed_relevance": proof.ai_verdict == "relevant"})
    return proof


@app.delete("/proofs/{proof_id}", status_code=204)
def discard_proof(proof_id: str, session: Session = Depends(get_session)):
    """Throw away a staged proof the uploader decided not to put forward.

    Only ever staged ones: a submitted proof is part of the record and its
    rejection is expressed through human verification, not deletion.
    """
    proof = session.get(Proof, proof_id)
    if not proof:
        raise HTTPException(404, "proof not found")
    if not proof.staged:
        raise HTTPException(409, "a submitted proof cannot be discarded")
    path = proof.file_path
    session.delete(proof)
    session.commit()
    try:
        os.remove(path)
    except OSError:
        # The row is gone either way; a stray file is not worth failing on.
        log.warning("could not remove discarded proof file %s", path, exc_info=True)
    return Response(status_code=204)


@app.get("/proofs/{proof_id}/file")
def proof_file(proof_id: str, session: Session = Depends(get_session)):
    proof = session.get(Proof, proof_id)
    if not proof or not os.path.exists(proof.file_path):
        raise HTTPException(404, "proof file not found")
    return FileResponse(proof.file_path)


class HumanVerify(BaseModel):
    approved: bool
    notes: str | None = None


@app.post("/proofs/{proof_id}/human-verify")
def human_verify(
    proof_id: str,
    body: HumanVerify,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    x_user: str = Header("admin"),
):
    """Final human verification — AI relevance was only a pre-filter."""
    proof = session.get(Proof, proof_id)
    if not proof:
        raise HTTPException(404, "proof not found")
    if proof.staged:
        # Nobody has put this forward yet — there is nothing to sign off on.
        raise HTTPException(409, "proof has not been submitted yet")
    wo = session.get(WorkOrder, proof.work_order_id)
    assert wo is not None
    proof.human_verdict = "approved" if body.approved else "rejected"
    proof.human_verifier = x_user
    proof.human_notes = body.notes

    if body.approved:
        wo.status = "verified"
        wo.completed_at = now_iso()
        session.commit()
        _set_issue_status(wo.issue_id, "verified", f"verified by {x_user}")
        background.add_task(events.publish, "issue.verified",
                            {"issue_id": wo.issue_id, "work_order_id": wo.id,
                             "verifier": x_user})
    else:
        wo.status = "awaiting_proof"
        session.commit()
        _set_issue_status(wo.issue_id, "in_progress", "verification rejected; back to work")
        background.add_task(events.publish, "proof.rejected",
                            {"issue_id": wo.issue_id, "work_order_id": wo.id,
                             "proof_id": proof.id, "uploaded_by": proof.uploaded_by,
                             "reason": body.notes or "Rejected by verifier"})
    session.refresh(proof)
    return proof


def _handle_event(event: dict) -> None:
    from sqlmodel import Session as _Session

    if event.get("event_type") != "issue.triaged":
        return
    payload = event.get("payload") or {}
    issue_id = payload.get("issue_id")
    if not issue_id:
        return
    with _Session(engine) as session:
        existing = session.exec(
            select(WorkOrder).where(WorkOrder.issue_id == issue_id)
        ).first()
        if existing:
            return  # idempotent on re-delivery / re-triage
        try:
            resp = httpx.get(f"{config.REPORTING_URL}/issues/{issue_id}", timeout=10)
            resp.raise_for_status()
            issue = resp.json()["issue"]
        except httpx.HTTPError:
            log.warning("could not fetch issue %s for work order", issue_id, exc_info=True)
            return

        # One defect, one dispatch: a duplicate rides the group primary's work
        # order rather than sending maintenance out twice (docs/05).
        group_id = issue.get("duplicate_group_id")
        primary = session.exec(
            select(WorkOrder).where(WorkOrder.issue_id == group_id)
        ).first() if group_id else None
        if dedupe.is_covered_by_primary(
            issue_id, group_id, primary.status if primary else None
        ):
            log.info(
                "issue %s is a duplicate of %s (work order %s) — no second work order",
                issue_id, group_id, primary.id,  # type: ignore[union-attr]
            )
            return

        session.add(WorkOrder(
            issue_id=issue_id,
            issue_reference_no=issue.get("reference_no", ""),
            issue_title=issue.get("title", ""),
            issue_description=issue.get("description", ""),
        ))
        session.commit()


@app.post("/webhooks/events")
def webhook(event: dict, background: BackgroundTasks):
    background.add_task(_handle_event, event)
    return {"accepted": True}
