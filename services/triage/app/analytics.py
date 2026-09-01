"""MTBF / MTTR / profiles over the triage.issue_facts snapshot, plus read-only
queries over the fixverify schema (docs/05-triage-analytics.md).

Cross-schema rule: triage may READ the fixverify schema (raw SQL below) but
never writes to it — fixverify remains its single writer.
"""

from collections import defaultdict
from datetime import datetime

from sqlalchemy import text
from sqlmodel import Session, select

from .models import IssueFact

GROUP_KEYS = {
    "category": lambda f: f.category,
    "building": lambda f: f.building,
    "floor": lambda f: f"{f.building}|{f.floor}",
    "equipment": lambda f: f.equipment_name or "(unspecified)",
}


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _grouped(session: Session, group_by: str) -> dict[str, list[IssueFact]]:
    key_fn = GROUP_KEYS[group_by]
    groups: dict[str, list[IssueFact]] = defaultdict(list)
    for fact in session.exec(select(IssueFact)).all():
        groups[key_fn(fact)].append(fact)
    return groups


def mtbf(session: Session, group_by: str = "category") -> list[dict]:
    """Mean time between failures (days) per group; needs ≥ 2 issues."""
    out = []
    for key, facts in _grouped(session, group_by).items():
        times = sorted(_parse(f.created_at) for f in facts if f.created_at)
        if len(times) < 2:  # a gap needs two timestamps, not two rows
            continue
        gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
        out.append({
            "group": key,
            "issue_count": len(facts),
            "mtbf_days": round(sum(gaps) / len(gaps) / 86400, 2),
        })
    return sorted(out, key=lambda r: r["mtbf_days"])


def mttr(session: Session, group_by: str = "category") -> list[dict]:
    """Mean time to repair (created → fixed) and to close, in days, per group."""
    out = []
    for key, facts in _grouped(session, group_by).items():
        repairs = [
            (_parse(f.fixed_at) - _parse(f.created_at)).total_seconds()
            for f in facts if f.fixed_at and f.created_at
        ]
        closes = [
            (_parse(f.closed_at) - _parse(f.created_at)).total_seconds()
            for f in facts if f.closed_at and f.created_at
        ]
        if not repairs and not closes:
            continue
        out.append({
            "group": key,
            "repaired_count": len(repairs),
            "mttr_days": round(sum(repairs) / len(repairs) / 86400, 2) if repairs else None,
            "mttc_days": round(sum(closes) / len(closes) / 86400, 2) if closes else None,
        })
    return sorted(out, key=lambda r: r["mttr_days"] or 0, reverse=True)


def vendor_performance(session: Session) -> list[dict]:
    """Per-assignee performance from fixverify's tables (read-only).

    Speed: mean repair hours (work order started → completed).
    Quality: proof rejection rate (AI 'irrelevant' or human 'rejected'),
    and resolved-on-arrival counts (no work was actually needed).
    """
    try:
        rows = session.exec(text("""
            SELECT
                wo.assignee                                        AS assignee,
                COUNT(DISTINCT wo.id)                              AS work_orders,
                COUNT(DISTINCT CASE WHEN wo.status = 'verified' THEN wo.id END) AS verified,
                COUNT(DISTINCT CASE WHEN wo.resolved_on_arrival THEN wo.id END) AS resolved_on_arrival,
                AVG(CASE
                    WHEN wo.started_at IS NOT NULL AND wo.completed_at IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (wo.completed_at::timestamptz
                                             - wo.started_at::timestamptz)) / 3600.0
                END)                                               AS avg_repair_hours,
                COUNT(p.id)                                        AS proofs,
                SUM(CASE WHEN p.ai_verdict = 'irrelevant'
                          OR p.human_verdict = 'rejected' THEN 1 ELSE 0 END) AS proofs_rejected
            FROM fixverify.work_orders wo
            LEFT JOIN fixverify.proofs p ON p.work_order_id = wo.id
            WHERE wo.assignee IS NOT NULL
            GROUP BY wo.assignee
        """)).all()
    except Exception:
        session.rollback()
        return []  # fixverify schema not created yet (fresh DB)
    out = []
    for r in rows:
        m = r._mapping
        proofs = m["proofs"] or 0
        out.append({
            "assignee": m["assignee"],
            "work_orders": m["work_orders"],
            "verified": m["verified"],
            "resolved_on_arrival": m["resolved_on_arrival"],
            "avg_repair_hours": round(float(m["avg_repair_hours"]), 1) if m["avg_repair_hours"] else None,
            "proofs": proofs,
            "proof_rejection_rate": round((m["proofs_rejected"] or 0) / proofs, 2) if proofs else None,
        })
    return sorted(out, key=lambda r: r["work_orders"], reverse=True)


def profiles(session: Session, by: str = "location") -> list[dict]:
    group_by = "floor" if by == "location" else "category"
    out = []
    for key, facts in _grouped(session, group_by).items():
        severity_mix: dict[str, int] = defaultdict(int)
        for f in facts:
            severity_mix[f.severity or "untriaged"] += 1
        out.append({
            "group": key,
            "total": len(facts),
            "open": sum(1 for f in facts if f.status not in ("closed", "cancelled")),
            "severity_mix": dict(severity_mix),
        })
    return sorted(out, key=lambda r: r["total"], reverse=True)
