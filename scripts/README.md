# Historical data import

Imports the ITeFM defect export (`raw_data/*.csv`, 2,182 rows covering
2025-07-01 → 2026-08-27) into the app database.

| File | Role |
|---|---|
| `defect_mapping.py` | Pure CSV → app-model mapping. No DB. Run directly for a mapping-only dry run. |
| `import_defects.py` | Reads the CSV, applies the mapping, writes the database. |

## Running it

The services own schema creation, so start them once first:

```bash
docker compose up -d --build
pip install "sqlmodel>=0.0.22" "psycopg[binary]>=3.2" python-dotenv

python scripts/import_defects.py --dry-run   # map + report, write nothing
python scripts/import_defects.py             # import
python scripts/import_defects.py --reset     # delete previous import, re-import
```

Re-running without `--reset` is safe: rows already present (matched on
`reference_no`) are skipped.

The importer refuses to start against a database that is missing a table, or a
column added after that database was created. `SQLModel.metadata.create_all`
never ALTERs an existing table, so new columns ship as idempotent DDL in the
owning service's `init_db()` (docs/02) — meaning a long-running stack needs a
service restart before the import, not just a `git pull`.

The import writes the database directly instead of replaying `POST /issues`,
which would fire an AI categorization call per issue and overwrite the source
reference numbers and timestamps.

## What gets written

| Table | Rows | Why |
|---|---|---|
| `reporting.issues` | 2,182 | The issues. |
| `reporting.issue_events` | 2,182 | One `imported` event per issue, whose JSON `detail` keeps the source row's Problem Type, Impact, Issue, Emergency and related fields. |
| `triage.issue_facts` | 2,182 | The analytics snapshot. MTBF/MTTR read **this** table, not `reporting.issues` — skipping it leaves every analytics view empty. |

`POST /analytics/sync` is not a substitute: it calls `GET /issues` with
`limit: 500`, which is also the endpoint's maximum, so a "full refresh" covers
at most 500 of the 2,182 rows.

## Mapping decisions

**Status** — the source has 5 states, the app 7:

| Source | App | Rows |
|---|---|---|
| Closed | `closed` | 1,988 |
| Pending Review | `reported` | 78 |
| Pending Rectification | `in_progress` | 68 |
| Cancelled | `cancelled` | 44 |
| Pending Closure | `verified` | 4 |

*Pending Review* maps to `reported`, not `pending_verification`: all 78 of those
rows have no arrival, recovery or closure timestamp, so they are unattended new
reports rather than repairs awaiting proof. Change `PENDING_REVIEW_STATUS` in
`defect_mapping.py` to flip this.

**Category** — all 17 source Problem Types collapse to `others`, because the
app's six-value enum has no home for ~42% of the corpus. The original value
survives on the imported event, so this can be revisited without the CSV.
Until it is, `analytics?group_by=category` returns a single group, and
`profiles()`'s `repeat_rate` reads 0.83–0.96 everywhere: it counts issues that
are not the first of their category in the group, and with one category almost
every issue qualifies. `duplicate_rate` is a true 0.0 (see below), and
`trend_pct`, `median_repair_days` and `verification_overhead_days` are all
unaffected.

**Location** — the source packs location into one path string
(`All Location > DSTA > Depot Road > <building> > <floor> > <room>`) with ragged
depth. `building` and `floor` are non-nullable, so absent segments become the
sentinels `Unknown` (14 rows) and `Unspecified` (248 rows); these show up as
real groups in analytics.

**Title** — the source has no title field. Titles are the first line of
`Problem Description` (907 of 2,182 are multi-line, and line one is almost
always the summary), truncated to 120 chars, falling back to Problem Type.

**Timestamps** — the export has no timezone; it is read as SGT (UTC+8) and
stored as UTC ISO-8601 to match the app. Ordering is consistent across all
2,182 rows: arrival never precedes report, recovery never precedes report,
closure never precedes recovery.

**Not populated** — `severity`, `urgency`, `triaged_at` (triage never ran on
this data), `duplicate_group_id` on both the issue and its fact (the source's
Related Job Request NO. is strictly 1:1 — 426 filled, 426 distinct — so there
are no duplicate groups to carry over), `estimated_resolution_days`,
and `resolution_type` (90% blank at source, and 227 of the 231 filled values are
"Others"). `is_critical_system` is `False` everywhere — only 9 source rows carry
it, and nothing in the app reads the field today.

**Not imported** — `triage.systemic_clusters` and `fixverify.*`. Systemic
clustering is a separate LLM pass (`pipeline.py:_systemic_check`) whose window
is the last `SYSTEMIC_WINDOW_DAYS` from *now*, so it would only ever see the
most recent 90 days. `vendor_performance()` needs `fixverify.work_orders`, which
this export has no equivalent for; it already returns `[]` when that table is
empty.
