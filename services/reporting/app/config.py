import os

from dotenv import load_dotenv

load_dotenv()

SERVICE_NAME = "reporting"
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://app:app@localhost:5432/defects"
)
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")

VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8080/v1")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "not-needed")
VLLM_TEXT_MODEL = os.getenv("VLLM_TEXT_MODEL", "")
AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "30"))

# # ETA estimation (docs/04-ai-integration.md §2)
# CAPACITY_PER_DAY = int(os.getenv("CAPACITY_PER_DAY", "10"))
# BASE_DAYS = {
#     "air_conditioning": 3.0,
#     "lighting": 2.0,
#     "cleanliness": 1.0,
#     "toilet": 2.0,
#     "physical_security": 1.0,
#     "others": 5.0,
# }
# SEVERITY_MULT = {"critical": 0.5, "high": 0.75, "medium": 1.0, "low": 1.5}

# SLA breach (agreed rule): an issue is in breach once it has been open longer
# than SLA_BREACH_DAYS and has not reached a settled status. "Settled" starts at
# pending_verification because the repair is done by then — what remains is
# proof and sign-off, which the ageing clock should not keep punishing.
SLA_BREACH_DAYS = int(os.getenv("SLA_BREACH_DAYS", "30"))
SLA_SETTLED_STATUSES = ("pending_verification", "verified", "closed", "cancelled")

# Role scoping for the dashboard. Reporters see only what they filed;
# maintenance sees only work that has reached their end of the pipeline.
MAINTENANCE_STATUSES = (
    "in_progress",
    "pending_verification",
    "verified",
    "closed",
    "cancelled",
)
OPEN_EXCLUDED_STATUSES = ("closed", "cancelled")
# Photo upload — shares fixverify's "uploads" docker volume; photos live in
# their own subfolder so the two services' files don't mix (docs/04 §7)
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "data/uploads/issues")
VLLM_VISION_MODEL = os.getenv("VLLM_VISION_MODEL", os.getenv("VLLM_TEXT_MODEL", ""))
PHOTO_MISALIGN_CONFIDENCE = float(os.getenv("PHOTO_MISALIGN_CONFIDENCE", "0.6"))
