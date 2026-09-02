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

CARD_ACTION = """You are a facilities maintenance planner. A monitoring rule raised
this finding about a building:

FINDING: {title}
{body}
EVIDENCE: {evidence}

The defect reports behind it:
{reports}

State ONE concrete next action. If the reports show a specific recurring fault,
name it. If they do not, say the finding is a volume signal only and say what
would confirm a cause. Do not invent detail that is not in the reports above.

Respond with strict JSON only:
{{"action": "<two sentences maximum>"}}
"""

FAULT_PATTERNS = """These are {count} facility defect reports from one location
({where}). They are filed under a single category, so category grouping tells us
nothing — the patterns have to come from what the reports say.

{reports}

Group them into recurring fault patterns. Assign each report to AT MOST ONE
pattern. Only report a pattern with {minimum} or more reports. Leave unrelated
reports out entirely rather than forcing them into a group. `shared_root_cause`
is whether the reports in the pattern plausibly come from ONE underlying fault,
as opposed to separate things that happen to be similar.

Respond with strict JSON only:
{{"patterns": [{{"name": "<short name>", "reports": [<report numbers>],
  "shared_root_cause": <true|false>, "why": "<one sentence>",
  "action": "<one concrete next step>"}}]}}
"""
