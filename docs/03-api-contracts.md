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
| `GET /issues` | List. Filters: `status`, `category`, `building`, `floor`, `reporter`, `q` (text), `limit`, `offset`. |
| `GET /issues/{id}` | Full issue + timeline (`issue_events`). |
| `PATCH /issues/{id}` | Reporter edits (title/description/location) while `status=reported`. |
| `POST /issues/{id}/accept-suggested-category` | Reporter accepts the AI category (`category_source=ai_accepted`). |
| `POST /issues/{id}/triage-result` | **Internal (triage svc)**: `{severity, urgency, equipment_name?, duplicate_group_id?, duplicate_count?, is_critical_system?}` → status `triaged`, recomputes ETA, emits `issue.triaged` timeline entry. |
| `POST /issues/{id}/status` | Transition: `{status, actor, detail?}`. Validated against the state machine. Emits `issue.status_changed`. |
| `POST /issues/{id}/close` | `{closed_by: reporter\|auto\|admin, resolution_type?, resolution_notes?}` from `verified`. Emits `issue.closed`. |
| `POST /issues/{id}/cancel` | `{reason}` while `reported`. |
| `GET /stats/load` | `{open_count, open_by_severity, avg_backlog_days}` — feeds ETA + dashboard. |

## Triage service (:8002)

| Method & path | Purpose |
|---|---|
| `POST /triage/run/{issue_id}` | Run/re-run the triage pipeline for one issue (also invoked by the `issue.created` webhook). Returns the `triage_result`. |
| `GET /triage/results/{issue_id}` | Latest triage result. |
| `POST /triage/results/{issue_id}/confirm` | Admin confirms or overrides `{severity?, urgency?}` → PATCHes reporting. |
| `GET /analytics/systemic` | Clusters of repeated issues (same category+location, min count ≥ threshold) with LLM maintenance recommendations. |
| `GET /analytics/metrics` | `{mtbf: [...], mttr: [...]}` grouped by `group_by=category\|building\|floor\|equipment`. |
| `GET /analytics/profiles` | Location profile & issue profile summaries (counts, trends). |
| `GET /analytics/vendor-performance` | Per-assignee speed & quality: avg repair hours, proof rejection rate, resolved-on-arrival counts. Reads `fixverify_*` tables directly (the sanctioned read-only cross-schema access in the unified DB). |
| `POST /analytics/sync` | Refresh `issue_facts` snapshot from reporting. |
| `POST /webhooks/events` | Gateway fan-out receiver (`issue.created`, `issue.closed`). |

## Fix & Verify service (:8003)

| Method & path | Purpose |
|---|---|
| `GET /work-orders` | List; filters `status`, `assignee`, `issue_id`. |
| `GET /work-orders/{id}` | Work order + proofs. |
| `POST /work-orders/{id}/start` | `{assignee}` → status `in_progress`; PATCHes issue → `in_progress`; emits `work_order.started`. |
| `GET /work-orders/{id}/evidence-recommendation` | LLM recommendation: `{recommended: [{media_type, what, why}], requires_human_verification, rationale}`. Cached on the work order. |
| `POST /work-orders/{id}/proofs` | Multipart: `file`, `note?`. Runs vision relevance check against issue description. `relevant` → issue `pending_verification`, emits `proof.uploaded`; `irrelevant` → HTTP 422 with `{ai_verdict, ai_reason}`, emits `proof.rejected` (uploader must re-upload). `inconclusive`/non-visual → stored, flagged for human review. Also accepted on an **`open`** work order: this means the defect was already resolved on arrival (or self-serviced) — the work order is marked `resolved_on_arrival` and the issue jumps `triaged → pending_verification`, skipping `in_progress`. |
| `GET /proofs/{id}/file` | Serve the uploaded file. |
| `POST /proofs/{id}/human-verify` | Admin: `{approved: bool, notes?}`. Approved → issue `verified`, emits `issue.verified`; rejected → work order back to `awaiting_proof`, issue `in_progress`. |
| `POST /webhooks/events` | Receiver (`issue.triaged` → auto-create work order). |

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
