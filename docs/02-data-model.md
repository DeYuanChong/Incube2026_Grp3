# 02 — Data Model

Each service owns its own SQLite database. No service reads another's DB file.

## Mapping from the reference schema (`example_db_schema.jpeg`)

The reference is a facilities job-request export. We adapted it as follows:

| Reference field | Our field / decision |
|---|---|
| Issue, Failure Type, Fault Classification | `description`, `category`, `ai_suggested_category` |
| Impact, Emergency, Is Critical System? | `severity`, `urgency`, `is_critical_system` (triage outputs) |
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

## Reporting service — `reporting.db`

### `issues`
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
| `duplicate_group_id` | TEXT, nullable | Shared by duplicates of one underlying defect |
| `duplicate_count` | INTEGER | # of reports in the group (drives escalation) |
| `estimated_resolution_days` | REAL, nullable | Expectation shown to reporter |
| `estimate_basis` | TEXT, nullable | Human-readable explanation of the estimate |
| `resolution_type` | TEXT, nullable | `repaired` `replaced` `no_action` `self_resolved` `duplicate` |
| `resolution_notes` | TEXT, nullable | |
| `cancellation_reason` | TEXT, nullable | |
| `closed_by` | TEXT, nullable | `reporter` \| `auto` \| `admin` |
| `created_at` / `triaged_at` / `work_started_at` / `fixed_at` / `verified_at` / `closed_at` / `updated_at` | TEXT ISO-8601 | Lifecycle timestamps (feed MTTR/MTBF) |

### `issue_events` (timeline shown on the dashboard)
`id`, `issue_id` FK, `event_type`, `detail` (JSON), `actor`, `created_at`

## Triage service — `triage.db`

### `triage_results`
`id`, `issue_id`, `suggested_severity`, `suggested_urgency`,
`severity_rationale` (LLM explanation), `equipment_extracted`,
`duplicate_of_issue_id`, `duplicate_confidence`, `systemic_flag` (bool),
`systemic_cluster_id`, `admin_confirmed` (bool), `admin_override_severity`,
`created_at`

### `issue_facts` (local analytics snapshot, refreshed from reporting)
Denormalized copy of the issue fields needed for analytics:
`issue_id`, `category`, `building`, `floor`, `room`, `equipment_name`,
`severity`, `status`, `created_at`, `fixed_at`, `closed_at`, `synced_at`

### `systemic_clusters`
`id`, `cluster_key` (e.g. `lighting|BlockA|L3`), `issue_count`, `first_seen`,
`last_seen`, `recommendation` (LLM: preventive/prescriptive maintenance advice)

## Fix & Verify service — `fixverify.db`

### `work_orders`
`id`, `issue_id`, `status` (`open` `in_progress` `awaiting_proof`
`pending_human_verification` `verified` `rejected`), `assignee`,
`is_temporary_fix` (bool), `resolved_on_arrival` (bool — defect was already
resolved when maintenance arrived, e.g. a spill someone else cleaned up or a
reporter self-service; the issue skips `in_progress` entirely),
`evidence_recommendation` (JSON: recommended proof
types + rationale), `requires_human_verification` (bool — true when the defect
is not visually verifiable, e.g. smells/noise), `started_at`, `completed_at`

### `proofs`
`id`, `work_order_id`, `file_path`, `media_type` (`image` `audio` `other`),
`uploaded_by`, `note`, `ai_verdict` (`relevant` `irrelevant` `inconclusive`),
`ai_reason` (shown to uploader on rejection), `ai_confidence`,
`human_verdict` (`approved` `rejected`, nullable), `human_verifier`,
`human_notes`, `created_at`

## Notification service — `notification.db`

### `notifications`
`id`, `target_role` (`reporter` `maintenance` `admin`), `target_user`
(nullable — narrows to a person), `issue_id`, `event_type`, `title`, `body`,
`is_read` (bool), `created_at`

## ID & time conventions
- All PKs are UUID4 strings; all timestamps are UTC ISO-8601 strings.
- Derived date parts (month/quarter/year in the reference schema) are computed
  in queries/analytics, never stored.
