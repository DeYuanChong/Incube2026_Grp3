"""Rule-derived findings over the triage metrics (docs/05).

Every insight is a threshold over numbers `analytics.py` has already computed,
so each one is reproducible and arguable: `evidence` carries the figures that
tripped the rule, not a summary of them. The one generative judgement in this
service — what to *do* about a cluster — stays the LLM's, in
`SystemicCluster.recommendation`, and rides along in the `systemic` block.

Kept dependency-free so the check below runs with plain `python3 insights.py`.
"""

from statistics import median

# ponytail: thresholds, not env vars — these are the knobs to turn when a site's
# normal is not this normal, and they want reading next to the rule they gate.
TREND_PCT = 50.0          # this window vs the one before it
REPEAT_RATE = 0.5
DUPLICATE_RATE = 0.3
MIN_RECENT = 3            # below this, a rate over one window is noise
MIN_TOTAL = 5
MTBF_DAYS = 7.0
SLOW_REPAIR_FACTOR = 2.0  # x the median group's MTTR
MIN_REPAIRED = 3
REJECTION_RATE = 0.3
MIN_PROOFS = 5


def _finding(kind: str, group: str, detail: str, **evidence) -> dict:
    return {"kind": kind, "group": group, "detail": detail, "evidence": evidence}


def derive(
    clusters: list[dict],
    profiles: list[dict],
    mtbf: list[dict],
    mttr: list[dict],
    vendors: list[dict],
    group_by: str = "category",
    window_days: int = 90,
) -> list[dict]:
    """The rows of the analytics bundle, in, findings out. Ordered by how far
    upstream the cause sits: root causes first, then places, then timings, then
    who did the work."""
    out: list[dict] = []

    # A cluster still accruing members is an unfixed root cause, not history.
    for c in clusters:
        if c.get("active"):
            out.append(_finding(
                "systemic_active", c["cluster_key"],
                f"{c['issue_count_live']} issues in the last {window_days} days and still "
                f"accruing — the root cause has not been fixed.",
                cluster_id=c.get("id"),
                issue_count_live=c["issue_count_live"],
                has_recommendation=bool(c.get("recommendation")),
            ))

    for p in profiles:
        recent, window = p["recent"], p["window_days"]
        if (p["trend_pct"] is not None and p["trend_pct"] >= TREND_PCT
                and recent >= MIN_RECENT):
            out.append(_finding(
                "worsening", p["group"],
                f"{recent} issues in the last {window} days against {p['prior']} in the "
                f"window before — up {p['trend_pct']}%.",
                recent=recent, prior=p["prior"], trend_pct=p["trend_pct"],
            ))
        # repeat_rate is degenerate when the group *is* one category (docs/05):
        # there every issue after the first counts, so the rule would fire on all
        # of them and say nothing.
        if (group_by != "category" and (p["repeat_rate"] or 0) >= REPEAT_RATE
                and recent >= MIN_RECENT):
            out.append(_finding(
                "chronic", p["group"],
                f"{round(p['repeat_rate'] * 100)}% of the last {window} days' issues here "
                f"repeat a category already seen — repairs are not holding.",
                repeat_rate=p["repeat_rate"], recent=recent,
            ))
        if (p["duplicate_rate"] or 0) >= DUPLICATE_RATE and p["total"] >= MIN_TOTAL:
            out.append(_finding(
                "duplicate_heavy", p["group"],
                f"{round(p['duplicate_rate'] * 100)}% of issues here arrive as duplicates of "
                f"an earlier report — one defect is costing several tickets.",
                duplicate_rate=p["duplicate_rate"], total=p["total"],
            ))

    for m in mtbf:
        if m["mtbf_days"] <= MTBF_DAYS:
            out.append(_finding(
                "rapid_recurrence", m["group"],
                f"a failure every {m['mtbf_days']} days on average across "
                f"{m['issue_count']} issues — preventive work beats repeat repairs.",
                mtbf_days=m["mtbf_days"], issue_count=m["issue_count"],
            ))

    # Slow is a comparison, so it needs a baseline: the median group, which one
    # abandoned ticket cannot drag the way a mean would.
    repairs = [m["mttr_days"] for m in mttr if m["mttr_days"] is not None]
    baseline = round(median(repairs), 2) if repairs else None
    for m in mttr:
        if (baseline and m["mttr_days"] and m["repaired_count"] >= MIN_REPAIRED
                and m["mttr_days"] >= baseline * SLOW_REPAIR_FACTOR):
            out.append(_finding(
                "slow_repair", m["group"],
                f"repairs here take {m['mttr_days']} days on average against a {baseline} "
                f"day median across groups.",
                mttr_days=m["mttr_days"], median_across_groups=baseline,
                repaired_count=m["repaired_count"],
            ))
        overhead = m["verification_overhead_days"]
        if overhead and m["mttr_days"] and overhead > m["mttr_days"]:
            out.append(_finding(
                "verification_bottleneck", m["group"],
                f"a finished repair waits {overhead} days on proof and sign-off, longer than "
                f"the {m['mttr_days']} days the repair itself took.",
                verification_overhead_days=overhead, mttr_days=m["mttr_days"],
            ))

    for v in vendors:
        if (v["proof_rejection_rate"] or 0) >= REJECTION_RATE and v["proofs"] >= MIN_PROOFS:
            out.append(_finding(
                "proof_quality", v["assignee"],
                f"{round(v['proof_rejection_rate'] * 100)}% of {v['proofs']} proofs were "
                f"rejected — the speed numbers for this assignee are not the whole story.",
                proof_rejection_rate=v["proof_rejection_rate"], proofs=v["proofs"],
            ))

    return out


if __name__ == "__main__":
    def kinds(**kw):
        base = {"clusters": [], "profiles": [], "mtbf": [], "mttr": [], "vendors": []}
        return [f["kind"] for f in derive(**{**base, **kw})]

    profile = {
        "group": "Block A|L3", "total": 10, "open": 2, "severity_mix": {},
        "duplicate_rate": 0.0, "window_days": 30, "recent": 6, "prior": 2,
        "trend_pct": 200.0, "repeat_rate": 0.0,
    }
    mttr_row = {
        "group": "lighting", "repaired_count": 5, "mttr_days": 2.0, "mttc_days": 3.0,
        "median_repair_days": 2.0, "verification_overhead_days": None,
    }

    # nothing in, nothing out — an empty snapshot has no findings, not a "no data" one
    assert kinds() == []

    # a cluster is a finding only while it is still accruing members
    live = {"id": "c1", "cluster_key": "lighting|Block A|L3", "issue_count": 9,
            "issue_count_live": 4, "active": True, "recommendation": "Inspect the board."}
    assert kinds(clusters=[live]) == ["systemic_active"]
    assert kinds(clusters=[{**live, "active": False, "issue_count_live": 1}]) == []
    # the count reported is the live one, not the peak the detector recorded
    assert derive([live], [], [], [], [])[0]["evidence"]["issue_count_live"] == 4

    # trend fires on a real jump, and not on two tickets that happen to double one
    assert kinds(profiles=[profile]) == ["worsening"]
    assert kinds(profiles=[{**profile, "recent": 2, "prior": 1}]) == []
    # no prior window is no baseline, not no change
    assert kinds(profiles=[{**profile, "trend_pct": None, "prior": 0}]) == []

    # repeat rate means something per location, nothing per category (docs/05)
    chronic = {**profile, "trend_pct": None, "repeat_rate": 0.6}
    assert kinds(profiles=[chronic], group_by="floor") == ["chronic"]
    assert kinds(profiles=[chronic], group_by="category") == []

    # duplicate rate needs a group big enough for a share to mean anything
    dupes = {**profile, "trend_pct": None, "duplicate_rate": 0.4}
    assert kinds(profiles=[dupes]) == ["duplicate_heavy"]
    assert kinds(profiles=[{**dupes, "total": 3}]) == []

    assert kinds(mtbf=[{"group": "aircon", "issue_count": 8, "mtbf_days": 3.1}]) \
        == ["rapid_recurrence"]
    assert kinds(mtbf=[{"group": "aircon", "issue_count": 8, "mtbf_days": 40.0}]) == []

    # slow is relative to the median group, so one group alone is never slow
    slow = {**mttr_row, "group": "plumbing", "mttr_days": 12.0}
    assert kinds(mttr=[slow]) == []
    assert kinds(mttr=[mttr_row, slow, {**mttr_row, "group": "doors"}]) == ["slow_repair"]
    # ...and a slow group with too few repairs behind it is not yet evidence
    assert kinds(mttr=[mttr_row, {**slow, "repaired_count": 2},
                       {**mttr_row, "group": "doors"}]) == []

    # sign-off outweighing the repair is a queue problem, not a repair problem
    assert kinds(mttr=[{**mttr_row, "verification_overhead_days": 5.0}]) \
        == ["verification_bottleneck"]
    assert kinds(mttr=[{**mttr_row, "verification_overhead_days": 0.5}]) == []

    vendor = {"assignee": "acme", "work_orders": 9, "verified": 6,
              "resolved_on_arrival": 1, "avg_repair_hours": 3.0, "proofs": 8,
              "proof_rejection_rate": 0.5}
    assert kinds(vendors=[vendor]) == ["proof_quality"]
    assert kinds(vendors=[{**vendor, "proofs": 2}]) == []
    # an assignee with no proofs yet has no quality signal, not a perfect one
    assert kinds(vendors=[{**vendor, "proofs": 0, "proof_rejection_rate": None}]) == []

    # root causes lead, then places, then timings, then who did the work
    assert kinds(clusters=[live], profiles=[profile],
                 mtbf=[{"group": "aircon", "issue_count": 8, "mtbf_days": 3.1}],
                 mttr=[{**mttr_row, "verification_overhead_days": 5.0}],
                 vendors=[vendor]) == [
        "systemic_active", "worsening", "rapid_recurrence",
        "verification_bottleneck", "proof_quality",
    ]

    print("insights: ok")
