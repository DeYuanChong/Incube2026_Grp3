"""Thin client for the OpenAI-compatible vLLM endpoint.

All calls degrade gracefully: on any failure the caller gets None and the
issue flow proceeds without AI (docs/04-ai-integration.md).
"""

import base64
import json
import logging
import mimetypes
import re

from openai import OpenAI

from . import config
from .models import Category
from .prompts import CATEGORIZE, VERIFY_PHOTO

log = logging.getLogger(__name__)

_client = OpenAI(
    base_url=config.VLLM_BASE_URL,
    api_key=config.VLLM_API_KEY,
    timeout=config.AI_TIMEOUT_SECONDS,
)


def _extract_json(text: str) -> dict | None:
    """Tolerant JSON extractor (handles ```json fences and leading prose)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def suggest_category(
    title: str, description: str, location: str, user_category: str
) -> dict | None:
    """Returns {"category": Category, "confidence": float, "rationale": str} or None."""
    prompt = CATEGORIZE.format(
        title=title,
        description=description,
        location=location,
        user_category=user_category,
    )
    try:
        resp = _client.chat.completions.create(
            model=config.VLLM_TEXT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        data = _extract_json(resp.choices[0].message.content or "")
        if not data or data.get("category") not in Category.__members__:
            return None
        return {
            "category": Category(data["category"]),
            "confidence": float(data.get("confidence", 0.5)),
            "rationale": str(data.get("rationale", "")),
        }
    except Exception:
        log.warning("categorization call failed; keeping user category", exc_info=True)
        return None


_PHOTO_CHECK_FALLBACK = {
    "verdict": "inconclusive",
    "confidence": 0.0,
    "reason": "Automated check unavailable; suggestions are skipped.",
    "suggested_category": None,
    "suggested_title": None,
    "suggested_description": None,
}


def verify_photo(image_path: str, category: str, title: str, description: str) -> dict:
    """Returns a dict shaped like _PHOTO_CHECK_FALLBACK; never raises."""
    mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    prompt = VERIFY_PHOTO.format(category=category, title=title, description=description)
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        resp = _client.chat.completions.create(
            model=config.VLLM_VISION_MODEL,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]}],
            temperature=0,
        )
        data = _extract_json(resp.choices[0].message.content or "")
        if not data or data.get("verdict") not in ("aligned", "misaligned", "inconclusive"):
            return dict(_PHOTO_CHECK_FALLBACK)
        suggested_category = data.get("suggested_category")
        if suggested_category not in Category.__members__:
            suggested_category = None
        return {
            "verdict": data["verdict"],
            "confidence": float(data.get("confidence", 0.5)),
            "reason": str(data.get("reason", "")),
            "suggested_category": Category(suggested_category) if suggested_category else None,
            "suggested_title": data.get("suggested_title") or None,
            "suggested_description": data.get("suggested_description") or None,
        }
    except Exception:
        log.warning("photo verification call failed; skipping suggestions", exc_info=True)
        return dict(_PHOTO_CHECK_FALLBACK)
