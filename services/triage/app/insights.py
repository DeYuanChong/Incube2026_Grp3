"""The rules behind the insight cards (docs/05) — thresholds, silence guards and
ranking, with no database and no prose.

`analytics.insights` owns the cards: it gathers the aggregates, writes the
title / body / action and attaches the linked issues. This module owns the one
question each card turns on — *is this worth an admin's attention, and how
badly* — because that is the part with the edge cases, and the part worth a
check that runs without a database.

Each rule takes an aggregate row and returns a **score** or `None`. `None` is
silence, and silence is a feature: a rule that cannot mean anything on this data
must not fire. Three of those conditions were found by running the rules over a
real 2182-issue snapshot rather than reasoned about:

- a window holding one category makes `repeat_rate` arithmetic, `(n-1)/n`, so it
  fired on 21 of 63 locations and meant nothing on any of them;
- a repair that took an hour is beaten by any sign-off at all, so
  `verification_overhead > mttr` alone flagged four-minute jobs;
- a median MTTR taken over groups with one repair each is not a baseline — on the
  equipment grouping it sat at 0.17 days and made every real group look slow.

The score is the observation as a multiple of the threshold it cleared, so 2.0 is
twice as far past the line as 1.0 on the *same* rule.

ponytail: across different rules that multiple is an ordering, not a unit — 2x
the trend threshold is not "as bad as" 2x the MTBF threshold. It is enough to
float the worst few to the top of a capped list, which is all the caller needs.
Weight per kind here if one rule turns out to deserve the front page.

Kept dependency-free so the check below runs with plain `python3 insights.py`.
"""

from statistics import median

# ponytail: thresholds, not env vars — these are the knobs to turn when a site's
# normal is not this normal, and they want reading next to the rule they gate.
TREND_PCT = 50.0          # a window at least half again as busy as the last
MIN_RECENT = 3            # ...on more than a couple of issues
REPEAT_RATE = 0.5         # over half the window is the same thing again
DUPLICATE_RATE = 0.3
MIN_TOTAL = 5             # a share needs a group big enough to have one
MTBF_DAYS = 60.0          # below this, repeat repair usually costs more than replacement
MIN_GROUP_ISSUES = 3
SLOW_REPAIR_FACTOR = 2.0  # x the median qualifying group's MTTR
MIN_REPAIRED = 3          # a repair timing needs repairs behind it
MIN_OVERHEAD_DAYS = 1.0   # sign-off lag long enough that someone would act on it
REJECTION_RATE = 0.5
MIN_PROOFS = 3

# What a caller should show. The rules return everything and rank it; the cut is
# the reader's decision, not the rule's, so it lives at the edge (main.overview).
LIMIT = 10


def repair_baseline(mttr_rows: list[dict]) -> float | None:
    """Median MTTR across groups with enough repairs to have one.

    Groups under `MIN_REPAIRED` are excluded from the baseline, not just from the
    finding: five equipment groups with a single repair each drag the median to
    0.17 days, and then every group with real volume reads as slow.
    """
    repairs = [
        row["mttr_days"] for row in mttr_rows
        if row["mttr_days"] is not None and row["repaired_count"] >= MIN_REPAIRED
    ]
    return round(median(repairs), 2) if repairs else None


def systemic(cluster: dict, min_cluster_count: int = 3) -> float | None:
    """A cluster with a recommendation to give. Ranked on its live count, so one
    that has stopped accruing members scores below 1.0 and sinks — which is what
    a fixed root cause looks like from here."""
    if not cluster.get("recommendation"):
        return None  # flagged, but the LLM call has not landed — nothing to escalate
    return cluster["issue_count_live"] / max(min_cluster_count, 1)


def trend(profile: dict) -> float | None:
    """Getting worse against its own baseline. `trend_pct` is None with no prior
    window — no baseline is not the same as no change."""
    if profile["trend_pct"] is None or profile["recent"] < MIN_RECENT:
        return None
    return None if profile["trend_pct"] < TREND_PCT else profile["trend_pct"] / TREND_PCT


def repeat(profile: dict, group_by: str) -> float | None:
    """The same kinds of fault coming back.

    Silent unless the window held at least two categories. `repeat_rate` is
    `(n - distinct categories)/n`, so a group with one category reports `(n-1)/n`
    by construction — which is how a flat taxonomy turns this into "the group had
    more than two tickets". Same reason `group_by="category"` is excluded: there
    the group *is* one category (docs/05).
    """
    if group_by == "category" or profile["distinct_categories"] < 2:
        return None
    if profile["repeat_rate"] is None or profile["recent"] < MIN_RECENT:
        return None
    return None if profile["repeat_rate"] < REPEAT_RATE else profile["repeat_rate"] / REPEAT_RATE


def duplicates(profile: dict) -> float | None:
    """One defect costing several tickets."""
    if profile["duplicate_rate"] is None or profile["total"] < MIN_TOTAL:
        return None
    return (
        None if profile["duplicate_rate"] < DUPLICATE_RATE
        else profile["duplicate_rate"] / DUPLICATE_RATE
    )


def asset_mtbf(row: dict) -> float | None:
    """An asset failing faster than it should.

    `(unspecified)` is skipped: it is every issue with no equipment extracted, so
    its MTBF is the site's arrival rate wearing an asset's name.
    """
    if row["group"] == "(unspecified)" or row["issue_count"] < MIN_GROUP_ISSUES:
        return None
    return None if row["mtbf_days"] >= MTBF_DAYS else MTBF_DAYS / max(row["mtbf_days"], 0.01)


def slow_repair(row: dict, baseline: float | None) -> float | None:
    """Slower than the median group. Needs a baseline, so one group is never slow."""
    if not baseline or row["mttr_days"] is None or row["repaired_count"] < MIN_REPAIRED:
        return None
    limit = baseline * SLOW_REPAIR_FACTOR
    return None if row["mttr_days"] < limit else row["mttr_days"] / limit


def verification(row: dict) -> float | None:
    """Sign-off outweighing the repair — but only when the lag is long enough to
    act on. Beating a four-minute repair is not a bottleneck."""
    overhead = row["verification_overhead_days"]
    if not overhead or row["mttr_days"] is None or row["repaired_count"] < MIN_REPAIRED:
        return None
    if overhead < MIN_OVERHEAD_DAYS or overhead <= row["mttr_days"]:
        return None
    return overhead / MIN_OVERHEAD_DAYS


def proof_quality(row: dict) -> float | None:
    """Work coming back rejected wastes a second dispatch."""
    if row["proof_rejection_rate"] is None or row["proofs"] < MIN_PROOFS:
        return None
    return (
        None if row["proof_rejection_rate"] < REJECTION_RATE
        else row["proof_rejection_rate"] / REJECTION_RATE
    )


if __name__ == "__main__":
    profile = {
        "group": "Block A|L3", "total": 10, "open": 2, "severity_mix": {},
        "duplicate_rate": 0.0, "window_days": 30, "recent": 6, "prior": 2,
        "trend_pct": 200.0, "repeat_rate": 0.0, "distinct_categories": 4,
    }
    mttr_row = {
        "group": "lighting", "repaired_count": 5, "mttr_days": 2.0, "mttc_days": 3.0,
        "median_repair_days": 2.0, "verification_overhead_days": None,
    }
    cluster = {"id": "c1", "cluster_key": "lighting|Block A|L3", "issue_count": 9,
               "issue_count_live": 6, "active": True,
               "recommendation": "Inspect the distribution board."}

    # A cluster with no recommendation yet has nothing to escalate; one that has
    # stopped accruing members scores below 1.0 and sinks down the ranking.
    assert systemic(cluster, 3) == 2.0
    assert systemic({**cluster, "recommendation": None}, 3) is None
    assert systemic({**cluster, "issue_count_live": 1, "active": False}, 3) < 1.0

    # Trend fires on a real jump, not on two tickets that happen to double one.
    assert trend(profile) == 4.0
    assert trend({**profile, "recent": 2, "prior": 1}) is None
    assert trend({**profile, "trend_pct": 20.0}) is None
    # no prior window is no baseline, not no change
    assert trend({**profile, "trend_pct": None, "prior": 0}) is None

    # Repeat rate needs something to repeat against.
    chronic = {**profile, "repeat_rate": 0.6}
    assert repeat(chronic, "floor") == 1.2
    assert repeat(chronic, "category") is None
    # the real snapshot's case: one category in the window, so (n-1)/n is
    # arithmetic and the rule must stay silent however high it reads
    assert repeat({**chronic, "repeat_rate": 0.96, "distinct_categories": 1}, "floor") is None

    assert duplicates({**profile, "duplicate_rate": 0.6}) == 2.0
    assert duplicates({**profile, "duplicate_rate": 0.6, "total": 3}) is None

    # An asset is only an asset if it was actually identified.
    assert asset_mtbf({"group": "DIC-AC-0032", "issue_count": 8, "mtbf_days": 30.0}) == 2.0
    assert asset_mtbf({"group": "DIC-AC-0032", "issue_count": 8, "mtbf_days": 90.0}) is None
    assert asset_mtbf({"group": "DIC-AC-0032", "issue_count": 2, "mtbf_days": 3.0}) is None
    assert asset_mtbf({"group": "(unspecified)", "issue_count": 2173, "mtbf_days": 0.19}) is None

    # The baseline excludes thin groups, or they drag it down until every group
    # with real volume looks slow — the equipment grouping's actual failure.
    thin = [{**mttr_row, "group": f"g{i}", "repaired_count": 1, "mttr_days": 0.1}
            for i in range(5)]
    assert repair_baseline(thin) is None
    assert repair_baseline([*thin, mttr_row]) == 2.0
    assert repair_baseline([]) is None
    base = repair_baseline([*thin, mttr_row])
    assert slow_repair({**mttr_row, "mttr_days": 12.0}, base) == 3.0
    assert slow_repair({**mttr_row, "mttr_days": 3.0}, base) is None
    assert slow_repair({**mttr_row, "mttr_days": 12.0, "repaired_count": 2}, base) is None
    assert slow_repair({**mttr_row, "mttr_days": 12.0}, None) is None

    # Sign-off must both beat the repair and be long enough to act on.
    assert verification({**mttr_row, "verification_overhead_days": 5.0}) == 5.0
    assert verification({**mttr_row, "verification_overhead_days": 0.5}) is None
    assert verification({**mttr_row, "mttr_days": 0.04,
                         "verification_overhead_days": 0.18}) is None
    assert verification({**mttr_row, "mttr_days": 3.0,
                         "verification_overhead_days": 2.0}) is None
    assert verification({**mttr_row, "repaired_count": 1, "mttr_days": 0.1,
                         "verification_overhead_days": 2.94}) is None

    vendor = {"assignee": "acme", "work_orders": 9, "proofs": 8, "avg_repair_hours": 3.0,
              "proof_rejection_rate": 0.75}
    assert proof_quality(vendor) == 1.5
    assert proof_quality({**vendor, "proofs": 2}) is None
    # an assignee with no proofs yet has no quality signal, not a perfect one
    assert proof_quality({**vendor, "proofs": 0, "proof_rejection_rate": None}) is None

    print("insights: ok")
