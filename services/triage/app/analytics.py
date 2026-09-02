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
from . import insights as rules
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


def _distinct_failures(facts: list[IssueFact]) -> list[IssueFact]:
    """One entry per duplicate group, the oldest — the original report.

    A duplicate is the same defect reported again by someone else, not the asset
    failing again (docs/05 §Duplicate handling). Counting the confirmations as
    separate failures collapses MTBF towards the reporting interval: four
    colleagues raising one warm FCU on consecutive days reads as an asset
    failing every day, which is the opposite of what the number is for.
    """
    primaries: dict[str, IssueFact] = {}
    singles: list[IssueFact] = []
    for fact in facts:
        if not fact.duplicate_group_id:
            singles.append(fact)
            continue
        seen = primaries.get(fact.duplicate_group_id)
        if seen is None or fact.created_at < seen.created_at:
            primaries[fact.duplicate_group_id] = fact
    return singles + list(primaries.values())


def mtbf(session: Session, group_by: str = "category") -> list[dict]:
    """Mean time between failures (days) per group; needs ≥ 2 failures."""
    out = []
    for key, group in _grouped(session, group_by).items():
        facts = _distinct_failures(group)
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
            # How many categories the window actually held. One means repeat_rate
            # is arithmetic rather than a finding — every issue after the first is
            # a "repeat" because there is nothing else it could be.
            "distinct_categories": len({f.category for f in recent}),
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


# --- Insight assembly -------------------------------------------------------
# Cards for the admin. The thresholds, the silence guards and the ranking live
# in `insights.py` — dependency-free and self-checked with `python3 insights.py`
# — because that is the part with the edge cases. This side owns the database,
# the prose and the evidence links.


def _linked_summary(fact: IssueFact) -> dict:
    """The evidence behind a card. A count on its own is unfalsifiable — an
    admin told "4 lighting failures" needs to see whether that is one ballast
    or four unrelated fittings (docs/05 §One issue in, one result out)."""
    return {
        "issue_id": fact.issue_id,
        "reference_no": fact.reference_no,
        "created_at": fact.created_at,
        "status": fact.status,
        "severity": fact.severity,
        "title": fact.description[:120],
    }


def _insight(
    *, id: str, kind: str, source: str, score: float, title: str, body: str,
    action: str, window_days: int, evidence: list[dict], linked: list[IssueFact],
    active: bool = True, filter: dict | None = None,
) -> dict:
    """`score` is how far past its own threshold this finding sits, and is what
    the list is ranked on (`insights.py`).

    `filter` is how to find this finding's issues in the defect list. Stated here
    because this is the side that knows the group — leaving the client to
    reconstruct it from `id` means parsing a cluster UUID back into a location,
    which cannot work.
    """
    return {
        "id": id,
        "kind": kind,
        "source": source,
        "score": round(score, 2),
        "active": active,
        "title": title,
        "body": body,
        "action": action,
        "window_days": window_days,
        "evidence": evidence,
        "filter": filter,
        "linked_count": len(linked),
        # ponytail: uncapped, as systemic_payload.issues is. The list *is* the
        # count, so a cap needs a truncation flag; paginate when a card links
        # enough issues for the response size to be noticed.
        "linked": [_linked_summary(f) for f in linked],
    }


def insights(session: Session) -> list[dict]:
    """Recommendation cards assembled from the aggregates above, worst first.

    Every field is derived from stored data or an LLM recommendation that was
    already written at detection time. Nothing here invents a confidence score
    or a cost saving — an admin acting on one of these can follow each number
    back to the issues in `linked`.
    """
    out: list[dict] = []
    window = config.SYSTEMIC_WINDOW_DAYS
    cutoff = _cutoff(window)

    # Members per cluster, keyed the same way the detector keys them — read off
    # the fact columns, never by splitting cluster_key, which a building
    # containing "|" makes unparseable. `members` is the live window (the
    # evidence); `ever` spans all time, so a cluster whose members have all
    # rolled out of the window can still be named properly.
    members: dict[str, list[IssueFact]] = defaultdict(list)
    ever: dict[str, list[IssueFact]] = defaultdict(list)
    for fact in session.exec(select(IssueFact)).all():
        key = grouping.cluster_key(fact.category, fact.building, fact.floor)
        ever[key].append(fact)
        if fact.created_at >= cutoff:
            members[key].append(fact)

    # 1. Systemic clusters — the finding that already carries a recommendation.
    for cluster in systemic_clusters(session):
        score = rules.systemic(cluster, config.SYSTEMIC_MIN_COUNT)
        if score is None:
            continue
        linked = sorted(
            members.get(cluster["cluster_key"], []), key=lambda f: f.created_at
        )
        named = ever.get(cluster["cluster_key"], [])
        sample = named[0] if named else None
        # With no fact left to read the parts off (the snapshot was rebuilt),
        # fall back to prettifying the key for display only — never split it
        # back into fields, which a building containing "|" breaks.
        where = (
            f"{sample.building} / {sample.floor}" if sample
            else cluster["cluster_key"].replace("|", " · ")
        )
        # category is a slug on the fact ("air_conditioning"); this is prose
        what = sample.category.replace("_", " ").capitalize() if sample else ""
        out.append(_insight(
            id=f"systemic:{cluster['id']}",
            kind="systemic",
            source="systemic_cluster",
            score=score,
            active=cluster["active"],
            title=f"{what or 'Repeat'} faults keep recurring at {where}".strip(),
            body=(
                f"{cluster['issue_count_live']} issues in the last {window} days, "
                f"against {cluster['issue_count']} when this was first flagged. "
                + ("Still accruing members."
                   if cluster["active"]
                   else "No longer clearing the threshold — it may already be fixed.")
            ),
            action=cluster["recommendation"],
            window_days=window,
            filter=(
                {"search": f"{sample.building} / {sample.floor}", "category": sample.category}
                if sample else None
            ),
            evidence=[
                {"label": "Issues now", "value": cluster["issue_count_live"]},
                {"label": "At detection", "value": cluster["issue_count"]},
                {"label": "Window", "value": f"{window}d"},
            ],
            linked=linked,
        ))

    location_groups = _grouped(session, "floor")
    recent_cutoff = _cutoff(TREND_WINDOW_DAYS)

    for profile in profiles(session, by="location"):
        facts = location_groups.get(profile["group"], [])
        recent = sorted(
            (f for f in facts if f.created_at >= recent_cutoff),
            key=lambda f: f.created_at,
        )
        sample = recent[0] if recent else None
        where = f"{sample.building} / {sample.floor}" if sample else profile["group"]
        where_filter = {"search": where, "category": None} if sample else None

        # 2. Getting worse: this window against the one before it.
        score = rules.trend(profile)
        if score is not None:
            out.append(_insight(
                id=f"trend:{profile['group']}",
                kind="predictive",
                source="profile_trend",
                score=score,
                title=f"Defect volume at {where} is climbing",
                body=(
                    f"{profile['recent']} issues in the last {profile['window_days']} days "
                    f"against {profile['prior']} in the {profile['window_days']} before — "
                    f"up {profile['trend_pct']}%."
                ),
                action=(
                    "Check whether one asset is behind the rise before scheduling "
                    "more reactive callouts here; the linked issues show the mix."
                ),
                window_days=profile["window_days"],
                filter=where_filter,
                evidence=[
                    {"label": "This window", "value": profile["recent"]},
                    {"label": "Previous", "value": profile["prior"]},
                    {"label": "Trend", "value": f"{profile['trend_pct']:+}%"},
                ],
                linked=recent,
            ))

        # 3. Same thing again: repeats within the window.
        score = rules.repeat(profile, "floor")
        if score is not None:
            out.append(_insight(
                id=f"repeat:{profile['group']}",
                kind="pre-emptive",
                source="profile_repeat",
                score=score,
                title=f"Repeat reports of the same categories at {where}",
                body=(
                    f"{int(profile['repeat_rate'] * 100)}% of the last "
                    f"{profile['recent']} issues here were not the first of their "
                    f"category, across {profile['distinct_categories']} categories — "
                    "the same kinds of fault keep coming back."
                ),
                action=(
                    "Treat these as one standing fault rather than separate "
                    "tickets, and hold sign-off until a post-fix check passes."
                ),
                window_days=profile["window_days"],
                filter=where_filter,
                evidence=[
                    {"label": "Repeat rate", "value": f"{int(profile['repeat_rate'] * 100)}%"},
                    {"label": "Issues", "value": profile["recent"]},
                    {"label": "Categories", "value": profile["distinct_categories"]},
                ],
                linked=recent,
            ))

        # 4. One defect, several tickets.
        score = rules.duplicates(profile)
        if score is not None:
            out.append(_insight(
                id=f"duplicate:{profile['group']}",
                kind="pre-emptive",
                source="profile_duplicate",
                score=score,
                title=f"Several reporters are filing the same defects at {where}",
                body=(
                    f"{int(profile['duplicate_rate'] * 100)}% of the {profile['total']} "
                    "issues here arrived as a duplicate of an earlier report — one "
                    "defect is opening several tickets."
                ),
                action=(
                    "Show reporters the open tickets for a location before they file. "
                    "Dispatch is already gated, so the cost here is triage time, not "
                    "duplicated callouts."
                ),
                window_days=profile["window_days"],
                filter=where_filter,
                evidence=[
                    {"label": "Duplicate rate", "value": f"{int(profile['duplicate_rate'] * 100)}%"},
                    {"label": "Issues", "value": profile["total"]},
                    {"label": "Open", "value": profile["open"]},
                ],
                linked=recent,
            ))

    # 5. Assets failing faster than they should.
    equipment_groups = _grouped(session, "equipment")
    repair = {row["group"]: row for row in mttr(session, "equipment")}
    for row in mtbf(session, "equipment"):
        score = rules.asset_mtbf(row)
        if score is None:
            continue
        linked = sorted(equipment_groups.get(row["group"], []), key=lambda f: f.created_at)
        mttr_days = (repair.get(row["group"]) or {}).get("mttr_days")
        out.append(_insight(
            id=f"mtbf:{row['group']}",
            kind="pre-emptive",
            source="mtbf",
            score=score,
            title=(
                f"{row['group']} is failing every {row['mtbf_days']:.0f} "
                f"{'day' if round(row['mtbf_days']) == 1 else 'days'}"
            ),
            body=(
                f"{row['issue_count']} failures recorded, averaging "
                f"{row['mtbf_days']} days between them — under the "
                f"{rules.MTBF_DAYS:.0f}-day mark where repeat repair usually "
                "costs more than replacement."
            ),
            action=(
                "Escalate past routine servicing to a root-cause inspection, or "
                "price a replacement against the callouts this asset is taking."
            ),
            window_days=window,
            filter={"search": row["group"], "category": None},
            evidence=[
                {"label": "MTBF", "value": f"{row['mtbf_days']}d"},
                {"label": "Failures", "value": row["issue_count"]},
                {"label": "MTTR", "value": f"{mttr_days}d" if mttr_days else "—"},
            ],
            linked=linked,
        ))

    # 6/7. Where the time goes: the repair itself, or the sign-off after it.
    location_mttr = mttr(session, "floor")
    baseline = rules.repair_baseline(location_mttr)
    for row in location_mttr:
        facts = location_groups.get(row["group"], [])
        # The evidence for a repair timing is the repairs, not every ticket.
        repaired = sorted((f for f in facts if f.fixed_at), key=lambda f: f.created_at)
        sample = repaired[0] if repaired else None
        where = f"{sample.building} / {sample.floor}" if sample else row["group"]
        where_filter = {"search": where, "category": None} if sample else None

        score = rules.slow_repair(row, baseline)
        if score is not None:
            out.append(_insight(
                id=f"mttr:{row['group']}",
                kind="predictive",
                source="mttr",
                score=score,
                title=f"Repairs at {where} take longer than elsewhere",
                body=(
                    f"{row['mttr_days']} days on average across {row['repaired_count']} "
                    f"repairs, against a {baseline} day median across locations."
                ),
                action=(
                    "Check access, parts lead time and who is assigned here before "
                    "adding capacity — the delay may not be the repair itself."
                ),
                window_days=window,
                filter=where_filter,
                evidence=[
                    {"label": "MTTR", "value": f"{row['mttr_days']}d"},
                    {"label": "Median", "value": f"{baseline}d"},
                    {"label": "Repairs", "value": row["repaired_count"]},
                ],
                linked=repaired,
            ))

        score = rules.verification(row)
        if score is not None:
            out.append(_insight(
                id=f"verification:{row['group']}",
                kind="pre-emptive",
                source="mttr",
                score=score,
                title=f"Finished repairs at {where} are waiting on sign-off",
                body=(
                    f"A completed repair waits {row['verification_overhead_days']} days on "
                    f"proof and sign-off, longer than the {row['mttr_days']} days the repair "
                    f"itself took, across {row['repaired_count']} repairs."
                ),
                action=(
                    "Chase verification rather than the repair queue: the work is "
                    "already done while the ticket is still counted as open."
                ),
                window_days=window,
                filter=where_filter,
                evidence=[
                    {"label": "Sign-off", "value": f"{row['verification_overhead_days']}d"},
                    {"label": "Repair", "value": f"{row['mttr_days']}d"},
                    {"label": "Repairs", "value": row["repaired_count"]},
                ],
                linked=repaired,
            ))

    # 8. Proof quality: work coming back rejected wastes a second dispatch.
    for row in vendor_performance(session):
        score = rules.proof_quality(row)
        if score is None:
            continue
        out.append(_insight(
            id=f"vendor:{row['assignee']}",
            kind="pre-emptive",
            source="vendor_performance",
            score=score,
            title=f"{row['assignee']}'s proofs are mostly being rejected",
            body=(
                f"{int(row['proof_rejection_rate'] * 100)}% of {row['proofs']} "
                f"proof uploads across {row['work_orders']} work orders were "
                "rejected by the vision check or by a human verifier."
            ),
            action=(
                "Send the evidence recommendation with the dispatch so the right "
                "photo is taken on the first visit."
            ),
            window_days=window,
            evidence=[
                {"label": "Rejection rate", "value": f"{int(row['proof_rejection_rate'] * 100)}%"},
                {"label": "Proofs", "value": row["proofs"]},
                {
                    "label": "Avg repair",
                    "value": f"{row['avg_repair_hours']}h" if row["avg_repair_hours"] else "—",
                },
            ],
            linked=[],
        ))

    # Worst first. Stable, so equal scores keep the order the rules ran in:
    # root causes, then places, then assets, then timings, then who did the work.
    return sorted(out, key=lambda i: i["score"], reverse=True)
