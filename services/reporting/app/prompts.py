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
