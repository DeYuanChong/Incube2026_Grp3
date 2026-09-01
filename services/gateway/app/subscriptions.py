"""Event fan-out table: event_type → subscriber webhook URLs.

`*` subscribes to every event. URLs are built from the service env vars so the
same table works locally and in docker-compose.
"""

import os

REPORTING_URL = os.getenv("REPORTING_URL", "http://localhost:8001")
TRIAGE_URL = os.getenv("TRIAGE_URL", "http://localhost:8002")
FIXVERIFY_URL = os.getenv("FIXVERIFY_URL", "http://localhost:8003")
NOTIFICATION_URL = os.getenv("NOTIFICATION_URL", "http://localhost:8004")

SUBSCRIPTIONS: dict[str, list[str]] = {
    "*": [f"{NOTIFICATION_URL}/webhooks/events"],
    "issue.created": [f"{TRIAGE_URL}/webhooks/events"],
    "issue.closed": [f"{TRIAGE_URL}/webhooks/events"],
    "issue.status_changed": [f"{TRIAGE_URL}/webhooks/events"],
    "issue.triaged": [f"{FIXVERIFY_URL}/webhooks/events"],
}


def subscribers_for(event_type: str) -> list[str]:
    return SUBSCRIPTIONS.get("*", []) + SUBSCRIPTIONS.get(event_type, [])
