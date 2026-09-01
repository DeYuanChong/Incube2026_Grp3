# Triage component — backend correctness + the analytics doc 05 promises

## Context

`feat/triage` has reshaped the component's *output*: one result per issue, with the
cluster-level finding in a nullable `systemic_payload` (now carrying its member
`issues`), `is_critical_system` retired into `severity_rationale`, escalation
settled as another component's job, and the redundant `/triage` route prefix gone.

What remains is the component's *inside*. Two classes of problem:

1. **Correctness.** `duplicate_count` reports how busy a location is rather than how
   many duplicates exist, which both fires phantom severity bumps and — via chained
   group primaries — defeats fixverify's one-defect-one-dispatch gate.
   `GET /analytics/systemic` never decays, so a cluster fixed in March still tops the
   admin's list in September. And `issue_facts.status` goes stale because cancelled
   issues emit no event at all.
2. **Doc 05 over-promises analytics.** `profiles()` returns `total`, `open` and
   `severity_mix`; the doc's repeat-rate, trend, median resolution time, duplicate
   rate, equipment profile and verification overhead are not computed. The last
   commit made doc 05 honest about this. This plan makes the code match the doc
   instead.

Outcome: the numbers triage reports mean what they say, and the endpoints return
what doc 05 says they return.

**Hard constraint discovered during planning:** `pg-data` is a persistent named
volume and `init_db()` calls `SQLModel.metadata.create_all`, which creates missing
tables but **never alters existing ones**. Any new column silently will not exist on
a running deployment. New columns must ship with idempotent DDL in `init_db()`,
which already runs raw SQL there (`CREATE SCHEMA`, `CREATE EXTENSION`).

## Scope

In: backend correctness, and the analytics doc 05 documents as designed.
Out (user's call): surfacing any of it in the frontend, and retrofitting self-checks
onto existing untested code. New non-trivial logic still leaves one runnable
`__main__` assert check, per the repo's existing pattern
(`services/fixverify/app/dedupe.py`, `services/triage/app/payload.py`).
`docs/03-api-contracts.md` stays untouched and stays stale — see Known drift.

---

## A. Duplicate detection: count confirmations, and pick the oldest member

`pipeline._find_duplicate` (services/triage/app/pipeline.py:43) sets
`group_size = len(candidates) + 1` on the **first** confirmation, where `candidates`
is the trigram pre-filter's `limit(5)`. Two consequences:

- The count is decoupled from reality — one genuine duplicate reports `6` whenever
  the pre-filter is full. Every threshold from 3 to 6 still trips on a single
  duplicate; 7 makes `DUPLICATE_BUMP_THRESHOLD` unreachable. **Raising the
  threshold cannot fix this** (verified by replaying the logic over all pool sizes).
- It returns the *most trigram-similar* confirmed member as the group primary. If
  that member is itself a duplicate riding someone else's work order, it has no work
  order of its own, so `fixverify/app/main.py:_handle_event` looks up
  `WorkOrder.issue_id == group_id`, finds nothing, passes `primary_status=None` to
  `dedupe.is_covered_by_primary`, and **dispatches anyway**. Chained duplicates
  defeat the gate.

Change: scan every candidate, collect confirmations, and select the **oldest** by
`created_at` as the primary. Oldest is the original report, so every member of a
group converges on the same primary and chains collapse — which is the root-cause
fix for the gate, not just the count.

- New dependency-free module `services/triage/app/grouping.py` holding the two pure
  decisions, with a `python3 grouping.py` assert check:
  - `pick_primary(confirmed)` → `(issue_id | None, confidence, group_size)` where
    `group_size = len(confirmed) + 1`.
  - `cluster_key(category, building, floor)` — the single formula for the key,
    reused by `pipeline._cluster_key` and by the decay join in D/B below, so the two
    cannot drift.
- Lift the bare `0.6` into `config.DUPLICATE_MIN_CONFIDENCE`.
- Cost: always up to 5 `ai_client.is_duplicate` calls. Worst case is unchanged —
  the no-duplicate path already scanned all five; only the found-early case loses
  its short-circuit.

## B. `GET /analytics/systemic` must decay

`main.systemic` sorts on the stored `SystemicCluster.issue_count`, refreshed only
when `_systemic_check` runs — i.e. when a new member arrives. A remediated cluster
holds its peak count forever. (The per-issue `systemic_payload` already decays, since
`issue_count` there is `len(issues)` from a live query.)

Add to `analytics.py` a live count for every cluster in one pass:

- One `GROUP BY category, building, floor` over `issue_facts` inside
  `SYSTEMIC_WINDOW_DAYS`, keyed with `grouping.cluster_key(...)` built **from the
  fact columns** — never by splitting `cluster_key`, which is not safely parseable
  when a building or floor contains `|`.
- Join to the cluster rows in Python; return each with `issue_count_live` and
  `active` (`live >= SYSTEMIC_MIN_COUNT`), sorted by live count descending.
- Keep the stored `issue_count` in the response as the detector's record. Doc 05
  already explains that the two answer different questions.

## C. Fact freshness

`issue_facts.status` only refreshes on `issue.closed` and `POST /analytics/sync`, so
stale statuses leak into `_find_duplicate`'s open-candidate filter and `profiles()`'
open backlog.

- **In-component:** `main._handle_event` — widen the closed branch to
  `elif event_type in ("issue.closed", "issue.status_changed")`. Both do the same
  fetch-and-sync. Requires one line in `services/gateway/app/subscriptions.py` adding
  `TRIAGE_URL` to `issue.status_changed`, which reporting already publishes.
- **Cross-service, flag before doing:** `reporting/app/main.py::cancel_issue` (line
  302) publishes **nothing** — no event of any kind. A cancelled issue therefore
  never reaches triage, stays "reported" in `issue_facts`, and keeps counting as an
  open duplicate candidate and a live cluster member. No triage-side code can fix
  this. The fix is one `background.add_task(events.publish, "issue.status_changed",
  …)` in that handler, mirroring the other three publishes. Strike this item if you
  want reporting left alone; the staleness then stands for cancellations only.

## D. Build the analytics doc 05 documents

All in `services/triage/app/analytics.py`, all arithmetic over the existing
`_grouped` helper and stdlib (`statistics.median`), unless noted.

| Metric | Where | Note |
|---|---|---|
| Verification overhead | `mttr()` | `mean(closed_at - fixed_at)` over facts with both |
| Median resolution time | `mttr()` | `statistics.median` over the existing `repairs` list |
| Trend, 30d vs prior 30d | `profiles()` | counts in the two windows + percent change |
| Repeat rate | `profiles()` | share of a group's issues that are not the first of their category in that group inside the window |
| Equipment profile | `profiles()` | add `equipment` to the `by` pattern in `main.get_profiles`; `GROUP_KEYS["equipment"]` already exists |
| Duplicate rate | `profiles()` | needs the column below |

**Duplicate rate needs one new column.** `IssueFact` carries no duplicate field, and
`triage.results` is append-only so counting rows there double-counts re-runs. Add
`duplicate_group_id: str | None` to `IssueFact`, set it in
`pipeline.sync_issue_fact` from the reporting payload (which already carries it), and
ship the DDL in `db.init_db()` **after** `create_all` — the table must exist first:

```sql
ALTER TABLE triage.issue_facts ADD COLUMN IF NOT EXISTS duplicate_group_id TEXT
```

Existing rows backfill on their next sync, or immediately via
`POST /analytics/sync`. Then update doc 05's Profiles and Metrics sections, which
currently list these as designed-but-not-served.

---

## Files

- `services/triage/app/grouping.py` — new, dependency-free, self-checking
- `services/triage/app/pipeline.py` — `_find_duplicate`, `_cluster_key`, `sync_issue_fact`
- `services/triage/app/analytics.py` — live cluster counts, the six metrics
- `services/triage/app/main.py` — `systemic` response, `get_profiles` pattern, `_handle_event`
- `services/triage/app/models.py` — `IssueFact.duplicate_group_id`
- `services/triage/app/db.py` — idempotent `ALTER TABLE` after `create_all`
- `services/triage/app/config.py` — `DUPLICATE_MIN_CONFIDENCE`
- `docs/05-triage-analytics.md` — Profiles, Metrics, duplicate-count gap, systemic decay
- `services/gateway/app/subscriptions.py` — one line (C)
- `services/reporting/app/main.py` — one publish in `cancel_issue` (C, strikeable)

## Verification

1. `python3 grouping.py` and `python3 payload.py` in `services/triage/app` — assert
   checks pass with no dependencies installed.
2. `docker compose up -d --build` (README: `--build` is mandatory after changes).
   Confirm triage starts — this exercises the new `ALTER TABLE` on the **existing**
   `pg-data` volume, which is the risky step.
3. `curl -XPOST localhost:8000/api/triage/analytics/sync` to backfill
   `duplicate_group_id` on existing facts.
4. File 3 lighting issues at one building/floor via `POST /api/reporting/issues`, then
   a 4th near-identical one. Check `GET /api/triage/results/{id}`:
   `systemic_payload.issues` lists the members, `duplicate_count` equals confirmed
   duplicates + 1 (not the candidate-pool size), `duplicate_of_issue_id` is the
   **oldest** member.
5. `GET /api/triage/analytics/systemic` — `issue_count_live` and `active` present;
   confirm a cluster built from back-dated issues outside the window reports
   `active: false` while the stored `issue_count` still shows its peak.
6. `GET /api/triage/analytics/profiles?by=location|category|equipment` and
   `GET /api/triage/analytics/metrics` — every field doc 05 lists is present.
7. Cancel a reported issue, then re-check `profiles()` open backlog drops (proves C).

## Explicitly not doing

- **Capping `systemic_payload.issues`.** Already marked with a `ponytail:` comment
  naming pagination as the upgrade. A cap needs a truncation flag and breaks the
  clean "the count *is* the list" invariant, for a problem that does not exist at
  PoC scale. Do it when a cluster is large enough to notice.
- **A remediation link** (`remediates_cluster_id` / `remediated_by_issue_id`).
  Settled: a fixed root cause shows up as a cluster that stops accruing members,
  which B makes visible. One nullable column with no backfill if it is ever wanted.
- **`POST /analytics/sync`.** Redundant with the webhook, but it is the manual
  backfill path step 3 depends on. Kept.
- **Frontend.** `api.triageResult`, `api.profiles` and `api.vendorPerformance` still
  have zero callers, so everything above remains invisible in the running app.

## Known drift

`docs/03-api-contracts.md` lists the pre-fix `/triage/run` and `/triage/results`
paths and still shows `is_critical_system` in the `POST /issues/{id}/triage-result`
body. Both are wrong. Left untouched by instruction.
