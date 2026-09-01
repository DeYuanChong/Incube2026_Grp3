"""Shape of the triage endpoint's single per-issue result (docs/05).

Issue-level fields answer "what happens to this ticket". The cluster-level
finding is a different question with a different owner, so it rides along in a
nullable `systemic_payload` instead of being folded into them.

Kept dependency-free so the check below runs with plain `python3 payload.py`.
"""


def with_systemic(
    result: dict, cluster: dict | None, issues: list[dict], window_days: int
) -> dict:
    """`result` is the serialized triage.results row, `cluster` the serialized
    systemic_clusters row this issue landed in (or None), `issues` that
    cluster's members as of now.

    The payload is present only once the cluster has a recommendation to give:
    a flagged cluster whose LLM call has not landed yet still sets
    `systemic_flag`, but has nothing to escalate.

    `issue_count` is `len(issues)` — the evidence and the number are the same
    query, so they cannot disagree. The cluster row keeps its own `issue_count`
    as the record of what the detector saw when it flagged.
    """
    escalation = None
    if cluster and cluster.get("recommendation"):
        escalation = {
            "cluster_id": cluster["id"],
            "cluster_key": cluster["cluster_key"],
            "issue_count": len(issues),
            "window_days": window_days,
            "recommendation": cluster["recommendation"],
            "issues": issues,
        }
    return {**result, "systemic_payload": escalation}


if __name__ == "__main__":
    row = {"issue_id": "i1", "suggested_severity": "medium", "systemic_flag": False}
    flagged = {**row, "systemic_flag": True}
    cluster = {"id": "c1", "cluster_key": "lighting|Block A|L3",
               "issue_count": 3, "recommendation": "Inspect the distribution board."}
    members = [{"issue_id": "i1", "reference_no": "ISS-004"},
               {"issue_id": "i2", "reference_no": "ISS-002"},
               {"issue_id": "i3", "reference_no": "ISS-001"},
               {"issue_id": "i4", "reference_no": "ISS-003"}]

    # no cluster → issue-level answer only
    assert with_systemic(row, None, [], 90) == {**row, "systemic_payload": None}
    # flagged but the recommendation has not landed yet → nothing to escalate
    assert with_systemic(flagged, {**cluster, "recommendation": None}, members, 90)[
        "systemic_payload"] is None
    # flagged with a recommendation → cluster payload alongside the untouched row
    out = with_systemic(flagged, cluster, members, 90)
    assert out["suggested_severity"] == "medium"
    assert out["systemic_payload"] == {
        "cluster_id": "c1", "cluster_key": "lighting|Block A|L3",
        "issue_count": 4, "window_days": 90,
        "recommendation": "Inspect the distribution board.",
        "issues": members,
    }
    # the count is the evidence, not the stored column: the cluster row still
    # says 3 (what the detector saw) while a 4th member has since landed
    assert cluster["issue_count"] == 3
    assert out["systemic_payload"]["issue_count"] == len(members) == 4
    # a window that has rolled off leaves a flagged cluster with thin evidence,
    # and the count shrinks with it rather than reporting a stale 3
    assert with_systemic(flagged, cluster, members[:1], 90)["systemic_payload"][
        "issue_count"] == 1
    print("payload: ok")
