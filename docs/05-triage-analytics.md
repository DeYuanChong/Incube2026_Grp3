# 05 — Triage & Analytics

The triage service keeps a denormalized snapshot (`issue_facts`) of all issues,
refreshed from the reporting service on `issue.created` / `issue.closed` events
and via `POST /analytics/sync`. All macro-level analysis runs on this snapshot,
never on reporting's live DB.

## Systemic-fault detection (macro level)

Goal: surface deeper root problems that individual tickets hide.

1. **Cluster key**: `category | building | floor`. Equipment is deliberately
   not part of the key — `cluster_key` is unique, so adding it later is a
   migration, and equipment names are too sparse to cluster on today.
2. A cluster is flagged **systemic** when it accumulates
   `SYSTEMIC_MIN_COUNT` (default 3) issues within `SYSTEMIC_WINDOW_DAYS`
   (default 90).
3. For each flagged cluster the LLM produces a **preventive / prescriptive
   maintenance recommendation**, e.g. *"4 lighting failures on Block A Level 3 in
   6 weeks — likely a shared ballast/circuit fault; inspect the distribution
   board rather than replacing tubes individually."*
4. New issues landing in a flagged cluster get `systemic_flag=true` in their
   triage result and continue their normal lifecycle. The cluster's
   `issue_count` and `last_seen` are refreshed on every run, so both are
   as-of `updated_at`, not live — a cluster whose window has rolled off keeps
   its last computed count until a new member arrives.

## Systemic escalation (admin-raised issue)

Triage does not create, draft, or hold anything for the admin. When a cluster
first crosses the threshold it **notifies the admin once**, with the LLM's
recommendation as the body. The admin decides what to do with it, and if the
answer is "raise this as work", they file an ordinary issue under their own name
through the normal reporter flow. Nothing about that issue is special afterwards:
it is triaged, gets a work order, and needs proof and verification like any other.

```mermaid
sequenceDiagram
    participant R as Reporter
    participant T as Triage
    participant N as Notification
    participant A as Admin
    participant M as Maintainer
    R->>T: issue.created (ordinary ticket)
    T->>T: cluster crosses SYSTEMIC_MIN_COUNT
    T->>N: issue.escalated (cluster + recommendation)
    N->>A: one admin notification
    A->>A: reviews cluster via GET /analytics/systemic
    A->>M: files an ordinary issue in their own name → normal path
```

- **Emitted exactly once per cluster.** The event fires on the run that first
  writes `cluster.recommendation`, which is already a once-only latch
  (`if not cluster.recommendation`). No new column, and a failed LLM call simply
  retries on the next member rather than emitting a half-empty notification.
- **Payload is cluster-shaped**, not issue-shaped: `cluster_id`, `cluster_key`,
  `issue_count`, `window_days`, `recommendation`. There is no `issue_id` at this
  point — nothing exists in reporting — so the notification service needs its own
  case rather than the `payload.issue_id` fallback the other rules share.
- **No new endpoint.** `GET /analytics/systemic` already returns clusters with
  their recommendations; the notification points the admin at it.
- **Accepted cost**: the admin's issue lands in the same cluster it came from,
  inflating `issue_count` by one and slightly shortening that group's MTBF.
  Re-notification is not a risk, since `recommendation` is already set. There is
  no link back from the issue to the cluster, so triage cannot tell an
  admin-raised systemic issue from an ordinary report — deliberate, in exchange
  for zero new schema.

## Profiles

- **Location profile** (`GET /analytics/profiles?by=location`): issue counts,
  severity mix, open backlog and repeat-rate per building/floor.
- **Issue profile** (`by=category`): volume, trend (last 30d vs prior 30d),
  median resolution time, duplicate rate per category.
- **Equipment**: extracted `equipment_name` frequencies — which assets fail most.

## Metrics

### MTBF — Mean Time Between Failures
Signal for deeper root problems: a short MTBF for a cluster means the same thing
keeps breaking.

```
For a group g (category|location|equipment), order issues by created_at:
MTBF(g) = mean(created_at[i+1] - created_at[i])        # requires ≥ 2 issues
```

Reported in days, grouped by `category`, `building`, `floor`, or `equipment`.
Low MTBF + systemic flag ⇒ recommend preventive maintenance instead of repeat
repairs.

### MTTR — Mean Time To Repair
Signal on maintenance/vendor performance (speed; pair with proof-rejection rate
for quality).

```
MTTR(g) = mean(fixed_at - created_at)   over issues with fixed_at set
```

Also exposed: `MTTC` (mean time to close, `closed_at - created_at`) and the
verification overhead (`closed_at - fixed_at`).

### Quality signals (vendor performance beyond speed)
Served by `GET /analytics/vendor-performance`, which reads the `fixverify` schema
directly — the sanctioned read-only cross-schema access in the shared PostgreSQL DB:
- **Proof rejection rate**: rejected proofs / total proofs per assignee — AI
  relevance rejections plus human rejections.
- **Avg repair hours**: work order `started_at → completed_at` per assignee.
- **Resolved-on-arrival count**: dispatches where no work was needed (a signal
  for reporter education / self-service opportunities).
- **Reopen rate**: issues that went `verified → in_progress` (reporter dispute).

## Duplicate handling & the dispatch gate

Duplicates (same defect, different reporters) are linked via
`duplicate_group_id` (see doc 04 §4). Severity-bump rule: `duplicate_count ≥ 3`
bumps suggested severity one level — multiple reports indicate wider impact.
Duplicate issues stay open and visible to their own reporters (each reporter's
dashboard tracks their submission).

**One defect, one dispatch.** Fixverify's `issue.triaged` handler skips work
order creation when the issue is a duplicate whose group primary already has a
live work order (`fixverify/app/dedupe.py::is_covered_by_primary`) — the
duplicate rides the primary's dispatch instead of sending maintenance out twice.
A primary whose work order is already `verified` or `rejected` is finished, so a
fresh report against it is treated as a recurrence and does get its own work
order.

The gate has a known consequence: a gated issue stays at `triaged` with no work
order of its own, and nothing closes it when the primary is resolved (see below).
For the PoC an admin closes it via the status API.

## Known gaps (as built)

Recorded so they are not rediscovered during implementation. Neither is fixed.

- **`duplicate_count` counts candidates, not confirmed duplicates.**
  `pipeline._find_duplicate` sets `group_size = len(candidates) + 1` when *any*
  candidate is confirmed, where `candidates` is the trigram pre-filter's top 5 —
  so it counts unrelated issues at the same location. That number feeds the
  `duplicate_count >= 3` severity bump in `_apply_hard_rules` and is posted to
  reporting as `duplicate_count`. One genuine duplicate plus two unrelated
  same-location issues silently bumps severity a level.
- **`issue.escalated` is not emitted yet.** The section above describes the
  intended behaviour; `pipeline._systemic_check` writes `cluster.recommendation`
  but publishes nothing, and `notification/app/rules.py` has no case for the
  event. This is the next piece of work, and it is the whole of it.
- **Duplicate groups do not resolve together.** `duplicate_group_id` now gates
  dispatch (above), but nothing closes the other members when the primary is
  resolved. A gated duplicate sits at `triaged` until an admin closes it by hand.
  The fix is a rule in reporting on `issue.closed` — deliberately not built yet,
  because it needs a decision on whether the group closes with the primary or
  each reporter still confirms their own ticket.

## Triage pipeline (per issue)

```mermaid
flowchart TD
    A[issue.created event] --> B[Fetch issue from reporting]
    B --> C[Sync into issue_facts]
    C --> D[Duplicate detection<br/>heuristic candidates + LLM confirm]
    D --> E[Systemic cluster check]
    E --> F[LLM severity/urgency suggestion<br/>+ equipment extraction]
    F --> G[Apply hard rules<br/>duplicates bump severity, security ≥ urgent, hazard keywords → emergency]
    G --> H[Store triage_result]
    H --> I[POST triage-result to reporting<br/>status → triaged, ETA recomputed]
    I --> J[emit issue.triaged]
    E --> K{cluster newly systemic?<br/>no recommendation yet}
    K -- yes --> L[LLM writes cluster recommendation]
    L --> M[emit issue.escalated<br/>→ one admin notification]
```

The escalation branch is a side effect, not a gate: the triggering issue proceeds
down `I → J` regardless, and nothing in the pipeline waits on the admin. Any
issue the admin subsequently files re-enters at `A` as an ordinary
`issue.created`.

Admins can re-run the pipeline or override severity/urgency on the triage board;
overrides are kept for measuring AI suggestion accuracy over time. A re-run
appends another `triage.results` row rather than replacing the previous one.

### Example result

`POST /api/triage/run/{issue_id}` for the 4th lighting report on Block A / L3 —
the run that tips the cluster over `SYSTEMIC_MIN_COUNT`. The response is the
stored `triage.results` row, serialized whole:

```json
{
  "id": "b6f2c1a4-9d3e-4a77-8c21-5e0f7a2b91dd",
  "issue_id": "3f9a7c02-1b4d-4e88-9a10-2c6d5b8e4f31",
  "suggested_severity": "medium",
  "suggested_urgency": "routine",
  "severity_rationale": "A corridor light out affects circulation but poses no safety or security risk.",
  "equipment_extracted": "ceiling light",
  "duplicate_of_issue_id": null,
  "duplicate_confidence": null,
  "systemic_flag": true,
  "systemic_cluster_id": "e41c8d70-55a2-4f19-b3c6-7d9e0a1f2b48",
  "admin_confirmed": false,
  "admin_override_severity": null,
  "admin_override_urgency": null,
  "created_at": "2026-09-01T04:12:33.481920+00:00"
}
```

Side effects of that single call:

1. `triage.issue_facts` — row upserted for the issue.
2. `triage.systemic_clusters` — `cluster_key: "lighting|Block A|L3"`,
   `issue_count: 4`, `last_seen` bumped, `recommendation` written for the first
   time on this run.
3. `triage.results` — the row above, appended.
4. `POST /issues/{id}/triage-result` to reporting:
   `{"severity": "medium", "urgency": "routine", "equipment_name": "ceiling light",
   "duplicate_group_id": null, "duplicate_count": 1, "is_critical_system": false}`.
   A failure here is logged, not raised — the local result stands even if the
   write-back does not.
5. `issue.escalated` published, because this run wrote `recommendation`:
   `{"cluster_id": "e41c8d70-…", "cluster_key": "lighting|Block A|L3",
   "issue_count": 4, "window_days": 90, "recommendation": "…"}`.

Note `is_critical_system` is produced by the LLM and forwarded to reporting but
is **not** a column on `triage.results`, so it does not appear in the response.
