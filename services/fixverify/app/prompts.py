EVIDENCE = """You advise maintenance staff on what proof of work to upload after
fixing a facility defect, so an admin can verify the fix.

Issue:
- Category: {category}
- Title: {title}
- Description: {description}

Rules:
- Prefer visual proof (photos), before/after where meaningful (e.g. a thermostat
  reading before and after an aircon fix).
- Some defects cannot be verified visually (e.g. bad smells, intermittent
  noises) — for those, set requires_human_verification to true.

Respond with strict JSON only:
{{"recommended": [{{"media_type": "image|audio|other", "what": "...", "why": "..."}}],
  "requires_human_verification": <true|false>,
  "rationale": "<one sentence>"}}
"""

RELEVANCE = """You check whether an uploaded proof-of-work photo is relevant to a
facility defect that was reported.

Issue description: {description}
Recommended evidence (guideline only): {recommendation}
Uploader's note: {note}

Look at the attached image. Is it plausibly proof of work for THIS issue
(shows the affected location/equipment, or the completed fix)?

Respond with strict JSON only:
{{"verdict": "relevant|irrelevant|inconclusive", "confidence": <0.0-1.0>,
  "reason": "<one sentence, phrased for the uploader, e.g. 'The photo shows a corridor, but the issue describes a leaking toilet cistern'>"}}
"""
