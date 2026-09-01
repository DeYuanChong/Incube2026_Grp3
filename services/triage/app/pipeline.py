"""The per-issue triage pipeline (docs/05-triage-analytics.md).

fetch issue → sync fact → duplicate detection → systemic check →
LLM severity suggestion → hard rules → store result → write back to reporting.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import text
from sqlmodel import Session, select

from . import ai_client, config
from .models import IssueFact, SystemicCluster, TriageResult, now_iso

log = logging.getLogger(__name__)


def _cluster_key(fact: IssueFact) -> str:
    return f"{fact.category}|{fact.building}|{fact.floor}"


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
    fact.created_at = issue["created_at"]
    fact.fixed_at = issue.get("fixed_at")
    fact.closed_at = issue.get("closed_at")
    fact.synced_at = now_iso()
    session.add(fact)
    return fact


def _find_duplicate(session: Session, fact: IssueFact) -> tuple[str | None, float, int]:
    """Heuristic candidates (same category+building+floor, recent, open), ranked
    by pg_trgm description similarity so the LLM only confirms the closest few.
    Returns (duplicate_of_issue_id, confidence, group_size)."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=config.DUPLICATE_WINDOW_DAYS)
    ).isoformat()
    candidates = session.exec(
        select(IssueFact).where(
            IssueFact.category == fact.category,
            IssueFact.building == fact.building,
            IssueFact.floor == fact.floor,
            IssueFact.issue_id != fact.issue_id,
            IssueFact.created_at >= cutoff,
            IssueFact.status.notin_(["closed", "cancelled"]),  # type: ignore[attr-defined]
        ).order_by(
            text("similarity(description, :d) DESC").bindparams(d=fact.description)
        ).limit(5)
    ).all()
    location = f"{fact.building} / {fact.floor}"
    group_size = 1
    for candidate in candidates:
        verdict = ai_client.is_duplicate(
            candidate.description, fact.description, fact.category, location
        )
        if verdict["same_defect"] and verdict["confidence"] >= 0.6:
            group_size = len(candidates) + 1
            return candidate.issue_id, verdict["confidence"], group_size
    return None, 0.0, group_size


def _systemic_check(session: Session, fact: IssueFact) -> SystemicCluster | None:
    key = _cluster_key(fact)
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=config.SYSTEMIC_WINDOW_DAYS)
    ).isoformat()
    members = session.exec(
        select(IssueFact).where(
            IssueFact.category == fact.category,
            IssueFact.building == fact.building,
            IssueFact.floor == fact.floor,
            IssueFact.created_at >= cutoff,
        )
    ).all()
    if len(members) < config.SYSTEMIC_MIN_COUNT:
        return None
    cluster = session.exec(
        select(SystemicCluster).where(SystemicCluster.cluster_key == key)
    ).first() or SystemicCluster(cluster_key=key, first_seen=members[0].created_at)
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
    duplicate_of, dup_confidence, dup_count = _find_duplicate(session, fact)
    cluster = _systemic_check(session, fact)

    location = f"{fact.building} / {fact.floor}" + (f" / {fact.room}" if fact.room else "")
    suggestion = ai_client.suggest_severity(
        fact.category, issue.get("title", ""), fact.description, location,
        duplicate_count=dup_count,
        systemic_count=cluster.issue_count if cluster else 0,
    )
    suggestion = _apply_hard_rules(suggestion, fact, dup_count)

    result = TriageResult(
        issue_id=issue_id,
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

    # Write back to reporting (single writer of issue state)
    try:
        httpx.post(
            f"{config.REPORTING_URL}/issues/{issue_id}/triage-result",
            json={
                "severity": result.suggested_severity,
                "urgency": result.suggested_urgency,
                "equipment_name": result.equipment_extracted,
                "duplicate_group_id": duplicate_of,
                "duplicate_count": dup_count if duplicate_of else 1,
                "is_critical_system": suggestion["is_critical_system"],
            },
            timeout=10,
        ).raise_for_status()
    except httpx.HTTPError:
        log.warning("failed to write triage result back to reporting", exc_info=True)
    return result
