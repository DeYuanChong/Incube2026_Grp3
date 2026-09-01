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

SUGGEST_DESCRIPTION = """You help a facility-defect reporter draft a description.

Report so far:
- Title: {title}
- Category: {category}
- Location: {location}
- What the reporter has typed in the description field so far: {existing_text}

If the reporter has already typed something, continue/complete it into a concise,
plausible 1-2 sentence description that keeps their wording and intent rather than
replacing it. If they haven't typed anything yet, draft a fresh 1-2 sentence
description from the title alone. Plain factual language, no greetings, no questions.
If there isn't enough to go on, return an empty string for description.

Respond with strict JSON only:
{{"description": "<1-2 sentence description, or empty string>", "confidence": <0.0-1.0>}}
"""
