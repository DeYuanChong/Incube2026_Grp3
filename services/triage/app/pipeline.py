"""The per-issue triage pipeline (docs/05-triage-analytics.md).

fetch issue → sync fact → duplicate detection → systemic check →
LLM severity suggestion → hard rules → store result → write back to reporting.

One run answers one question — what happens to this issue. Whatever the run
learned about the issue's cluster leaves separately, in `systemic_payload`.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import or_, text
from sqlmodel import Session, select

from . import ai_client, config, grouping, payload
from .models import IssueFact, SystemicCluster, TriageResult, now_iso

log = logging.getLogger(__name__)


def _cluster_key(fact: IssueFact) -> str:
    return grouping.cluster_key(fact.category, fact.building, fact.floor)


def sync_issue_fact(session: Session, issue: dict) -> IssueFact:
    fact = session.get(IssueFact, issue["id"]) or IssueFact(issue_id=issue["id"])
    fact.reference_no = issue.get("reference_no", "")
    fact.category = issue["category"]
    fact.building = issue["building"]
    fact.floor = issue["floor"]
    fact.room = issue.get("room")
    fact.equipment_name = issue.get("equipment_name")
    fact.severity = issue.get("severity")
    fact.status = issue["status"]
    fact.description = issue.get("description", "")
    fact.duplicate_group_id = issue.get("duplicate_group_id")
    fact.created_at = issue["created_at"]
    fact.fixed_at = issue.get("fixed_at")
    fact.closed_at = issue.get("closed_at")
    fact.synced_at = now_iso()
    session.add(fact)
    return fact


def _find_duplicate(
    session: Session, fact: IssueFact, as_of: str | None = None
) -> tuple[str | None, float, int]:
    """Heuristic candidates (same category+building+floor, recent, open), ranked
    by pg_trgm description similarity so the LLM confirms the closest few first.
    Returns (duplicate_of_issue_id, confidence, group_size).

    Every candidate is confirmed rather than stopping at the first hit, because
    the group size is what it costs: it feeds the severity bump and is posted to
    reporting as `duplicate_count`, so it has to count duplicates and not the
    pre-filter's pool. The no-duplicate path already scanned all five; only the
    found-early case loses its short-circuit.

    `as_of` replays the issue at the moment it arrived instead of now: the
    window ends at its own `created_at`, only earlier issues are candidates, and
    "open" is judged by whether the candidate had closed *by then*. Live triage
    passes nothing and keeps the wall-clock behaviour. Without it a backfill
    compares a 2025 report against last week's tickets and finds nothing.
    """
    anchor = datetime.fromisoformat(as_of) if as_of else datetime.now(timezone.utc)
    cutoff = (anchor - timedelta(days=config.DUPLICATE_WINDOW_DAYS)).isoformat()
    still_open = (
        # closed_at is the only timestamp that says *when* a status was reached,
        # so it is what a historical "was this open then" can be asked against.
        or_(IssueFact.closed_at.is_(None), IssueFact.closed_at > as_of)  # type: ignore[union-attr]
        if as_of else
        IssueFact.status.notin_(["closed", "cancelled"])  # type: ignore[attr-defined]
    )
    candidates = session.exec(
        select(IssueFact).where(
            IssueFact.category == fact.category,
            IssueFact.building == fact.building,
            IssueFact.floor == fact.floor,
            IssueFact.issue_id != fact.issue_id,
            IssueFact.created_at >= cutoff,
            *([IssueFact.created_at < as_of] if as_of else []),
            still_open,
        ).order_by(
            text("similarity(description, :d) DESC").bindparams(d=fact.description)
        ).limit(5)
    ).all()
    location = f"{fact.building} / {fact.floor}"
    confirmed = []
    for candidate in candidates:
        verdict = ai_client.is_duplicate(
            candidate.description, fact.description, fact.category, location
        )
        if verdict["same_defect"] and verdict["confidence"] >= config.DUPLICATE_MIN_CONFIDENCE:
            confirmed.append(
                (candidate.issue_id, candidate.created_at, verdict["confidence"])
            )
    return grouping.pick_primary(confirmed)


def _cluster_members(
    session: Session, fact: IssueFact, as_of: str | None = None
) -> list[IssueFact]:
    """Issues sharing this issue's cluster key, inside the systemic window.

    Asked fresh on every call, so it is a live view: the window slides, and a
    cluster flagged months ago reports the members it has now rather than the
    count it was flagged on. `SystemicCluster.issue_count` keeps that number.

    `as_of` ends the window at the issue being replayed rather than at now, so a
    backfill flags a cluster on the members it actually had at the time.
    """
    anchor = datetime.fromisoformat(as_of) if as_of else datetime.now(timezone.utc)
    cutoff = (anchor - timedelta(days=config.SYSTEMIC_WINDOW_DAYS)).isoformat()
    return list(session.exec(
        select(IssueFact).where(
            IssueFact.category == fact.category,
            IssueFact.building == fact.building,
            IssueFact.floor == fact.floor,
            IssueFact.created_at >= cutoff,
            *([IssueFact.created_at <= as_of] if as_of else []),
        ).order_by(IssueFact.created_at)  # type: ignore[arg-type]
    ).all())


def _systemic_check(
    session: Session, fact: IssueFact, as_of: str | None = None
) -> SystemicCluster | None:
    key = _cluster_key(fact)
    members = _cluster_members(session, fact, as_of)
    if len(members) < config.SYSTEMIC_MIN_COUNT:
        return None
    cluster = session.exec(
        select(SystemicCluster).where(SystemicCluster.cluster_key == key)
    ).first() or SystemicCluster(
        cluster_key=key, first_seen=min(m.created_at for m in members)
    )
    cluster.issue_count = len(members)
    cluster.last_seen = max(m.created_at for m in members)
    if not cluster.recommendation:
        lines = "\n".join(f"- [{m.created_at[:10]}] {m.description[:150]}" for m in members)
        cluster.recommendation = ai_client.systemic_recommendation(
            key, len(members), config.SYSTEMIC_WINDOW_DAYS, lines
        )
    cluster.updated_at = now_iso()
    session.add(cluster)
    return cluster


def _member_summary(fact: IssueFact) -> dict:
    """What an admin needs to judge whether the cluster really is one fault."""
    return {
        "issue_id": fact.issue_id,
        "reference_no": fact.reference_no,
        "created_at": fact.created_at,
        "status": fact.status,
        "severity": fact.severity,
        "description": fact.description[:150],
    }


def to_response(session: Session, result: TriageResult) -> dict:
    """The endpoint's singular result: the stored row plus the nullable
    cluster-level payload it belongs to.

    The member list is read through the issue's own fact rather than by
    splitting `cluster_key`, which is not safely parseable — a building or
    floor containing "|" would split into the wrong three parts.
    """
    cluster = (
        session.get(SystemicCluster, result.systemic_cluster_id)
        if result.systemic_cluster_id
        else None
    )
    issues: list[dict] = []
    if cluster:
        fact = session.get(IssueFact, result.issue_id)
        # ponytail: whole cluster, uncapped — a 90-day window in a busy building
        # can return a long list. Paginate off cluster_id if that bites.
        issues = [_member_summary(m) for m in _cluster_members(session, fact)] if fact else []
    return payload.with_systemic(
        result.model_dump(),
        cluster.model_dump() if cluster else None,
        issues,
        config.SYSTEMIC_WINDOW_DAYS,
    )


def _apply_hard_rules(suggestion: dict, fact: IssueFact, duplicate_count: int) -> dict:
    """Rules win over the LLM (docs/04-ai-integration.md §3)."""
    order = config.SEVERITY_ORDER
    severity, urgency = suggestion["severity"], suggestion["urgency"]
    if duplicate_count >= config.DUPLICATE_BUMP_THRESHOLD:
        severity = order[min(order.index(severity) + 1, len(order) - 1)]
    if fact.category == "physical_security" and urgency == "routine":
        urgency = "urgent"
    text = fact.description.lower()
    if any(kw in text for kw in config.EMERGENCY_KEYWORDS):
        urgency = "emergency"
    return {**suggestion, "severity": severity, "urgency": urgency}


def run_triage(session: Session, issue_id: str) -> TriageResult:
    resp = httpx.get(f"{config.REPORTING_URL}/issues/{issue_id}", timeout=10)
    resp.raise_for_status()
    issue = resp.json()["issue"]
    fact = sync_issue_fact(session, issue)
    return triage_fact(session, fact, issue.get("title", ""))


def triage_fact(
    session: Session,
    fact: IssueFact,
    title: str,
    as_of: str | None = None,
    write_back: bool = True,
) -> TriageResult:
    """Triage one already-synced fact.

    Split out of `run_triage` so a historical replay (`scripts/backfill_triage.py`)
    runs the same duplicate detection, systemic check and hard rules rather than
    a second copy of them that drifts. `as_of` anchors both windows to the issue
    instead of to now; `write_back=False` leaves reporting alone, which is what a
    backfill of 2,182 closed issues wants — their severity is already history.
    """
    duplicate_of, dup_confidence, dup_count = _find_duplicate(session, fact, as_of)
    # Mirror what the write-back below is about to tell reporting. Reporting is
    # still the writer of record, but it publishes nothing on the write-back
    # that comes back here, so the snapshot would carry a null duplicate link
    # until the issue's next status change — and profiles() counts this column.
    fact.duplicate_group_id = duplicate_of
    cluster = _systemic_check(session, fact, as_of)

    location = f"{fact.building} / {fact.floor}" + (f" / {fact.room}" if fact.room else "")
    suggestion = ai_client.suggest_severity(
        fact.category, title, fact.description, location,
        duplicate_count=dup_count,
        systemic_count=cluster.issue_count if cluster else 0,
    )
    suggestion = _apply_hard_rules(suggestion, fact, dup_count)

    result = TriageResult(
        issue_id=fact.issue_id,
        suggested_severity=suggestion["severity"],
        suggested_urgency=suggestion["urgency"],
        severity_rationale=suggestion["rationale"],
        equipment_extracted=suggestion["equipment_name"],
        duplicate_of_issue_id=duplicate_of,
        duplicate_confidence=dup_confidence or None,
        systemic_flag=cluster is not None,
        systemic_cluster_id=cluster.id if cluster else None,
    )
    session.add(result)
    session.commit()
    session.refresh(result)

    if not write_back:
        return result

    # Write back to reporting (single writer of issue state)
    try:
        httpx.post(
            f"{config.REPORTING_URL}/issues/{fact.issue_id}/triage-result",
            json={
                "severity": result.suggested_severity,
                "urgency": result.suggested_urgency,
                "equipment_name": result.equipment_extracted,
                "duplicate_group_id": duplicate_of,
                "duplicate_count": dup_count if duplicate_of else 1,
            },
            timeout=10,
        ).raise_for_status()
    except httpx.HTTPError:
        log.warning("failed to write triage result back to reporting", exc_info=True)
    return result
