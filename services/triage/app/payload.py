"""Shape of the triage endpoint's single per-issue result (docs/05).

Issue-level fields answer "what happens to this ticket". The cluster-level
preventive recommendation is a different question with a different owner, so it
rides along in a nullable `systemic_payload` instead of being folded into them.

Kept dependency-free so the check below runs with plain `python3 payload.py`.
"""


def with_systemic(result: dict, cluster: dict | None, window_days: int) -> dict:
    """`result` is the serialized triage.results row, `cluster` the serialized
    systemic_clusters row this issue landed in (or None).

    The payload is present only once the cluster has a recommendation to give:
    a flagged cluster whose LLM call has not landed yet still sets
    `systemic_flag`, but has nothing to escalate.
    """
    escalation = None
    if cluster and cluster.get("recommendation"):
        escalation = {
            "cluster_id": cluster["id"],
            "cluster_key": cluster["cluster_key"],
            "issue_count": cluster["issue_count"],
            "window_days": window_days,
            "recommendation": cluster["recommendation"],
        }
    return {**result, "systemic_payload": escalation}


if __name__ == "__main__":
    row = {"issue_id": "i1", "suggested_severity": "medium", "systemic_flag": False}
    flagged = {**row, "systemic_flag": True}
    cluster = {"id": "c1", "cluster_key": "lighting|Block A|L3",
               "issue_count": 4, "recommendation": "Inspect the distribution board."}

    # no cluster → issue-level answer only
    assert with_systemic(row, None, 90) == {**row, "systemic_payload": None}
    # flagged but the recommendation has not landed yet → nothing to escalate
    assert with_systemic(flagged, {**cluster, "recommendation": None}, 90)["systemic_payload"] is None
    # flagged with a recommendation → cluster-shaped payload alongside the row
    out = with_systemic(flagged, cluster, 90)
    assert out["suggested_severity"] == "medium"        # issue fields untouched
    assert out["systemic_payload"] == {
        "cluster_id": "c1", "cluster_key": "lighting|Block A|L3",
        "issue_count": 4, "window_days": 90,
        "recommendation": "Inspect the distribution board.",
    }
    print("payload: ok")
