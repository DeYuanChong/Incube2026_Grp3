# Ingestion notes — ITeFM historical import

Notes from running `import_defects.py` on the masked ITeFM export
(`ITeFM Defect Report for period 1Jul25 to 27Aug26_masked.csv`, 2,182 rows).
Kept here so the next person doesn't rediscover the same snags.

## Result

All 2,182 rows imported cleanly, writing three tables in sync:

| Table                    | Rows  |
| ------------------------ | ----- |
| `reporting.issues`       | 2,182 |
| `reporting.issue_events` | 2,182 |
| `triage.issue_facts`     | 2,182 |

Status breakdown: 1,988 closed · 78 reported · 68 in_progress · 44 cancelled · 4 verified.

## Issues encountered

### 1. `mobile_number` NOT NULL violation (data/mapping fix)

**Symptom** — the first insert batch aborted with:

```
sqlalchemy.exc.IntegrityError: (psycopg.errors.NotNullViolation)
null value in column "mobile_number" of relation "issues" violates not-null constraint
```

**Cause** — `reporting.issues.mobile_number` is declared `mobile_number: str`
in `services/reporting/app/models.py` (NOT NULL, no default), but the masked
export carries no contact numbers, so `defect_mapping.map_row()` never set the
field and it defaulted to `None`.

**Fix** — `scripts/defect_mapping.py` now maps `mobile_number` to an empty
string for imported rows (the neutral "absent" value that satisfies the
constraint, consistent with how the mapping treats other unavailable source
columns). The failed run committed nothing — inserts are batched in one
transaction per batch — so the re-run did not need `--reset`.

## Prerequisites / gotchas worth knowing

- **The services must have started at least once** before importing — they own
  schema creation (`init_db()` creates the `reporting`/`triage` schemas, tables,
  and the `duplicate_group_id` column the script checks for). The script guards
  this with a `check_tables()` preflight and a clear "start the services" hint.
- **Run location vs. database URL.** From the host, use the default
  `postgresql+psycopg://app:app@localhost:5432/defects` (Postgres is exposed on
  `5432`). Inside the compose network the host would be `postgres`, not
  `localhost`. Credentials/DB name come from `docker-compose.yml`
  (`app` / `app` / `defects`).
- **The default CSV lookup scans `raw_data/`, not `scripts/`.** This file lived
  in `scripts/`, so it was passed explicitly with `--csv "<path>"`.
- **Idempotency.** The import skips rows whose `reference_no` already exists;
  use `--reset` to delete and re-import the rows this export owns. Validate
  first with `--dry-run` (maps every row and prints the first mapped record
  without writing).
