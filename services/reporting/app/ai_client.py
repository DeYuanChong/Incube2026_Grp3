"""Thin client for the OpenAI-compatible vLLM endpoint.

All calls degrade gracefully: on any failure the caller gets None and the
issue flow proceeds without AI (docs/04-ai-integration.md).
"""

import json
import logging
import re

from openai import OpenAI

from . import config
from .models import Category
from .prompts import CATEGORIZE

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
