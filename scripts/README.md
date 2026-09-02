# Historical data import

Imports the ITeFM defect export (`raw_data/*.csv`, 2,182 rows covering
2025-07-01 → 2026-08-27) into the app database.

| File | Role |
|---|---|
| `defect_mapping.py` | Pure CSV → app-model mapping. No DB. Run with a CSV for a mapping-only dry run, with no argument for its self-check. |
| `import_defects.py` | Reads the CSV, applies the mapping, writes the database. |
| `check_card_links.py` | End-to-end check that each insight card's "See N defects" link returns exactly those N. Needs the stack up. |

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

## Recovering a floor

248 rows have no floor segment in their location path and import on the
`Unspecified` sentinel, which the insight rules refuse to treat as a location
(`services/triage/app/insights.py`, `placed`). 158 of them name their level in
the free text instead — "Annex Level 3 pole B17", "L24 FW", "DTTCC #01-01B" —
and `defect_mapping.recover_floor` reads it back, in that building's own
spelling (`07` for DTTA, `3` for BLK B, `L07` for MSCP).

```bash
python scripts/defect_mapping.py                 # self-check, no CSV, no DB
python scripts/import_defects.py --refloor       # move already-imported rows
```

`--refloor` updates the floor on rows still sitting on the sentinel, in both
`reporting.issues` and `triage.issue_facts`, and touches nothing else. Use it
in preference to a `--reset` re-import when the database is already populated:
a re-import takes new issue ids with it, orphaning every `triage.results` row,
systemic-cluster recommendation and pattern scan built on the old ones. It is
matched on `reference_no` and idempotent — a second run reports 0.

Ambiguity stays unplaced by design, so 90 rows keep the sentinel: text naming
two levels names neither, and a level the building has never had is a misread.

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
are no duplicate groups to carry over), and `resolution_type` (90% blank at
source, and 227 of the 231 filled values are "Others"). `is_critical_system`
is `False` everywhere — only 9 source rows carry it, and nothing in the app
reads the field today.

**Not imported** — `triage.systemic_clusters` and `fixverify.*`. Systemic
clustering is a separate LLM pass (`pipeline.py:_systemic_check`) whose window
is the last `SYSTEMIC_WINDOW_DAYS` from *now*, so it would only ever see the
most recent 90 days. `vendor_performance()` needs `fixverify.work_orders`, which
this export has no equivalent for; it already returns `[]` when that table is
empty.

# Triage backfill

`backfill_triage.py` runs the pipeline over the imported facts — the step the
import deliberately skips. Without it `triage.results` is empty, so there are no
severity suggestions, no duplicate links, no systemic clusters, and the AI
Insights systemic panel shows nothing.

Each issue is replayed **as of its own `created_at`**: `pipeline.triage_fact`
takes an `as_of` that ends the 14-day duplicate window and the 90-day systemic
window at the issue instead of at wall-clock now. That is what the "Not
imported" note above is about — anchored, the clustering sees all 14 months
rather than the most recent 90 days.

Run it **from the host, not inside the triage container**. `docker compose exec`
runs as a child of the container: a `docker compose up` on any other terminal
recreates that container mid-run and takes the process, the copied script and
the log with it. That is not hypothetical — it killed a run at 42%.

```bash
pip install "sqlmodel>=0.0.22" "psycopg[binary]>=3.2" python-dotenv httpx openai

set -a; . ./.env; set +a
export DATABASE_URL=postgresql+psycopg://app:app@localhost:5432/defects
export PYTHONPATH=services/triage

python scripts/backfill_triage.py --dry-run          # counts, no model calls
python scripts/backfill_triage.py --limit 20         # smoke test
nohup python scripts/backfill_triage.py --every 100 > backfill.log 2>&1 &
```

Roughly 4,800 model calls, ~$0.20 on `google/gemini-2.5-flash-lite`, 1-2 hours
at 3-5s per issue. Sequential by design: clusters must accrue members in arrival
order, and the duplicate group of the second report needs the first already
stored. Re-running resumes — issues that already have a result row are skipped.
Reporting is not written to unless `--write-back` is passed; these are closed
issues whose severity is already history there.

**One run at a time.** A second start refuses on a Postgres advisory lock, and
it has to: `triage.results` has no unique constraint on `issue_id`, so two
runners each snapshot the pending list and both store their answers. That
produced 235 duplicate rows before the lock existed, visible only as a row count
above the issue count:

```sql
select count(*), count(distinct issue_id) from triage.results;  -- must be equal
```

**A dropped connection is not a failure.** `ai_client` degrades to a rule-based
fallback rather than raising (docs/04), so a lost model call still returns
`medium / routine / "Default (AI unavailable)"` and the pipeline stores it — a
row that looks triaged, so the next resume skips it forever. The runner raises
`max_retries` for its own process and deletes any fallback row it wrote, leaving
the issue pending instead. To confirm a finished run kept nothing degraded:

```sql
select count(*) from triage.results
 where severity_rationale like 'Default (AI unavailable)%';  -- must be 0
```

## Porting the results to another machine

The backfill is the only expensive thing in this repo — everything else can be
re-run for free. Move it rather than paying for it twice.

**Whole database (simplest, and what to use when the target is a fresh clone):**

```bash
# source machine
docker compose exec -T postgres pg_dump -U app -Fc defects > defects.dump

# target machine, after `docker compose up -d --build` has created the schema
docker compose exec -T postgres pg_restore -U app -d defects --clean --if-exists \
  < defects.dump
```

No import step needed on the target — the dump carries `reporting.*` and
`triage.*` together, so the target does not need `raw_data/` or the CSV.

**Triage outputs only (when the target already has its own imported data):**

```bash
# source machine — the four tables holding LLM output
docker compose exec -T postgres pg_dump -U app -d defects --data-only \
  -t triage.results -t triage.systemic_clusters \
  -t triage.insight_actions -t triage.pattern_scans > triage_ai.sql

# target machine
docker compose exec -T postgres psql -U app -d defects -c \
  'TRUNCATE triage.results, triage.systemic_clusters,
            triage.insight_actions, triage.pattern_scans'
docker compose exec -T postgres psql -U app -d defects < triage_ai.sql
# the facts carry a copy of the duplicate link, and it is not in those tables
docker compose exec -T postgres psql -U app -d defects -c \
  'UPDATE triage.issue_facts f SET duplicate_group_id = r.duplicate_of_issue_id
     FROM triage.results r WHERE r.issue_id = f.issue_id'
```

That last UPDATE is not optional: `profiles()` counts `duplicate_rate` off
`issue_facts.duplicate_group_id`, which `triage_fact` mirrors as it goes. Skip
it and the duplicate insight cards go quiet on the target.

Both routes assume the same issue ids on both machines. Re-running
`import_defects.py --reset` on the target mints new ids and orphans every row
you just copied — restore the dump instead of re-importing.
