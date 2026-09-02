# 04 — AI Integration

All AI features call a **self-hosted OpenAI-compatible vLLM endpoint** through the
`openai` Python client. No cloud AI dependency.

## Configuration (shared env vars, see `.env.example`)

| Var | Meaning |
|---|---|
| `VLLM_BASE_URL` | e.g. `http://vllm-host:8080/v1` |
| `VLLM_API_KEY` | Any string if the endpoint doesn't check keys |
| `VLLM_TEXT_MODEL` | Model name for chat/text tasks |
| `VLLM_VISION_MODEL` | Multimodal model name for proof-of-work image checks (can equal `VLLM_TEXT_MODEL` if it is multimodal) |
| `AI_TIMEOUT_SECONDS` | Default 30 |

Each service that needs AI has its own small `app/ai_client.py` (services stay
independently deployable; no shared library). All AI calls **degrade
gracefully**: if the endpoint is down or returns garbage, the feature falls back
(keep user category / rules-based severity / route proof to human review) and the
issue flow never blocks on AI.

All prompts request **strict JSON** responses and parse defensively
(`response_format={"type": "json_object"}` where supported, plus a tolerant
extractor for fenced JSON).

## 1. Smart categorization (Reporting)

- **When**: on `POST /issues` (and on description edit).
- **Prompt**: description + location → one of the six categories + confidence +
  one-line rationale.
- **Policy**: never override the reporter. If the suggestion differs from the
  user's category with confidence ≥ 0.6, the API returns the suggestion and the
  UI shows "Looks like *Toilet* — recategorize?" with an accept button
  (`POST /issues/{id}/accept-suggested-category`). Otherwise the user's category
  stands, and the suggestion is stored for triage analytics either way.

## 2. Severity & urgency suggestion (Triage)

- **Input**: description, category, location, `is_critical_system` keywords,
  duplicate count, and the systemic-cluster context (how many similar recent
  issues).
- **LLM output**: `{severity, urgency, rationale, equipment_name?}`.
- **Rules applied after the LLM (rules win)**:
  - `duplicate_count ≥ 3` → bump severity one level (affects more people).
  - Category `physical_security` → urgency at least `urgent`.
  - Keywords like "leak", "sparking", "exposed wiring" → `emergency`.
- Admin can confirm/override; overrides are stored (`admin_override_severity`)
  to later evaluate AI suggestion quality.

## 3. Duplicate detection (Triage)

Heuristic first: same `category` + `building` + `floor` with `status` not closed,
created within 14 days → candidate set. Then LLM compares descriptions pairwise
("same underlying defect? yes/no + confidence"). Confirmed duplicates share a
`duplicate_group_id`; `duplicate_count` is written back to reporting and feeds
the severity bump rule.

## 4. Evidence recommendation (Fix & Verify)

LLM, given issue description + category, returns:

```json
{
  "recommended": [
    {"media_type": "image", "what": "Thermostat reading before the fix", "why": "Documents the fault temperature"},
    {"media_type": "image", "what": "Thermostat reading after the fix", "why": "Proves recovery to setpoint"}
  ],
  "requires_human_verification": false,
  "rationale": "Aircon temperature is visually verifiable via thermostat photos."
}
```

`requires_human_verification=true` for defects that cannot be verified visually
(e.g. *"bad smell at Level 2"*) — those proofs skip auto-reject and go straight
to an admin. Recommendations are **suggestions only**; whatever the maintenance
user uploads is still processed.

## 5. Proof-of-work relevance verification (Fix & Verify)

- **When**: on every proof upload with `media_type=image`, once the work order
  has been **started** (a proof cannot be uploaded on an `open` order).
- **Call**: vision model with the image (base64 data URL) + issue description +
  evidence recommendation. Output: `{verdict: relevant|irrelevant|inconclusive,
  confidence, reason}`.
- **Leniency**: the check is a coarse junk filter, not a strict gate. The
  prompt instructs benefit-of-the-doubt judging — imperfect photos (blur,
  partial views, poor lighting, surrounding context) count as `relevant`, and
  `irrelevant` is reserved for clearly unrelated uploads (selfies, random
  screenshots, a different room entirely).
- **Two-step upload — the check never blocks or finalises**: uploading runs the
  check and stores the proof as a **draft** (`submitted=false`) with its verdict;
  the uploader sees the result and then confirms or cancels.
  - `relevant` / `inconclusive` / non-image media / vision endpoint down /
    `requires_human_verification` → the uploader **confirms**
    (`POST /proofs/{id}/submit`); the proof enters human verification, issue →
    `pending_verification`, admin notified (`proof.uploaded`).
  - `irrelevant` with confidence ≥ `RELEVANCE_REJECT_CONFIDENCE` (0.8) → a plain
    confirm is refused (422 `requires_override`, with the `reason` — e.g. *"The
    photo shows a corridor, but the issue describes a leaking toilet cistern"*).
    The uploader either **cancels** (`DELETE /proofs/{id}`, the draft and its file
    are discarded) and uploads a different proof, or **overrides**
    (`submit` with `override: true`) — the proof is flagged `ai_overridden` and
    sent for human sign-off anyway (shown with an "AI overridden" tag).
- **Final say is always human**: AI relevance is a pre-filter; an admin performs
  the actual verification (`POST /proofs/{id}/human-verify`) — including on an
  `ai_overridden` proof.

## 6. Photo verification & recategorization (Reporting)

- **When**: on `POST /issues/{id}/photos` (reporters can attach photos to
  their own report while it is still `status=reported`; stored permanently,
  sharing fixverify's `uploads` docker volume under an `issues/` subfolder).
  A second, pre-submit entry point exists: `POST /issues/preview-photo-check`
  runs the identical `ai_client.verify_photo` call against a photo picked in
  the report form *before the issue exists* — title/description/category are
  passed as form fields instead of read off a persisted `Issue`, and the file
  is written to disk only long enough for the AI call, then deleted (nothing
  is persisted, no `IssuePhoto` row, no majority-vote signal — that only
  applies once photos are actually attached to a real issue). The frontend
  calls it as soon as a photo is picked, if the reporter already has a chip
  or typed description to compare against, and shows any `misaligned`
  title/description suggestion inline under the description field, styled
  like the description-autocomplete banner in §7. A photo is checked at most
  once — dismissing the suggestion (or accepting it) never re-triggers a
  check for that same photo. The real `POST /issues/{id}/photos` call still
  re-runs its own verification when the photo is actually uploaded at
  submit time (unavoidable given the two are separate AI calls against two
  different code paths — the persisted `ai_suggested_title`/
  `ai_suggested_description`/`photo_note` on the created `Issue` remain the
  source of truth, not the pre-submit preview).
- **Call**: vision model with the image (base64 data URL) + the issue's
  current category/title/description in one joint call. Output:
  `{verdict: aligned|misaligned|inconclusive, confidence, reason,
  suggested_category, suggested_title, suggested_description}`
  (`suggested_*` only non-null when `verdict=misaligned` and confident).
- **Combining signals — suggest-only, like category suggestion in §1**:
  three signals feed the category suggestion — the issue's current category
  (`U`), the pending text-only suggestion from §1 if any (`T`), and a
  majority vote across all of the issue's photos (`P`; each photo votes for
  the category it was checked against if `aligned`, or its
  `suggested_category` if `misaligned` with a guess). If `P` disagrees with
  `U` but agrees with `T`, the existing recategorize suggestion is
  reinforced; if `P` instead agrees with `U` (backing the reporter against a
  lone disagreeing text-only read), the recategorize banner is suppressed in
  favor of a soft, non-actionable `photo_note`; a genuine three-way
  disagreement falls back to trusting the text-only suggestion, logging the
  conflict to the issue timeline for triage visibility only. Title/
  description suggestions are independent of this vote — sourced from
  whichever uploaded photo has the highest-confidence `misaligned` verdict.
- **Never auto-rewrites**: exactly like accepting a category suggestion, the
  reporter must explicitly accept via `POST /issues/{id}/accept-suggested-title`
  or `.../accept-suggested-description`. Editing the issue's text clears any
  pending photo-derived suggestions (they'd reference stale text).

## 7. Description autocomplete (Reporting)

- **When**: `POST /issues/suggest-description`, called while the report form is
  being filled, before the issue exists.
- **Prompt**: title + optional location + `existing_text` (what the reporter
  has typed so far) → a 1-2 sentence draft/continuation + confidence, **and**
  independently a `suggested_title`/`title_confidence` when the typed
  description describes a clearly different defect than the current title
  says (not just extra detail on the same one) — e.g. a reporter typing
  about a flooding toilet under a "Lighting — Flickering" title gets back a
  `suggested_title: "Plumbing — Flooding"` alongside the description
  continuation. `category` is deliberately **not** passed into the prompt —
  a continuation could otherwise lean on category-flavored phrasing instead
  of staying anchored to the reporter's own typed words, which defeats the
  point of an autocomplete on their own text (`category` still exists on the
  request schema for forward compatibility but is unused by the prompt).
  The two suggestions are accepted/dismissed independently in the UI; an
  accepted title becomes a `titleOverride` that wins over whatever the
  category/chip combination would otherwise have built (see §6's
  `preview-photo-check`, which sets the same override) — picking a chip
  explicitly always clears it back.
- **Policy**: suggestion only — the frontend offers accept/dismiss, never
  auto-fills. On AI failure, timeout, or an unusably vague title, the
  endpoint returns `description: null` with HTTP 200 so the form is never
  blocked.

## Prompt inventory

| Prompt file | Service | Task |
|---|---|---|
| `reporting/app/prompts.py::CATEGORIZE` | reporting | category suggestion |
| `reporting/app/prompts.py::VERIFY_PHOTO` | reporting | photo-vs-report verification |
| `reporting/app/prompts.py::SUGGEST_DESCRIPTION` | reporting | description autocomplete |
| `triage/app/prompts.py::SEVERITY` | triage | severity/urgency + equipment |
| `triage/app/prompts.py::DUPLICATE` | triage | pairwise duplicate check |
| `triage/app/prompts.py::SYSTEMIC` | triage | cluster maintenance recommendation (also the body of the admin escalation notification, doc 05) |
| `fixverify/app/prompts.py::EVIDENCE` | fixverify | evidence recommendation |
| `fixverify/app/prompts.py::RELEVANCE` | fixverify | vision relevance check |
