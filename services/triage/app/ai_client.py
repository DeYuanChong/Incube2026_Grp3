"""vLLM client for triage tasks. All calls degrade gracefully to rule-based
fallbacks (docs/04-ai-integration.md)."""

import json
import logging
import re

from openai import OpenAI

from . import config, prompts

log = logging.getLogger(__name__)

_client = OpenAI(
    base_url=config.VLLM_BASE_URL,
    api_key=config.VLLM_API_KEY,
    timeout=config.AI_TIMEOUT_SECONDS,
    max_retries=1,  # fail over to the graceful fallback sooner when the endpoint is down
)


def _chat_json(prompt: str) -> dict | None:
    try:
        resp = _client.chat.completions.create(
            model=config.VLLM_TEXT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        match = re.search(r"\{.*\}", resp.choices[0].message.content or "", re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception:
        log.warning("vLLM call failed", exc_info=True)
        return None


def suggest_severity(
    category: str, title: str, description: str, location: str,
    duplicate_count: int, systemic_count: int,
) -> dict:
    data = _chat_json(prompts.SEVERITY.format(
        category=category, title=title, description=description, location=location,
        duplicate_count=duplicate_count, systemic_count=systemic_count,
    ))
    if data and data.get("severity") in config.SEVERITY_ORDER:
        return {
            "severity": data["severity"],
            "urgency": data.get("urgency", "routine"),
            "rationale": str(data.get("rationale", "")),
            "equipment_name": data.get("equipment_name") or None,
        }
    # Fallback: rule-based default when the model is unavailable
    return {
        "severity": "medium",
        "urgency": "routine",
        "rationale": "Default (AI unavailable); admin review recommended.",
        "equipment_name": None,
    }


def is_duplicate(description_a: str, description_b: str, category: str, location: str) -> dict:
    data = _chat_json(prompts.DUPLICATE.format(
        description_a=description_a, description_b=description_b,
        category=category, location=location,
    ))
    if data is not None and "same_defect" in data:
        return {
            "same_defect": bool(data["same_defect"]),
            "confidence": float(data.get("confidence", 0.5)),
            "reason": str(data.get("reason", "")),
        }
    return {"same_defect": False, "confidence": 0.0, "reason": "AI unavailable"}


def systemic_recommendation(cluster_key: str, count: int, window_days: int,
                            issue_lines: str) -> str | None:
    data = _chat_json(prompts.SYSTEMIC.format(
        cluster_key=cluster_key, count=count, window_days=window_days,
        issue_lines=issue_lines,
    ))
    return data.get("recommendation") if data else None


def card_action(title: str, body: str, evidence: str, report_lines: str) -> str | None:
    """One card's `action`, written from the reports behind it.

    None on any failure, which the caller reads as "keep the template" — the
    card is already useful without this, so a dead model must not empty it.
    """
    data = _chat_json(prompts.CARD_ACTION.format(
        title=title, body=body, evidence=evidence, reports=report_lines,
    ))
    action = (data or {}).get("action")
    return str(action).strip() if action else None


def fault_patterns(where: str, count: int, minimum: int, report_lines: str) -> list[dict] | None:
    """Recurring faults in one location's free text, as raw model output.

    Returned unvalidated on purpose: the report numbers are the model's claim,
    and `insights.verified_patterns` is what turns them into members. None means
    the call failed — distinct from `[]`, which means it ran and found nothing
    and is worth storing so the location is not rescanned immediately.
    """
    data = _chat_json(prompts.FAULT_PATTERNS.format(
        where=where, count=count, minimum=minimum, reports=report_lines,
    ))
    if data is None:
        return None
    patterns = data.get("patterns")
    return patterns if isinstance(patterns, list) else []
