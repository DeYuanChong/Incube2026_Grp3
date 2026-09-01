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

# Photo upload — shares fixverify's "uploads" docker volume; photos live in
# their own subfolder so the two services' files don't mix (docs/04 §7)
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "data/uploads/issues")
VLLM_VISION_MODEL = os.getenv("VLLM_VISION_MODEL", os.getenv("VLLM_TEXT_MODEL", ""))
PHOTO_MISALIGN_CONFIDENCE = float(os.getenv("PHOTO_MISALIGN_CONFIDENCE", "0.6"))
