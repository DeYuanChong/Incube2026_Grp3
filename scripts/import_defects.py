"""Import the historical ITeFM defect export into the app database.

Writes three tables in one transaction per batch:

  reporting.issues        the issues themselves
  reporting.issue_events  one "imported" event per issue, carrying the source
                          row's provenance (Problem Type, Impact, ...) so the
                          category decision can be revisited without the CSV
  triage.issue_facts      the analytics snapshot — MTBF/MTTR read this table,
                          not reporting.issues, so skipping it leaves every
                          analytics view empty

The import writes to the database directly rather than replaying POST /issues:
that endpoint fires an AI categorization call per issue (2,182 of them) and
stamps its own reference numbers and timestamps.

Usage:
    python scripts/import_defects.py --dry-run
    python scripts/import_defects.py
    python scripts/import_defects.py --reset      # re-import from scratch

Requires the services to have started at least once (they own schema creation).
Install deps if running outside a service venv:
    pip install "sqlmodel>=0.0.22" "psycopg[binary]>=3.2" python-dotenv
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session, create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parent))
import defect_mapping as mapping  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_URL = "postgresql+psycopg://app:app@localhost:5432/defects"


def _load_models(module_name: str, relative_path: str):
    """Load a service's models.py under a unique name.

    Both services package their code as `app`, so a plain import of the second
    one would resolve to the first from sys.modules.
    """
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        sys.exit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


reporting_models = _load_models("reporting_models", "services/reporting/app/models.py")
triage_models = _load_models("triage_models", "services/triage/app/models.py")

Issue = reporting_models.Issue
IssueEvent = reporting_models.IssueEvent
IssueFact = triage_models.IssueFact

REQUIRED_TABLES = [
    ("reporting", "issues"),
    ("reporting", "issue_events"),
    ("triage", "issue_facts"),
]

# create_all never ALTERs an existing table, so columns added after the first
# deploy ship as idempotent DDL in the owning service's init_db() (docs/02).
# On a stale stack the table exists but the column does not, and the insert
# would fail halfway through with a raw ProgrammingError.
REQUIRED_COLUMNS = [
    ("triage", "issue_facts", "duplicate_group_id"),
]


def find_csv(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            sys.exit(f"no such file: {path}")
        return path
    candidates = sorted((ROOT / "raw_data").glob("*.csv"))
    if not candidates:
        sys.exit("no CSV found in raw_data/ — pass --csv explicitly")
    if len(candidates) > 1:
        names = "\n  ".join(c.name for c in candidates)
        sys.exit(f"several CSVs in raw_data/, pass --csv:\n  {names}")
    return candidates[0]


def check_tables(session: Session) -> None:
    missing = [
        f"{schema}.{table}"
        for schema, table in REQUIRED_TABLES
        if not session.exec(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = :s AND table_name = :t"
            ).bindparams(s=schema, t=table)
        ).first()
    ]
    if missing:
        sys.exit(
            "missing table(s): "
            + ", ".join(missing)
            + "\nStart the services once so they create their schemas:"
            "\n  docker compose up -d --build"
        )

    stale = [
        f"{schema}.{table}.{column}"
        for schema, table, column in REQUIRED_COLUMNS
        if not session.exec(
            text(
                "SELECT 1 FROM information_schema.columns WHERE table_schema = :s "
                "AND table_name = :t AND column_name = :c"
            ).bindparams(s=schema, t=table, c=column)
        ).first()
    ]
    if stale:
        sys.exit(
            "missing column(s): "
            + ", ".join(stale)
            + "\nThe database predates a model change. Restart the services so"
            " init_db() applies the ALTER:"
            "\n  docker compose up -d --build"
        )


def build_fact(fields: dict, issue_id: str) -> IssueFact:
    """Mirror triage's sync_issue_fact (services/triage/app/pipeline.py:24)."""
    return IssueFact(
        issue_id=issue_id,
        reference_no=fields["reference_no"],
        category=fields["category"],
        building=fields["building"],
        floor=fields["floor"],
        room=fields["room"],
        equipment_name=fields["equipment_name"],
        severity=fields["severity"],
        status=fields["status"],
        description=fields["description"],
        duplicate_group_id=fields["duplicate_group_id"],
        created_at=fields["created_at"],
        fixed_at=fields["fixed_at"],
        closed_at=fields["closed_at"],
    )


def reset(session: Session, reference_nos: list[str]) -> int:
    """Delete only the rows this import owns, in foreign-key order."""
    ids = session.exec(
        select(Issue.id).where(Issue.reference_no.in_(reference_nos))
    ).all()
    if not ids:
        return 0
    for statement in (
        text("DELETE FROM triage.issue_facts WHERE issue_id = ANY(:ids)"),
        text("DELETE FROM reporting.issue_events WHERE issue_id = ANY(:ids)"),
        text("DELETE FROM reporting.issues WHERE id = ANY(:ids)"),
    ):
        session.exec(statement.bindparams(ids=list(ids)))
    session.commit()
    return len(ids)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", help="path to the export (default: the CSV in raw_data/)")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="SQLAlchemy URL (default: $DATABASE_URL, else the compose postgres)",
    )
    parser.add_argument("--dry-run", action="store_true", help="map and report, write nothing")
    parser.add_argument("--limit", type=int, help="import only the first N rows")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete previously imported rows (matched by reference_no) first",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    csv_path = find_csv(args.csv)
    print(f"reading {csv_path}")
    mapped, errors = mapping.map_file(str(csv_path))
    if args.limit:
        mapped = mapped[: args.limit]

    print(f"mapped {len(mapped)} rows ({len(errors)} unmappable)")
    for line_no, message in errors:
        print(f"  ! line {line_no}: {message}")

    if args.dry_run:
        fields, provenance = mapped[0]
        print("\nfirst mapped row:")
        for key, value in fields.items():
            print(f"  {key:26s} {value!r}")
        print(f"  {'(provenance)':26s} {json.dumps(provenance)[:160]}...")
        print("\ndry run — nothing written")
        return

    engine = create_engine(args.database_url, pool_pre_ping=True)
    with Session(engine) as session:
        check_tables(session)

        if args.reset:
            removed = reset(session, [f["reference_no"] for f, _ in mapped])
            print(f"reset: deleted {removed} previously imported issues")

        existing = set(
            session.exec(
                select(Issue.reference_no).where(
                    Issue.reference_no.in_([f["reference_no"] for f, _ in mapped])
                )
            ).all()
        )
        if existing:
            print(f"skipping {len(existing)} rows already present (use --reset to replace)")

        inserted = 0
        pending = 0
        for fields, provenance in mapped:
            if fields["reference_no"] in existing:
                continue
            issue = Issue(**fields)
            session.add(issue)
            session.add(
                IssueEvent(
                    issue_id=issue.id,
                    event_type="imported",
                    actor="import",
                    detail=json.dumps(provenance),
                    created_at=fields["created_at"],
                )
            )
            session.add(build_fact(fields, issue.id))
            inserted += 1
            pending += 1
            if pending >= args.batch_size:
                session.commit()
                pending = 0
                print(f"  committed {inserted}/{len(mapped) - len(existing)}")
        session.commit()

        print(f"\nimported {inserted} issues")
        for label, query in (
            ("reporting.issues", "SELECT COUNT(*) FROM reporting.issues"),
            ("reporting.issue_events", "SELECT COUNT(*) FROM reporting.issue_events"),
            ("triage.issue_facts", "SELECT COUNT(*) FROM triage.issue_facts"),
        ):
            total = session.exec(text(query)).one()[0]
            print(f"  {label:24s} {total}")

        print("\nstatus breakdown:")
        rows = session.exec(
            text(
                "SELECT status, COUNT(*) FROM reporting.issues "
                "GROUP BY status ORDER BY COUNT(*) DESC"
            )
        ).all()
        for status, count in rows:
            print(f"  {count:5d}  {status}")


if __name__ == "__main__":
    main()
