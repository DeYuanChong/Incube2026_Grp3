# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this service is

The **reporting** service (port 8001) is one of five FastAPI microservices in a
larger defect-reporting monorepo (`services/gateway`, `reporting`, `triage`,
`fixverify`, `notification`, plus a React `frontend/`). This service is the
**source of truth for issues**: intake, smart categorization, and the full
issue status state machine. Other services (`triage`,
`fixverify`) call back into this service's endpoints to advance an issue's
status; they never write to its tables directly.

Full cross-service design docs live at the repo root in `../../docs/`
(`00-design-overview.md`, `01-architecture.md`, `02-data-model.md`,
`03-api-contracts.md`, `04-ai-integration.md`, `05-triage-analytics.md`) —
read these when a change touches contracts other services depend on.

## Commands

Run from `services/reporting/`:

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8001 --reload
```

There are no tests or lint configs in this service currently.

The service needs a running Postgres (`DATABASE_URL`) and, for the full repo,
is normally brought up via `docker compose up --build` from the repo root —
see the root `README.md`. **After changing `requirements.txt`, rebuild the
container** (`docker compose up -d --build`); a plain `up` reuses the old
image and the service will crash with `ModuleNotFoundError`.

## Architecture

- `app/main.py` — all FastAPI routes. Every mutating endpoint follows the
  same pattern: load the `Issue`, mutate it, append an `IssueEvent` via
  `_log_event`, commit, then fire an event to the gateway via
  `background.add_task(events.publish, ...)`.
- `app/models.py` — SQLModel tables (`Issue`, `IssueEvent`, `IssuePhoto`) under
  the `reporting` Postgres schema, plus the `Status` enum and the authoritative
  `TRANSITIONS` state machine dict. **Any status transition must be checked
  against `TRANSITIONS`** — `POST /issues/{id}/status` rejects anything not
  listed (see `docs/00-design-overview.md` for the diagram). Note the
  resolved-on-arrival shortcut: `triaged → pending_verification` directly,
  skipping `in_progress`, when a defect was already fixed when maintenance
  arrived.
- `app/schemas.py` — Pydantic request bodies (separate from the SQLModel
  table models).
- `app/db.py` — engine setup; `init_db()` creates the `reporting` schema, the
  `pg_trgm` extension, and a GIN trigram index over `title || ' ' ||
  description` used by the fuzzy `q` search in `list_issues`.
- `app/ai_client.py` — thin OpenAI-SDK client against a self-hosted
  OpenAI-compatible endpoint (vLLM, or currently ZenMux per `.env.example`).
  **All AI calls must degrade gracefully**: any exception is caught and
  logged, returning `None` (`suggest_category`) or a fixed `inconclusive`
  fallback dict (`verify_photo`), so issue creation and photo upload never
  block on the AI being down. The suggested category is *never* used to
  override the user's chosen category — only surfaced as
  `ai_suggested_category` for the reporter to optionally accept via
  `POST /issues/{id}/accept-suggested-category`. `verify_photo` runs a
  vision-model check of an uploaded photo against the issue's current
  category/title/description (`VLLM_VISION_MODEL`, currently
  `deepseek/deepseek-v4-flash-vision-exp` per `.env.example`) and returns a
  verdict; same suggest-only rule applies to the `ai_suggested_title`/
  `ai_suggested_description` it can produce (accepted via
  `POST /issues/{id}/accept-suggested-title`/`-description`).
- `app/events.py` — fire-and-forget event publishing to the gateway's
  `/events` endpoint; failures are logged, never raised, since events are
  best-effort side channels, not the source of truth.
- `app/prompts.py` — LLM prompt templates, kept separate from client code.
- `app/config.py` — all env-driven config with defaults; loads `.env` via
  `python-dotenv`. Notable: `VLLM_*` (AI endpoint), `UPLOAD_DIR` (photo storage,
  defaults to `data/uploads/issues` — a subfolder of the same docker volume
  `fixverify` mounts for its proofs, so the two services' uploaded files
  don't collide), `PHOTO_MISALIGN_CONFIDENCE` (threshold above which a
  photo's misalignment verdict is trusted enough to populate a title/
  description suggestion).

### Photo upload & the category-suggestion decision matrix

`POST /issues/{id}/photos` (only while `status=reported`) saves the file,
runs `ai_client.verify_photo`, and then calls `_apply_photo_signal` in
`main.py`, which **recomputes from scratch** (re-querying *all* of the
issue's photos, not just the new one) whether to set
`ai_suggested_category`/`ai_suggested_title`/`ai_suggested_description` or
the softer, non-actionable `photo_note`. The logic combines three signals —
the issue's current category, the pending text-only suggestion (if any) from
`suggest_category`, and a **majority vote** across the issue's photos (each
photo votes for the category it was checked against if `aligned`, or its own
`suggested_category` if `misaligned`) — see `docs/04-ai-integration.md`
section 6 for the full decision table before touching this function; it's
easy to get the agree/disagree cases backwards. Editing an issue via `PATCH`
clears all of these suggestion/note fields, since they'd otherwise reference
now-stale text.

An alternate implementation of just `verify_photo`'s internals (an
independent-read-then-compare two-stage pipeline, vs. this branch's
single joint vision call) lives on branch `feat/reporting-photo-vision-two-stage`
for comparison — same external contract, different internals.

## Data model notes

- IDs are UUID4 strings; timestamps are UTC ISO-8601 **strings**, not native
  `timestamptz` (see `docs/02-data-model.md` for why — SQLite-era carryover,
  sorts and casts fine as-is).
- `reference_no` (`DEF-2026-NNNN`) is derived from a row count at creation
  time — not safe under concurrent writes, but acceptable for this PoC.
- The `reporting` schema is owned exclusively by this service; other
  services reach it only through this service's HTTP API, never direct SQL
  (the one documented exception in the whole system is triage reading
  `fixverify` directly — irrelevant here).
- Demo-mode identity comes from headers (`X-User`, `X-Role` via the `caller`
  dependency) — there is no real auth in this PoC.
