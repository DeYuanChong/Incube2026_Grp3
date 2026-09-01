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

SUGGEST_DESCRIPTION = """You help a facility-defect reporter draft a description from just a title.
The reporter has not written a description yet.

Report so far:
- Title: {title}
- Category: {category}
- Location: {location}

Write a concise, plausible 1-2 sentence description a reporter could use as a starting
point, in plain factual language (no greetings, no questions). If the title is too vague
to infer anything useful, return an empty string for description.

Respond with strict JSON only:
{{"description": "<1-2 sentence description, or empty string>", "confidence": <0.0-1.0>}}
"""
