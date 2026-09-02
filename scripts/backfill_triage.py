"""Replay the triage pipeline over the imported historical defects.

`scripts/import_defects.py` writes `triage.issue_facts` directly and never runs
the pipeline, so a fresh import has 2,182 facts and zero `triage.results` — no
severity suggestions, no duplicate links, no systemic clusters, and therefore an
empty systemic panel on the AI Insights page. This fills that in.

Every issue is replayed **as of its own `created_at`**: `pipeline.triage_fact`
takes an `as_of`, so the 14-day duplicate window and the 90-day systemic window
end at the issue rather than at wall-clock now. Run without it and every
historical issue is compared against whatever arrived in the last fortnight,
which for this dataset means 56 rows out of 2,182.

Issues are processed oldest-first and one at a time, on purpose: a cluster has
to accrue members in the order they arrived, and the duplicate group of the
second report depends on the first already being stored. This is not a place to
add concurrency for speed.

Reporting is left alone by default (`--write-back` to opt in). These issues are
closed history; their severity is already recorded there, and the pipeline's
write-back would overwrite it.

Usage (from the repo root — the script runs inside the triage container, which
already has the deps, the model config and the app package):

    docker compose cp scripts/backfill_triage.py triage:/app/backfill_triage.py
    docker compose exec triage python /app/backfill_triage.py --dry-run
    docker compose exec triage python /app/backfill_triage.py --limit 20
    docker compose exec -d triage python /app/backfill_triage.py

Re-running is safe and resumes: an issue that already has a `triage.results` row
is skipped, so a run killed at 90 minutes picks up where it stopped.

Porting the results to another machine — see scripts/README.md.
"""

from __future__ import annotations

import argparse
import sys
import time

from sqlalchemy import text
from sqlmodel import Session, select

from app import ai_client, pipeline
from app.db import engine
from app.models import IssueFact, SystemicCluster, TriageResult

# `ai_client` is built for live serving: max_retries=1, and every call degrades
# to a rule-based fallback rather than raising, so a dropped connection returns
# "medium/routine, AI unavailable" and the pipeline stores it as though it were
# an answer. That is right for one issue in front of a waiting admin and wrong
# for a backfill, where the LLM judgement is the entire product and the row it
# writes is indistinguishable from a real one on the next resume.
#
# ponytail: patched on the client rather than threaded through ai_client, so
# live triage keeps its fail-fast behaviour untouched. Give ai_client a
# per-call retries argument if anything else ever needs this.
ai_client._client = ai_client._client.with_options(max_retries=6)

# What `suggest_severity` writes when it never reached the model.
FALLBACK_RATIONALE = "Default (AI unavailable)"

# Two runners each take a snapshot of what is pending and then work the same
# issues: `triage.results` has no unique constraint on `issue_id`, so the second
# copy is stored rather than rejected, and the duplicates are only visible as a
# row count above the issue count. A session-scoped advisory lock is the cheapest
# thing that makes the second start refuse instead. Any constant will do; this
# one is arbitrary and only has to be stable.
LOCK_KEY = 8_675_309


def _pending(session: Session, limit: int | None) -> list[IssueFact]:
    """Facts with no result yet, oldest first.

    Oldest-first is the replay order; it is also what makes `--limit` useful,
    since a partial run then leaves a correct prefix of history rather than a
    scatter of issues whose clusters never saw their earlier members.
    """
    done = set(session.exec(select(TriageResult.issue_id)).all())
    facts = session.exec(
        select(IssueFact).order_by(IssueFact.created_at)  # type: ignore[arg-type]
    ).all()
    todo = [f for f in facts if f.issue_id not in done]
    return todo[:limit] if limit else todo


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, help="process at most N issues")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would run, make no model calls")
    ap.add_argument("--write-back", action="store_true",
                    help="also POST results to reporting (overwrites live severity)")
    ap.add_argument("--every", type=int, default=25, help="progress line interval")
    args = ap.parse_args()

    with Session(engine) as session:
        # Index the Row, do not truth-test it: a SQLAlchemy 2.0 Row is not a
        # tuple subclass, and Row((False,)) is a non-empty sequence, so testing
        # the row itself reports "lock acquired" every time it was refused.
        held = session.exec(
            text(f"select pg_try_advisory_lock({LOCK_KEY})")  # type: ignore[arg-type]
        ).one()[0]
        if not held:
            print("another backfill is already running (advisory lock held) — "
                  "stop it before starting a second, or the same issues get "
                  "triaged twice and stored twice")
            return 2

        todo = _pending(session, args.limit)
        total = len(todo)
        if args.dry_run:
            done = session.exec(select(TriageResult)).all()
            print(f"{total} issues to triage, {len(done)} already done")
            if todo:
                print(f"from {todo[0].created_at[:10]} to {todo[-1].created_at[:10]}")
            print(f"write-back: {'ON' if args.write_back else 'off'}")
            return 0

        started = time.time()
        failed = degraded = 0
        for n, fact in enumerate(todo, 1):
            try:
                # reference_no stands in for the issue title: the fact table has
                # no title column, and reporting is not queried here.
                result = pipeline.triage_fact(
                    session, fact, fact.reference_no,
                    as_of=fact.created_at, write_back=args.write_back,
                )
                # A stored fallback is worse than no row: it looks triaged, so
                # the next run skips it forever. Drop it and leave the issue
                # pending instead.
                if result.severity_rationale.startswith(FALLBACK_RATIONALE):
                    session.delete(result)
                    session.commit()
                    degraded += 1
                    print(f"  ~ {fact.issue_id[:8]} model unreachable, left pending",
                          flush=True)
            except Exception as exc:  # noqa: BLE001 - one bad issue must not end the run
                failed += 1
                print(f"  ! {fact.issue_id[:8]} {type(exc).__name__}: {exc}", flush=True)
                session.rollback()
            if n % args.every == 0 or n == total:
                rate = (time.time() - started) / n
                left = int(rate * (total - n))
                print(
                    f"{n}/{total}  {rate:.1f}s/issue  ~{left // 60}m left"
                    + (f"  ({failed} failed)" if failed else "")
                    + (f"  ({degraded} left pending)" if degraded else ""),
                    flush=True,
                )

        clusters = session.exec(select(SystemicCluster)).all()
        with_rec = sum(1 for c in clusters if c.recommendation)
        print(
            f"done in {int(time.time() - started) // 60}m: "
            f"{total - failed - degraded} triaged, {failed} failed, "
            f"{degraded} left pending (model unreachable), "
            f"{len(clusters)} clusters ({with_rec} with a recommendation)"
        )
    return 1 if failed or degraded else 0


if __name__ == "__main__":
    sys.exit(main())
