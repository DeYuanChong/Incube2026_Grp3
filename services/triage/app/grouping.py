"""The two pure decisions behind duplicate grouping and clustering (docs/05).

Both are formulas with no DB and no LLM in them, so they live apart from the
pipeline and are checked with plain `python3 grouping.py`.
"""


def cluster_key(category: str, building: str, floor: str) -> str:
    """A cluster's identity: category at a location. One formula, used by the
    per-issue check and by the live counts in analytics, so the two cannot
    drift. Not parseable back — a building containing "|" splits wrong — so
    read the parts off the fact, never off the key."""
    return f"{category}|{building}|{floor}"


def pick_primary(
    confirmed: list[tuple[str, str, float]],
) -> tuple[str | None, float, int]:
    """`confirmed` is (issue_id, created_at, confidence) for every candidate the
    LLM confirmed as the same defect. Returns (primary, confidence, group_size).

    The primary is the **oldest** member, not the most similar one. Oldest is
    the original report, so every member of a group names the same primary and
    chains collapse — a chain leaves the last member pointing at an issue that
    is itself a duplicate, which has no work order of its own, which is exactly
    what fixverify's dispatch gate needs to find (`dedupe.is_covered_by_primary`).

    `group_size` counts confirmations plus this issue, so it is how many
    duplicates exist rather than how full the candidate pre-filter was.

    created_at is compared as a string: every timestamp in the snapshot comes
    from `now_iso()` in UTC, so ISO-8601 sorts lexicographically.
    """
    if not confirmed:
        return None, 0.0, 1
    issue_id, _, confidence = min(confirmed, key=lambda c: c[1])
    return issue_id, confidence, len(confirmed) + 1


if __name__ == "__main__":
    assert cluster_key("lighting", "Block A", "L3") == "lighting|Block A|L3"

    # nothing confirmed → not a duplicate, and the group is this issue alone
    assert pick_primary([]) == (None, 0.0, 1)
    # one confirmation → that one, group of two. The candidate pool could have
    # held five; the count follows the confirmations, not the pool.
    assert pick_primary([("a", "2026-08-01T00:00:00+00:00", 0.9)]) == ("a", 0.9, 2)
    # several → the oldest wins even when a newer one was more confident, and
    # even when the newer one was seen first
    picked = pick_primary([
        ("c", "2026-08-20T00:00:00+00:00", 0.99),
        ("a", "2026-08-01T00:00:00+00:00", 0.71),
        ("b", "2026-08-10T00:00:00+00:00", 0.85),
    ])
    assert picked == ("a", 0.71, 4), picked
    # chain collapse: b and c each confirm against the same pool, so both name
    # a — the original — rather than b naming c and c naming a
    pool = [("a", "2026-08-01T00:00:00+00:00", 0.8),
            ("b", "2026-08-10T00:00:00+00:00", 0.8)]
    assert pick_primary(pool)[0] == pick_primary(pool[:1])[0] == "a"
    print("grouping: ok")
