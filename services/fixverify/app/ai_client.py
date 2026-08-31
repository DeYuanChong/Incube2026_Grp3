"""vLLM client for fix-and-verify: evidence recommendation (text model) and
proof-of-work relevance verification (vision model).

Policy (docs/04-ai-integration.md §6): AI is a pre-filter only. On any failure
the proof is marked 'inconclusive' and routed to human review — AI never blocks
a fix from reaching a human.
"""

import base64
import json
import logging
import mimetypes
import re

from openai import OpenAI

from . import config, prompts

log = logging.getLogger(__name__)

_client = OpenAI(
    base_url=config.VLLM_BASE_URL,
    api_key=config.VLLM_API_KEY,
    timeout=config.AI_TIMEOUT_SECONDS,
)


def _extract_json(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def recommend_evidence(category: str, title: str, description: str) -> dict:
    prompt = prompts.EVIDENCE.format(category=category, title=title, description=description)
    try:
        resp = _client.chat.completions.create(
            model=config.VLLM_TEXT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        data = _extract_json(resp.choices[0].message.content or "")
        if data and "recommended" in data:
            return data
    except Exception:
        log.warning("evidence recommendation failed", exc_info=True)
    return {
        "recommended": [{"media_type": "image", "what": "Photo of the completed fix",
                         "why": "Generic fallback (AI unavailable)"}],
        "requires_human_verification": True,
        "rationale": "AI unavailable; defaulting to human verification.",
    }


def check_relevance(image_path: str, description: str, recommendation: str, note: str) -> dict:
    """Returns {"verdict": relevant|irrelevant|inconclusive, "confidence": float, "reason": str}."""
    mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        prompt = prompts.RELEVANCE.format(
            description=description, recommendation=recommendation or "none", note=note or "none"
        )
        resp = _client.chat.completions.create(
            model=config.VLLM_VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }],
            temperature=0,
        )
        data = _extract_json(resp.choices[0].message.content or "")
        if data and data.get("verdict") in ("relevant", "irrelevant", "inconclusive"):
            return {
                "verdict": data["verdict"],
                "confidence": float(data.get("confidence", 0.5)),
                "reason": str(data.get("reason", "")),
            }
    except Exception:
        log.warning("relevance check failed; routing to human", exc_info=True)
    return {"verdict": "inconclusive", "confidence": 0.0,
            "reason": "Automated check unavailable; a human will review this proof."}
