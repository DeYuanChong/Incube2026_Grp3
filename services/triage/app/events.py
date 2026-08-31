"""Publish events to the gateway event bus (fire-and-forget)."""

import logging
import uuid
from datetime import datetime, timezone

import httpx

from .config import GATEWAY_URL, SERVICE_NAME

log = logging.getLogger(__name__)


def publish(event_type: str, payload: dict) -> None:
    envelope = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "source": SERVICE_NAME,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    try:
        httpx.post(f"{GATEWAY_URL}/events", json=envelope, timeout=5)
    except httpx.HTTPError:
        log.warning("failed to publish %s to gateway", event_type, exc_info=True)
