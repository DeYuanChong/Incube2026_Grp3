import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://app:app@localhost:5432/defects"
)
# No GATEWAY_URL: triage consumes events (issue.created / issue.closed) and
# publishes none — escalation is not this service's job (docs/05).
REPORTING_URL = os.getenv("REPORTING_URL", "http://localhost:8001")

VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8080/v1")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "not-needed")
VLLM_TEXT_MODEL = os.getenv("VLLM_TEXT_MODEL", "")
AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "30"))

SYSTEMIC_MIN_COUNT = int(os.getenv("SYSTEMIC_MIN_COUNT", "3"))
SYSTEMIC_WINDOW_DAYS = int(os.getenv("SYSTEMIC_WINDOW_DAYS", "90"))
DUPLICATE_WINDOW_DAYS = int(os.getenv("DUPLICATE_WINDOW_DAYS", "14"))
# Below this the LLM's "same defect" verdict is not trusted enough to group on.
DUPLICATE_MIN_CONFIDENCE = float(os.getenv("DUPLICATE_MIN_CONFIDENCE", "0.6"))

# LLM work behind the insight cards. Both are filled in the background off a
# read, so both are bounded per request: a GET must not fan out into an
# unbounded number of model calls, and what is missed is filled on a later one.
INSIGHT_ACTION_LIMIT = int(os.getenv("INSIGHT_ACTION_LIMIT", "3"))
PATTERN_SCAN_LIMIT = int(os.getenv("PATTERN_SCAN_LIMIT", "2"))
PATTERN_REFRESH_DAYS = int(os.getenv("PATTERN_REFRESH_DAYS", "7"))
PATTERN_MIN_REPORTS = int(os.getenv("PATTERN_MIN_REPORTS", "12"))
PATTERN_MAX_REPORTS = int(os.getenv("PATTERN_MAX_REPORTS", "60"))

# Hard rules applied after the LLM (rules win) — docs/04-ai-integration.md §3
SEVERITY_ORDER = ["low", "medium", "high", "critical"]
DUPLICATE_BUMP_THRESHOLD = 3
EMERGENCY_KEYWORDS = ["leak", "sparking", "exposed wiring", "flood", "fire", "smoke"]
