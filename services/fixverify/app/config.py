import os

from dotenv import load_dotenv

load_dotenv()

SERVICE_NAME = "fixverify"
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://app:app@localhost:5432/defects"
)
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")
REPORTING_URL = os.getenv("REPORTING_URL", "http://localhost:8001")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "data/uploads")

VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8080/v1")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "not-needed")
VLLM_TEXT_MODEL = os.getenv("VLLM_TEXT_MODEL", "")
VLLM_VISION_MODEL = os.getenv("VLLM_VISION_MODEL", os.getenv("VLLM_TEXT_MODEL", ""))
AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "30"))

# Auto-reject only clearly-unrelated proofs the model is confident about;
# below this bar an "irrelevant" verdict is stored but routed to human review
RELEVANCE_REJECT_CONFIDENCE = 0.8
