"""MTBF / MTTR / profiles over the triage.issue_facts snapshot, plus read-only
queries over the fixverify schema (docs/05-triage-analytics.md).

Cross-schema rule: triage may READ the fixverify schema (raw SQL below) but
never writes to it — fixverify remains its single writer.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import func, text
from sqlmodel import Session, select

from . import config, grouping
from .models import IssueFact, SystemicCluster

GROUP_KEYS = {
    "category": lambda f: f.category,
    "building": lambda f: f.building,
    "floor": lambda f: f"{f.building}|{f.floor}",
    "equipment": lambda f: f.equipment_name or "(unspecified)",
}

# Profiles compare this window against the one before it (docs/05 §Profiles).
TREND_WINDOW_DAYS = 30


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _cutoff(days: int) -> str:
    """ISO timestamps in the snapshot are UTC, so a window is a string
    comparison — same as the pipeline's queries."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def group_for(by: str) -> str:
    """`location` is the profile-level name for the `building|floor` grouping.
    One formula, so the profiles and the metrics computed beside them cannot end
    up grouped differently."""
    return "floor" if by == "location" else by


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
    """Time to repair (created → fixed) and to close, in days, per group: mean,
    median, and the verification overhead sitting between fixed and closed."""
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
        # Verification overhead is fixed → closed, over the issues that have
        # both stamps. Not mttc_days - mttr_days: those two means are taken over
        # different sets of issues, so the subtraction is only right when every
        # repaired issue also closed.
        verifications = [
            (_parse(f.closed_at) - _parse(f.fixed_at)).total_seconds()
            for f in facts if f.closed_at and f.fixed_at
        ]
        if not repairs and not closes:
            continue
        out.append({
            "group": key,
            "repaired_count": len(repairs),
            "mttr_days": round(sum(repairs) / len(repairs) / 86400, 2) if repairs else None,
            "mttc_days": round(sum(closes) / len(closes) / 86400, 2) if closes else None,
            # median resists the one issue that sat open for a month
            "median_repair_days": round(median(repairs) / 86400, 2) if repairs else None,
            "verification_overhead_days": (
                round(sum(verifications) / len(verifications) / 86400, 2)
                if verifications else None
            ),
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
    """Per-group profile (docs/05 §Profiles).

    `total`, `open`, `severity_mix` and `duplicate_rate` are over the whole
    snapshot. `recent`, `prior`, `trend_pct` and `repeat_rate` are over
    `window_days` and the window before it — a rate needs a period, or it only
    ever drifts towards whatever the building has always been like.
    """
    group_by = group_for(by)
    recent_cutoff = _cutoff(TREND_WINDOW_DAYS)
    prior_cutoff = _cutoff(TREND_WINDOW_DAYS * 2)
    out = []
    for key, facts in _grouped(session, group_by).items():
        severity_mix: dict[str, int] = defaultdict(int)
        for f in facts:
            severity_mix[f.severity or "untriaged"] += 1
        recent = [f for f in facts if f.created_at >= recent_cutoff]
        prior = [f for f in facts if prior_cutoff <= f.created_at < recent_cutoff]
        duplicates = sum(1 for f in facts if f.duplicate_group_id)
        out.append({
            "group": key,
            "total": len(facts),
            "open": sum(1 for f in facts if f.status not in ("closed", "cancelled")),
            "severity_mix": dict(severity_mix),
            # share of issues that arrived as a duplicate of an earlier one
            "duplicate_rate": round(duplicates / len(facts), 2) if facts else None,
            "window_days": TREND_WINDOW_DAYS,
            "recent": len(recent),
            "prior": len(prior),
            # undefined against an empty prior window, not 0% and not infinite
            "trend_pct": (
                round((len(recent) - len(prior)) / len(prior) * 100, 1)
                if prior else None
            ),
            "repeat_rate": _repeat_rate(recent),
        })
    return sorted(out, key=lambda r: r["total"], reverse=True)


def _repeat_rate(facts: list[IssueFact]) -> float | None:
    """Share of the window's issues that are not the first of their category
    here. The first report of a category is the discovery; every later one is
    the same kind of thing happening again, which is what a repeat rate is for.

    Order does not matter — exactly one issue per distinct category is a first —
    so this is the count minus the distinct count. Degenerate for `by=category`,
    where the group is one category and every issue after the first counts.
    """
    if not facts:
        return None
    firsts = len({f.category for f in facts})
    return round((len(facts) - firsts) / len(facts), 2)


def systemic_clusters(session: Session) -> list[dict]:
    """Every stored cluster, with a live member count over the current window.

    `issue_count` on the row is refreshed only when a new member arrives, so a
    cluster someone actually fixed keeps its peak count forever and stays at the
    top of the admin's list. `issue_count_live` decays with the window and
    `active` says whether it would still be flagged today; the stored count
    stays as the record of what the detector saw. The two answer different
    questions and are expected to diverge (docs/05).
    """
    cutoff = _cutoff(config.SYSTEMIC_WINDOW_DAYS)
    # One GROUP BY for every cluster, keyed from the fact columns — never by
    # splitting cluster_key, which a building containing "|" makes unparseable.
    live = {
        grouping.cluster_key(category, building, floor): count
        for category, building, floor, count in session.exec(
            select(
                IssueFact.category, IssueFact.building, IssueFact.floor,
                func.count(),  # type: ignore[arg-type]
            )
            .where(IssueFact.created_at >= cutoff)
            .group_by(IssueFact.category, IssueFact.building, IssueFact.floor)
        ).all()
    }
    out = [
        {
            **cluster.model_dump(),
            "issue_count_live": live.get(cluster.cluster_key, 0),
            "active": live.get(cluster.cluster_key, 0) >= config.SYSTEMIC_MIN_COUNT,
        }
        for cluster in session.exec(select(SystemicCluster)).all()
    ]
    return sorted(out, key=lambda r: r["issue_count_live"], reverse=True)
