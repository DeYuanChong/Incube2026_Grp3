import os

from dotenv import load_dotenv

load_dotenv()

SERVICE_NAME = "triage"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/triage.db")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")
REPORTING_URL = os.getenv("REPORTING_URL", "http://localhost:8001")

VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8080/v1")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "not-needed")
VLLM_TEXT_MODEL = os.getenv("VLLM_TEXT_MODEL", "")
AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "30"))

SYSTEMIC_MIN_COUNT = int(os.getenv("SYSTEMIC_MIN_COUNT", "3"))
SYSTEMIC_WINDOW_DAYS = int(os.getenv("SYSTEMIC_WINDOW_DAYS", "90"))
DUPLICATE_WINDOW_DAYS = int(os.getenv("DUPLICATE_WINDOW_DAYS", "14"))

# Hard rules applied after the LLM (rules win) — docs/04-ai-integration.md §3
SEVERITY_ORDER = ["low", "medium", "high", "critical"]
DUPLICATE_BUMP_THRESHOLD = 3
EMERGENCY_KEYWORDS = ["leak", "sparking", "exposed wiring", "flood", "fire", "smoke"]
