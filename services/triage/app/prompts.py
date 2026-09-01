SEVERITY = """You triage facility defect reports, suggesting severity and urgency.

Severity levels: low, medium, high, critical
Urgency classes: routine, urgent, emergency

Issue:
- Category: {category}
- Title: {title}
- Description: {description}
- Location: {location}
- Reports of the same defect by different users: {duplicate_count}
- Similar recent issues at this location (possible systemic fault): {systemic_count}

Consider safety impact, how many people are affected, and whether a critical
system (security, power, water) is involved — if one is, say so in the rationale,
that is what the rationale is for. Also extract the specific equipment mentioned,
if any (e.g. "FCU-3-01", "hand dryer", "ceiling light").

Respond with strict JSON only:
{{"severity": "...", "urgency": "...", "rationale": "<one sentence>",
  "equipment_name": "<string or null>"}}
"""

DUPLICATE = """Do these two facility defect reports describe the SAME underlying defect?

Report A: {description_a}
Report B: {description_b}
Both are category "{category}" at {location}.

Respond with strict JSON only:
{{"same_defect": <true|false>, "confidence": <0.0-1.0>, "reason": "<one sentence>"}}
"""

SYSTEMIC = """You are a facilities maintenance planner. The following repeated defects
were reported for the same location profile:

Location/profile: {cluster_key}
Issues ({count} in {window_days} days):
{issue_lines}

Suggest ONE preventive or prescriptive maintenance action that addresses the
likely root cause (not per-ticket repairs).

Respond with strict JSON only:
{{"recommendation": "<2-3 sentences>"}}
"""
