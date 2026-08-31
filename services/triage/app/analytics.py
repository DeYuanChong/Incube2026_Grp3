"""MTBF / MTTR / profiles over the issue_facts snapshot (docs/05-triage-analytics.md)."""

from collections import defaultdict
from datetime import datetime

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
        if len(facts) < 2:
            continue
        times = sorted(_parse(f.created_at) for f in facts if f.created_at)
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
