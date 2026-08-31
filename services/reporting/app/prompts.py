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
