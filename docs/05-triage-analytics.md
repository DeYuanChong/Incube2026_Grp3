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
   triage result and continue their normal lifecycle — the systemic problem is
   escalated separately, as its own issue (below).

## Systemic escalation → admin → maintainer

An escalation is **a new issue**, not a change to the one that triggered it. The
reporter's ticket ("light out in 3-12") still gets fixed on the normal path; the
systemic problem ("Level 3 distribution board") is a separate piece of work with
its own lifecycle, severity, work order and metrics. The admin is the reporter
of that new issue — they own it, and it appears under their name.

```mermaid
sequenceDiagram
    participant R as Reporter
    participant T as Triage
    participant A as Admin panel
    participant P as Reporting
    participant M as Maintainer
    R->>T: issue.created (ordinary ticket)
    T->>T: pipeline flags systemic cluster
    T->>A: issue.escalated — draft title/description/recommendation
    A->>A: admin edits the draft, or accepts as-is
    A->>P: POST /issues (X-User: admin) → escalation issue
    P->>T: issue.created → normal triage
    T->>M: normal triaged → work order → maintainer
```

1. **Report** — reporter files the issue as usual. It is never blocked or
   re-purposed by what follows.
2. **Detect** — the triage pipeline flags the cluster as systemic
   (`systemic_flag=true`, `systemic_cluster_id` set on the triage result).
3. **Draft** — for a cluster with no escalation issue yet, the LLM drafts one on
   the cluster row (`draft_title`, `draft_description`: the pattern, the
   evidence — member issue ids, count in window, MTBF — and the recommended
   preventive action) and triage emits `issue.escalated`. Nothing exists in
   reporting yet; the draft is a proposal sitting in the admin panel's
   **Escalations** queue next to the cluster's member issues.
4. **Admin sends** — `POST /triage/escalations/{cluster_id}/send`, which is the
   admin either accepting the draft (no body) or adjusting it
   (`{title?, description?, category?, building?, floor?, severity_hint?}`).
   Triage calls reporting's `POST /issues` with the admin's identity headers, so
   `reporter_name` is the admin. The new issue's `origin_cluster_id` points back
   at the cluster, and the cluster records `escalated_issue_id` /`escalated_at`
   so it will not draft a second one.
5. **Maintainer works it** — from here nothing is special. The escalation issue
   is triaged, gets a work order, is assigned, and needs proof and verification
   like any other. The maintainer sees "inspect the Level 3 distribution board"
   because that is what the issue says, not because of a side channel.

Two things that fall out of this shape:

- **Escalation issues are excluded from clustering.** An issue with
  `origin_cluster_id` set is skipped when `issue_facts` is grouped, otherwise the
  escalation counts toward the very cluster that produced it and re-triggers.
- **Closing the escalation does not close its members.** They are independent
  issues; the reporters still confirm their own tickets. A cluster whose
  escalation is closed becomes eligible to draft again if it keeps accumulating.

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
    I --> J[emit issue.triaged]
    E --> K{systemic cluster<br/>with no escalation issue?}
    K -- yes --> L[LLM drafts escalation issue<br/>on the cluster row]
    L --> M[emit issue.escalated<br/>admin panel Escalations queue]
    M --> N[Admin accepts or edits, then sends<br/>→ POST /issues as the admin]
    N --> A
```

The escalation branch is a side effect of the pipeline, not a gate on it: the
triggering issue proceeds down `I → J` regardless. The escalation issue that the
admin sends re-enters at `A` as an ordinary `issue.created`.

Admins can re-run the pipeline or override severity/urgency on the triage board;
overrides are kept for measuring AI suggestion accuracy over time.
