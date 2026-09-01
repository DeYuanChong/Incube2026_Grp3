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

## 2. Expectation management / ETA (Reporting)

Deterministic formula (no LLM — must be explainable to the reporter):

```
base_days      = BASE_DAYS[category]            # e.g. lighting 2, aircon 3, others 5
severity_mult  = {critical: 0.5, high: 0.75, medium: 1.0, low: 1.5}[severity or medium]
load_factor    = 1 + min(open_issue_count / CAPACITY_PER_DAY, 2.0)   # live backlog pressure
estimated_days = round(base_days * severity_mult * load_factor, 1)
```

Returned with `estimate_basis` text, e.g. *"Lighting defects typically take ~2
days; 14 issues currently open (+40%)."* — so a reporter can judge whether
self-resolving is faster. Recomputed at triage when severity is set.

## 3. Severity & urgency suggestion (Triage)

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

## 4. Duplicate detection (Triage)

Heuristic first: same `category` + `building` + `floor` with `status` not closed,
created within 14 days → candidate set. Then LLM compares descriptions pairwise
("same underlying defect? yes/no + confidence"). Confirmed duplicates share a
`duplicate_group_id`; `duplicate_count` is written back to reporting and feeds
the severity bump rule.

## 5. Evidence recommendation (Fix & Verify)

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

## 6. Proof-of-work relevance verification (Fix & Verify)

- **When**: on every proof upload with `media_type=image`.
- **Call**: vision model with the image (base64 data URL) + issue description +
  evidence recommendation. Output: `{verdict: relevant|irrelevant|inconclusive,
  confidence, reason}`.
- **Leniency**: the check is a coarse junk filter, not a strict gate. The
  prompt instructs benefit-of-the-doubt judging — imperfect photos (blur,
  partial views, poor lighting, surrounding context) count as `relevant`, and
  `irrelevant` is reserved for clearly unrelated uploads (selfies, random
  screenshots, a different room entirely).
- **Policy**:
  - `relevant` → proof accepted for human verification; issue →
    `pending_verification`; admin notified (`proof.uploaded`).
  - `irrelevant` with confidence ≥ `RELEVANCE_REJECT_CONFIDENCE` (0.8) →
    HTTP 422 with the `reason` (e.g. *"The photo shows a corridor, but the
    issue describes a leaking toilet cistern"*); uploader must re-upload.
    The rejected proof row is kept for audit. Below the bar, the proof is
    stored and routed to human review instead.
  - `inconclusive`, non-image media, vision endpoint down, or
    `requires_human_verification` → accepted as *unverified*, flagged for the
    human to judge (AI never blocks a fix from reaching a human).
- **Final say is always human**: AI relevance is a pre-filter; an admin performs
  the actual verification (`POST /proofs/{id}/human-verify`).

## Prompt inventory

| Prompt file | Service | Task |
|---|---|---|
| `reporting/app/prompts.py::CATEGORIZE` | reporting | category suggestion |
| `triage/app/prompts.py::SEVERITY` | triage | severity/urgency + equipment |
| `triage/app/prompts.py::DUPLICATE` | triage | pairwise duplicate check |
| `triage/app/prompts.py::SYSTEMIC` | triage | cluster maintenance recommendation |
| `fixverify/app/prompts.py::EVIDENCE` | fixverify | evidence recommendation |
| `fixverify/app/prompts.py::RELEVANCE` | fixverify | vision relevance check |
