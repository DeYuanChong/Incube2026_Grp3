# 05 — Triage & Analytics

The triage service keeps a denormalized snapshot (`issue_facts`) of all issues,
refreshed from the reporting service on `issue.created` / `issue.closed` events
and via `POST /analytics/sync`. All macro-level analysis runs on this snapshot,
never on reporting's live DB.

## Systemic-fault detection (macro level)

Goal: surface deeper root problems that individual tickets hide.

1. **Cluster key**: `category | building | floor` (and `equipment_name` when
   present).
2. A cluster is flagged **systemic** when it accumulates
   `SYSTEMIC_MIN_COUNT` (default 3) issues within `SYSTEMIC_WINDOW_DAYS`
   (default 90).
3. For each flagged cluster the LLM produces a **preventive / prescriptive
   maintenance recommendation**, e.g. *"4 lighting failures on Block A Level 3 in
   6 weeks — likely a shared ballast/circuit fault; inspect the distribution
   board rather than replacing tubes individually."*
4. New issues landing in a flagged cluster get `systemic_flag=true` in their
   triage result and are **escalated to the admin** instead of being dispatched
   automatically (below).

## Systemic escalation → admin → maintainer

A normal issue goes `triaged → work order` with no human gate: fixverify
auto-creates the work order on `issue.triaged`. A **systemic** issue does not —
the fix is likely not "repair this ticket", so an admin decides what the
maintainer is actually asked to do.

```mermaid
sequenceDiagram
    participant R as Reporter
    participant T as Triage
    participant A as Admin panel
    participant F as Fix & Verify
    participant M as Maintainer
    R->>T: issue.created
    T->>T: pipeline detects systemic cluster
    T->>A: issue.escalated (brief + recommendation)
    A->>A: admin edits the brief, or accepts as-is
    A->>T: POST /triage/results/{id}/dispatch {brief}
    T->>F: issue.dispatched → work order created
    F->>M: assigned work order carries the brief
```

1. **Report** — reporter files the issue as usual.
2. **Detect** — the triage pipeline flags the cluster as systemic
   (`systemic_flag=true`, `systemic_cluster_id` set).
3. **Escalate** — triage writes an `escalation_brief` on the triage result
   (LLM: what the pattern is, the evidence — sibling issue ids, MTBF, count in
   window — and the recommended action) and emits `issue.escalated`. The issue
   sits at `triaged`; fixverify skips auto-creation while `systemic_flag` is set.
   The admin panel lists it under **Escalations** with the cluster's other issues.
4. **Admin decides** — one endpoint covers both branches:
   `POST /triage/results/{issue_id}/dispatch {brief?}`.
   - *Accept*: no `brief` in the body — the LLM's `escalation_brief` is sent
     verbatim.
   - *Adjust*: `brief` supplied — it overwrites `escalation_brief` (the LLM's
     original stays in `systemic_clusters.recommendation`, so admin edit rate
     is measurable the same way severity overrides are).
   Either way the result records `dispatched_by` / `dispatched_at` and triage
   emits `issue.dispatched`.
5. **Maintainer works it** — fixverify creates the work order on
   `issue.dispatched` and stores the brief as the work order's instruction, so
   the maintainer sees "inspect the Level 3 distribution board", not "replace
   the tube in room 3-12". From here the flow is the normal Fix & Verify path
   (evidence recommendation, proof upload, verification).

An admin can also close the escalation without dispatching (the systemic work is
handled outside the ticket, e.g. a planned shutdown) — the issue keeps its normal
lifecycle and the cluster stays flagged for the next report.

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

## Duplicate handling & escalation

Duplicates (same defect, different reporters) are linked via
`duplicate_group_id` (see doc 04 §4). Escalation rule: `duplicate_count ≥ 3`
bumps suggested severity one level — multiple reports indicate wider impact.
Duplicate issues stay open and visible to their own reporters (each reporter's
dashboard tracks their submission); resolution of the group's primary issue
resolves the group.

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
    I --> K{systemic_flag?}
    K -- no --> J[emit issue.triaged<br/>fixverify auto-creates work order]
    K -- yes --> L[LLM escalation brief<br/>pattern + evidence + recommendation]
    L --> M[emit issue.escalated<br/>admin panel Escalations queue]
    M --> N[Admin accepts or edits the brief<br/>POST /triage/results/id/dispatch]
    N --> O[emit issue.dispatched<br/>work order carries the brief]
```

Admins can re-run the pipeline or override severity/urgency on the triage board;
overrides are kept for measuring AI suggestion accuracy over time. Systemic
issues additionally wait on the admin dispatch step above before any work order
exists.
