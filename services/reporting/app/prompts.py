CATEGORIZE = """You classify facility defect reports into exactly one category.

Categories: air_conditioning, lighting, cleanliness, toilet, physical_security, others

Defect report:
- Title: {title}
- Description: {description}
- Location: {location}
- Reporter chose category: {user_category}

Respond with strict JSON only:
{{"category": "<one of the categories>", "confidence": <0.0-1.0>, "rationale": "<one sentence>"}}
"""

VERIFY_PHOTO = """You check whether a photo of a facility defect matches the
reporter's written report.

Reporter's report:
- Category: {category}
- Title: {title}
- Description: {description}

Look at the attached photo and decide whether it plausibly shows the same
defect described above.

Respond with strict JSON only:
{{"verdict": "<aligned|misaligned|inconclusive>", "confidence": <0.0-1.0>,
"reason": "<one sentence>",
"suggested_category": "<one of: air_conditioning, lighting, cleanliness,
toilet, physical_security, others, or null>",
"suggested_title": "<a corrected short title, or null>",
"suggested_description": "<a corrected description, or null>"}}

Only fill suggested_category/suggested_title/suggested_description when
verdict is "misaligned" and you are confident about what the photo actually
shows. Otherwise use null for all three.
"""

# No category input here on purpose: the continuation must stay anchored to
# what the reporter actually typed, not lean on category-flavored phrasing.
SUGGEST_DESCRIPTION = """You help a facility-defect reporter draft a description,
and flag when their own words suggest the title no longer fits.

Report so far:
- Current title: {title}
- Location: {location}
- What the reporter has typed in the description field so far: {existing_text}

Task 1 — description: if the reporter has already typed something, continue/
complete it into a concise, plausible 1-2 sentence description that keeps
their wording and intent rather than replacing it. If they haven't typed
anything yet, draft a fresh 1-2 sentence description from the title alone.
Plain factual language, no greetings, no questions. If there isn't enough to
go on, return an empty string for description.

Task 2 — title check: using only what the reporter typed in the description
(not the title itself), decide whether the current title still accurately
summarizes the defect. Only propose a replacement if their words describe a
clearly different problem than the title says — not just extra detail on the
same problem. Keep it short (under 10 words). Otherwise return null.

Task 3 — missing details: the building/floor are already captured elsewhere
(shown above as Location), so don't ask for those. Only using what the
reporter has typed so far (skip this task entirely if they haven't typed
anything yet — return an empty list), check for two things separately:
"where" — a specific spot within that location (e.g. "near the entrance",
"above desk 12", "the ceiling", "the second stall") — and "when" — a time
reference for the defect (e.g. "since this morning", "for the past 3 days",
"just noticed it", "every time it rains"). Return a list containing "where"
and/or "when" for whichever is genuinely absent from their text; omit
whichever is already there.

Respond with strict JSON only:
{{"description": "<1-2 sentence description, or empty string>", "confidence": <0.0-1.0>,
"suggested_title": "<a corrected short title, or null>",
"title_confidence": <0.0-1.0, or null>,
"missing_details": ["where", "when"]}}
"""
