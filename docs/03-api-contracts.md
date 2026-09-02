# 03 — API Contracts

All services speak JSON (uploads are multipart). Demo-mode identity headers on
every request: `X-User: <name>`, `X-Role: reporter|maintenance|admin`.

Frontend always calls the **gateway** (`http://localhost:8000`); paths below are
service-local. Gateway mapping: `/api/reporting/*→:8001/*`, `/api/triage/*→:8002/*`,
`/api/fixverify/*→:8003/*`, `/api/notifications/*→:8004/*`.

## Reporting service (:8001)

| Method & path | Purpose |
|---|---|
| `POST /issues` | Create issue. Body: `{category, title, description, building, floor, room?, equipment_name?}`. Runs AI categorization + ETA. Returns the issue incl. `ai_suggested_category` and `estimated_resolution_days`. Emits `issue.created`. |
| `GET /issues` | List. Filters: `status` (repeatable), `severity` (repeatable, `untriaged` matches an unset severity), `category`, `building`, `floor`, `reporter`, `q` (text), `limit`, `offset`. **Role-scoped** from `X-Role`/`X-User` on top of those filters: a reporter sees only issues they reported, maintenance only `in_progress`/`pending_verification`/`verified`/`closed`/`cancelled`, admin everything. |
| `POST /issues` | Create issue. Body: `{category, title, description?, building, floor, room?, equipment_name?, mobile_number, ack_confirmed}`. `description` is optional; `ack_confirmed` must be `true` (422 otherwise). Runs AI categorization. Returns the issue incl. `ai_suggested_category`. Emits `issue.created`. |
| `GET /issues` | List. Filters: `status`, `category`, `building`, `floor`, `reporter`, `q` (text), `limit`, `offset`. |
| `GET /issues/{id}` | Full issue + timeline (`issue_events`). |
| `PATCH /issues/{id}` | Reporter edits (title/description/location) while `status=reported`. |
| `POST /issues/{id}/accept-suggested-category` | Reporter accepts the AI category (`category_source=ai_accepted`). |
| `POST /issues/{id}/accept-suggested-title` | Reporter accepts the photo-derived title suggestion. |
| `POST /issues/{id}/accept-suggested-description` | Reporter accepts the photo-derived description suggestion. |
| `POST /issues/{id}/photos` | Multipart `file`. Only while `status=reported`. Runs vision verification against the issue's current category/title/description (docs/04 §7); recomputes `ai_suggested_category`/`ai_suggested_title`/`ai_suggested_description`/`photo_note` across all of the issue's photos. Emits `issue.photo_uploaded`. |
| `GET /issues/{id}/photos/{photo_id}/file` | Serve an uploaded photo. |
| `POST /issues/{id}/triage-result` | **Internal (triage svc)**: `{severity, urgency, equipment_name?, duplicate_group_id?, duplicate_count?, is_critical_system?}` → status `triaged`, emits `issue.triaged` timeline entry. |
| `POST /issues/{id}/status` | Transition: `{status, actor, detail?}`. Validated against the state machine. Emits `issue.status_changed`. |
| `POST /issues/{id}/close` | `{closed_by: reporter\|auto\|admin, resolution_type?, resolution_notes?}` from `verified`. Emits `issue.closed`. |
| `POST /issues/{id}/cancel` | `{reason}` while `reported`. |
| `GET /stats/load` | `{open_count, open_by_severity}` — feeds the ETA estimator's load factor. |
| `GET /stats/dashboard` | Role-scoped KPI aggregates behind the dashboard tiles, over the caller's whole scoped population: `{scope, sla_breach_days, total_count, open_count, open_by_severity, open_by_status, open_by_category, sla: {breached, within, breach_rate}, age_buckets, duplicates, month}`. `?month=YYYY-MM` (default: current) selects the window for `month`, which carries `{key, closed, cancelled, verified, repaired, avg_mttr_days, avg_mttc_days, median_repair_days, prev_key, prev_avg_mttr_days, mttr_delta_days}`. Durations are `null`, never `0`, when the set is empty. **SLA breach** = open longer than `SLA_BREACH_DAYS` (30) and not yet `pending_verification`, `verified`, `closed` or `cancelled` — mirrored client-side in `frontend/src/lib/format.js`. |

## Triage service (:8002)

| Method & path | Purpose |
|---|---|
| `POST /triage/run/{issue_id}` | Run/re-run the triage pipeline for one issue (also invoked by the `issue.created` webhook). Returns the `triage_result`. |
| `GET /triage/results/{issue_id}` | Latest triage result. |
| `POST /triage/results/{issue_id}/confirm` | Admin confirms or overrides `{severity?, urgency?}` → PATCHes reporting. |
| `GET /analytics/systemic` | Clusters of repeated issues (same category+location, min count ≥ threshold) with LLM maintenance recommendations. This is what the `issue.escalated` admin notification points at — there is no separate escalations queue. |
| `GET /analytics/metrics` | `{mtbf: [...], mttr: [...]}` grouped by `group_by=category\|building\|floor\|equipment`. `mtbf` counts one failure per duplicate group (the oldest member): a duplicate is the same defect reported again, not the asset failing again, and counting confirmations collapses MTBF towards the reporting interval. |
| `GET /analytics/profiles` | Location profile & issue profile summaries (counts, trends). |
| `GET /analytics/vendor-performance` | Per-assignee speed & quality: avg repair hours, proof rejection rate, resolved-on-arrival counts. Reads the `fixverify` schema directly (the sanctioned read-only cross-schema access in the shared PostgreSQL DB). |
| `GET /analytics/insights` | Ranked recommendation cards assembled from the four aggregates above — the admin-facing read of them, and what closes doc 05's "nobody escalates a cluster" gap. Each card: `{id, kind, source, active, title, body, action, window_days, evidence[3], filter, linked_count, linked[]}`. `kind` is `systemic` (a live cluster, `action` is its stored LLM recommendation), `predictive` (a location's 30-day volume up ≥50%) or `pre-emptive` (asset MTBF under 60 days, a repeat rate over half, or an assignee whose proofs are mostly rejected). `active: false` marks a cluster that has stopped accruing members. `filter` is how to find the card's issues in the defect list (`{search, category}`) — stated here because this is the side that knows the group. No confidence score and no cost figure: nothing in the system produces either. |
| `POST /analytics/sync` | Refresh `issue_facts` snapshot from reporting. |
| `POST /webhooks/events` | Gateway fan-out receiver (`issue.created`, `issue.closed`). |

## Fix & Verify service (:8003)

| Method & path | Purpose |
|---|---|
| `GET /work-orders` | List; filters `status`, `assignee`, `issue_id`. |
| `GET /work-orders/{id}` | Work order + its **submitted** proofs; staged ones are not part of the record yet. |
| `POST /work-orders/{id}/start` | `{assignee}` → status `in_progress`; PATCHes issue → `in_progress`; emits `work_order.started`. |
| `GET /work-orders/{id}/evidence-recommendation` | LLM recommendation: `{recommended: [{media_type, what, why}], requires_human_verification, rationale}`. Cached on the work order. |
| `POST /work-orders/{id}/proofs` | **Phase 1 of two.** Multipart: `file`, `note?`. Stores the file and runs the vision relevance check against the issue description, then stops. Returns the `Proof` with `staged: true` and its `{ai_verdict, ai_reason, ai_confidence}`. The work order and issue do **not** move and no event fires. The verdict is advisory — even a confident `irrelevant` does not block, it is returned for the uploader to weigh. |
| `POST /proofs/{id}/submit` | **Phase 2.** Multipart `note?` (overwrites the staged note, which may have been edited after the check). The uploader stands behind the proof: `staged → false`, work order → `pending_human_verification`, issue → `pending_verification`, emits `proof.uploaded`. 409 if already submitted. Submitting against an **`open`** work order means the defect was already resolved on arrival (or self-serviced) — the work order is marked `resolved_on_arrival` and the issue jumps `triaged → pending_verification`, skipping `in_progress`. |
| `DELETE /proofs/{id}` | Discard a **staged** proof the uploader chose not to put forward: row and file are both deleted. 409 on a submitted proof — a submitted proof is part of the record, and rejecting it is what human verification is for. |
| `GET /proofs/{id}/file` | Serve the uploaded file. |
| `POST /proofs/{id}/human-verify` | Admin: `{approved: bool, notes?}`. 409 on a staged proof — nobody has put it forward yet. Approved → issue `verified`, emits `issue.verified`; rejected → work order back to `awaiting_proof`, issue `in_progress`. |
| `POST /webhooks/events` | Receiver (`issue.triaged` → auto-create work order). Skipped when the issue is a duplicate whose group primary already has a live work order — one defect, one dispatch (doc 05). |

## Notification service (:8004)

| Method & path | Purpose |
|---|---|
| `GET /notifications` | Inbox for the caller: matches `target_role == X-Role` or `target_user == X-User`. Filter `unread_only=true`. |
| `GET /notifications/unread-count` | Badge count. |
| `POST /notifications/{id}/read` | Mark read. |
| `POST /notifications/read-all` | Mark all read for caller. |
| `POST /webhooks/events` | Receiver for **all** events → creates targeted notifications (see mapping in `services/notification/app/rules.py`). |

## Gateway (:8000)

| Method & path | Purpose |
|---|---|
| `/api/{service}/{path}` | Reverse proxy (all methods). |
| `POST /events` | Event bus intake: `{event_id, event_type, payload, source, created_at}`. Fans out to subscribers per `subscriptions.py`. Returns per-subscriber delivery results. |
| `GET /health` | Aggregated health of all services. |

## Event envelope

```json
{
  "event_id": "uuid4",
  "event_type": "issue.created",
  "source": "reporting",
  "created_at": "2026-08-31T08:00:00Z",
  "payload": { "issue_id": "…", "...": "event-specific fields" }
}
```

Consumers must be idempotent on `event_id` (PoC consumers keep it simple:
operations are naturally idempotent upserts keyed by issue/work-order id).
