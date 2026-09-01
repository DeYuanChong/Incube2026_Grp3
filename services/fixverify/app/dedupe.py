"""Duplicate gate: a duplicate report rides its group primary's work order
instead of dispatching maintenance a second time for one defect (docs/05).

Kept dependency-free so the check below runs with plain `python3 dedupe.py`.
"""

# A primary in one of these has finished; a fresh report is a recurrence, not a
# duplicate ride-along, and deserves its own work order.
TERMINAL_STATUSES = ("verified", "rejected")


def is_covered_by_primary(
    issue_id: str, group_id: str | None, primary_status: str | None
) -> bool:
    """True when this issue's defect is already being worked under another issue.

    `primary_status` is the group primary's work order status, or None when the
    primary has no work order yet (nothing to ride — dispatch normally).
    """
    if not group_id or group_id == issue_id:
        return False
    return primary_status is not None and primary_status not in TERMINAL_STATUSES


if __name__ == "__main__":
    # not a duplicate at all
    assert not is_covered_by_primary("a", None, None)
    # primary is the issue itself (it *is* the group primary)
    assert not is_covered_by_primary("a", "a", "in_progress")
    # duplicate, primary actively being worked → gate it
    assert is_covered_by_primary("b", "a", "open")
    assert is_covered_by_primary("b", "a", "in_progress")
    assert is_covered_by_primary("b", "a", "awaiting_proof")
    assert is_covered_by_primary("b", "a", "pending_human_verification")
    # duplicate, but primary already finished → recurrence, dispatch it
    assert not is_covered_by_primary("b", "a", "verified")
    assert not is_covered_by_primary("b", "a", "rejected")
    # duplicate, primary has no work order yet → nothing to ride
    assert not is_covered_by_primary("b", "a", None)
    print("dedupe: ok")
