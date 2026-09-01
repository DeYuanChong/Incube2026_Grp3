# 02 — Data Model

All services share **one PostgreSQL database** (`defects`), with a **real
schema per service**: `reporting`, `triage`, `fixverify`, `notification`.
Each service creates its own schema at startup (`CREATE SCHEMA IF NOT EXISTS`).

Ownership rules:
- Each service **writes only** tables in its own schema (it remains the single
  writer and migration owner for them).
- Tables are created by `SQLModel.metadata.create_all`, which creates what is
  **missing** and never alters what exists. The DB lives on a persistent volume,
  so a column added to a model after the first deploy silently does not exist on
  a running stack. Added columns therefore ship as idempotent DDL in the
  service's `init_db()`, **after** `create_all` — see
  `triage/app/db.py` (`ALTER TABLE … ADD COLUMN IF NOT EXISTS`).
- **Triage may read the `fixverify` schema** (read-only, raw SQL) — triage
  folds repair durations, proof rejections, and resolved-on-arrival counts into
  its analytics (`/analytics/vendor-performance`).
- All other cross-service access stays REST/events.
- For the PoC all services share one DB role (`app`); in production each
  service would get its own credentials, with a `GRANT SELECT ON ALL TABLES IN
  SCHEMA fixverify TO triage_role` making the read boundary enforceable.

Fuzzy text search uses the **`pg_trgm`** extension (enabled at startup):
- `GET /issues?q=` matches on trigram `word_similarity` (typo-tolerant) OR
  `ILIKE` substring, ranked by similarity, backed by a GIN index on
  `reporting.issues(title || ' ' || description)`.
- Triage's duplicate detection ranks candidate issues by description
  `similarity()` and only sends the top 5 to the LLM for confirmation.

Timestamps remain UTC ISO-8601 **strings** (portable from the SQLite era; they
sort correctly and cast cleanly via `::timestamptz` where SQL needs date math).
Converting columns to native `timestamptz` is a straightforward later cleanup.

## Mapping from the reference schema (`example_db_schema.jpeg`)

The reference is a facilities job-request export. We adapted it as follows:

| Reference field | Our field / decision |
|---|---|
| Issue, Failure Type, Fault Classification | `description`, `category`, `ai_suggested_category` |
| Impact, Emergency, Is Critical System? | `severity`, `urgency` (triage outputs); `is_critical_system` is admin-set on the issue, not a triage output — triage states it inside `severity_rationale` instead (doc 05) |
| Exact Location, Unit | `building`, `floor`, `room` (room optional), `equipment_name` |
| Requestor Name | `reporter_name` (demo-mode header) |
| Created/Reported Date Time (+ Month/Quarter/Year variants) | `created_at` only — month/quarter/year are derived at query time, not stored |
| Arrive On Site Date/Time | `work_started_at` (work order) |
| Recovery Date Time | `fixed_at` (proof accepted) |
| Closed Date Time | `closed_at` |
| Modified Date Time | `updated_at` |
| Problem Resolution, Resolution Type | `resolution_notes`, `resolution_type` |
| Related Job / Related Job Request NO. | `duplicate_of_issue_id` / `duplicate_group_id` |
| User Closed Defect, User Submitted for Closure | `closed_by` (`reporter` \| `auto` \| `admin`), `verified` status |
| Cancellation Remarks | `cancellation_reason` |
| Temporary Recovery Declaration | `is_temporary_fix` (work order) |
| No Follow-up Action / Reason | folded into `resolution_type = no_action` + `resolution_notes` |
| Charge to PWO?, Costing Required?, Negligence/Non-Negligence remarks, Minor Building Repair Works, Control Register, Building Security System Declaration | **Out of scope for PoC** — administrative/financial fields; add later if needed |

## Reporting service — schema `reporting`

### `reporting.issues`
| Column | Type | Notes |
|---|---|---|
| `id` | TEXT (UUID) PK | |
| `reference_no` | TEXT unique | Human-friendly, e.g. `DEF-2026-0042` |
| `category` | TEXT enum | `air_conditioning` `lighting` `cleanliness` `toilet` `physical_security` `others` — the reporter's (or accepted) category |
| `ai_suggested_category` | TEXT enum, nullable | vLLM suggestion; shown when it differs from `category` |
| `ai_category_confidence` | REAL, nullable | 0–1 |
| `category_source` | TEXT | `user` \| `ai_accepted` |
| `title` | TEXT | Short summary |
| `description` | TEXT | Required, free text |
| `building` | TEXT | Required |
| `floor` | TEXT | Required |
| `room` | TEXT, nullable | Optional per requirements |
| `equipment_name` | TEXT, nullable | Extracted by triage or entered by user |
| `reporter_name` | TEXT | From `X-User` |
| `status` | TEXT enum | `reported` `triaged` `in_progress` `pending_verification` `verified` `closed` `cancelled` |
| `severity` | TEXT enum, nullable | `low` `medium` `high` `critical` (set at triage) |
| `urgency` | TEXT enum, nullable | `routine` `urgent` `emergency` (set at triage) |
| `is_critical_system` | INTEGER bool | default 0 |
| `duplicate_group_id` | TEXT, nullable | Shared by duplicates of one underlying defect. Also gates dispatch: a duplicate rides the group primary's work order (doc 05). |
| `duplicate_count` | INTEGER | # of reports in the group (drives escalation) |
| `estimated_resolution_days` | REAL, nullable | Expectation shown to reporter |
| `estimate_basis` | TEXT, nullable | Human-readable explanation of the estimate |
| `resolution_type` | TEXT, nullable | `repaired` `replaced` `no_action` `self_resolved` `duplicate` |
| `resolution_notes` | TEXT, nullable | |
| `cancellation_reason` | TEXT, nullable | |
| `closed_by` | TEXT, nullable | `reporter` \| `auto` \| `admin` |
| `created_at` / `triaged_at` / `work_started_at` / `fixed_at` / `verified_at` / `closed_at` / `updated_at` | TEXT ISO-8601 | Lifecycle timestamps (feed MTTR/MTBF) |

### `reporting.issue_events` (timeline shown on the dashboard)
`id`, `issue_id` FK, `event_type`, `detail` (JSON), `actor`, `created_at`

## Triage service — schema `triage`

### `triage.results`
`id`, `issue_id`, `suggested_severity`, `suggested_urgency`,
`severity_rationale` (LLM explanation — including whether a critical system is
involved, which is a reason for the severity rather than a separate column),
`equipment_extracted`, `duplicate_of_issue_id` (the group primary: the **oldest**
confirmed duplicate, so members of a group converge on one primary instead of
chaining — doc 05), `duplicate_confidence`, `systemic_flag` (bool),
`systemic_cluster_id`, `admin_confirmed` (bool), `admin_override_severity`,
`admin_override_urgency`, `created_at`

Append-only: a re-run adds a row rather than replacing the previous one, which is
why anything that needs *counting* (the duplicate rate) reads a column on
`issue_facts` and not these rows. There is no `systemic_payload` column — the
endpoint composes it at serialization time from the `systemic_clusters` row and a
live member query (doc 05).

### `triage.issue_facts` (local analytics snapshot, refreshed from reporting)
Denormalized copy of the issue fields needed for analytics:
`issue_id`, `reference_no`, `category`, `building`, `floor`, `room`,
`equipment_name`, `severity`, `status`, `description`, `duplicate_group_id`,
`created_at`, `fixed_at`, `closed_at`, `synced_at`

- `description` backs both the trigram duplicate pre-filter and the member
  summaries in `systemic_payload`; `reference_no` is there so a member can be
  named without a round trip to reporting.
- `duplicate_group_id` mirrors reporting's column, which stays the writer of
  record. It is what `profiles()` counts for the duplicate rate. The pipeline
  writes onto the fact what it posts back to reporting, because nothing reporting
  publishes on the write-back returns to triage; existing rows fill in on their
  next sync or via `POST /analytics/sync`.
- Refreshed on `issue.created`, `issue.status_changed` and `issue.closed`. A
  status the snapshot never hears about goes on counting as open work, which is
  why cancellation publishes an event too.

### `triage.systemic_clusters`
`id`, `cluster_key` (e.g. `lighting|BlockA|L3`), `issue_count`, `first_seen`,
`last_seen`, `recommendation` (LLM: preventive/prescriptive maintenance advice,
written once under `if not cluster.recommendation` and never refreshed),
`updated_at` (`issue_count` / `last_seen` are as-of this timestamp)

`cluster_key` is unique and built by one formula, `triage/app/grouping.py::
cluster_key`. It is **never parsed back apart** — a building or floor containing
`|` would split into the wrong three parts — so anything needing the components
reads them off the fact columns.

`issue_count` is a stored high-water mark, refreshed only when a new member
arrives, so a remediated cluster keeps its peak forever.
`GET /analytics/systemic` therefore recounts the window per request and returns
`issue_count_live` and `active` alongside it; neither is a column (doc 05).

## Fix & Verify service — schema `fixverify`

### `fixverify.work_orders`
`id`, `issue_id`, `status` (`open` `in_progress` `awaiting_proof`
`pending_human_verification` `verified` `rejected`), `assignee`,
`is_temporary_fix` (bool), `resolved_on_arrival` (bool — defect was already
resolved when maintenance arrived, e.g. a spill someone else cleaned up or a
reporter self-service; the issue skips `in_progress` entirely),
`evidence_recommendation` (JSON: recommended proof
types + rationale), `requires_human_verification` (bool — true when the defect
is not visually verifiable, e.g. smells/noise), `started_at`, `completed_at`

### `fixverify.proofs`
`id`, `work_order_id`, `file_path`, `media_type` (`image` `audio` `other`),
`uploaded_by`, `note`, `ai_verdict` (`relevant` `irrelevant` `inconclusive`),
`ai_reason` (shown to uploader on rejection), `ai_confidence`,
`human_verdict` (`approved` `rejected`, nullable), `human_verifier`,
`human_notes`, `created_at`

## Notification service — schema `notification`

### `notification.inbox`
`id`, `target_role` (`reporter` `maintenance` `admin`), `target_user`
(nullable — narrows to a person), `issue_id`, `event_type`, `title`, `body`,
`is_read` (bool), `created_at`

## ID & time conventions
- All PKs are UUID4 strings; all timestamps are UTC ISO-8601 strings.
- Derived date parts (month/quarter/year in the reference schema) are computed
  in queries/analytics, never stored.
