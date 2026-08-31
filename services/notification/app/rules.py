"""Event → notification mapping (docs/01-architecture.md event catalog).

Each rule returns a list of Notification kwargs for one incoming event.
"""


def notifications_for(event: dict) -> list[dict]:
    event_type = event.get("event_type", "")
    p = event.get("payload") or {}
    ref = p.get("reference_no", p.get("issue_id", ""))
    common = {"issue_id": p.get("issue_id"), "event_type": event_type}

    if event_type == "issue.created":
        return [{
            **common, "target_role": "admin",
            "title": f"New issue {ref}: {p.get('title', '')}",
            "body": f"Category {p.get('category')}, at {p.get('building')} / {p.get('floor')}. Auto-triage is running.",
        }]

    if event_type == "issue.triaged":
        return [
            {**common, "target_role": "maintenance",
             "title": f"Issue {ref} triaged — {p.get('severity')}/{p.get('urgency')}",
             "body": f"A work order is ready for: {p.get('title', '')}"},
            {**common, "target_role": "reporter", "target_user": p.get("reporter"),
             "title": f"Your issue {ref} has been triaged",
             "body": f"Severity: {p.get('severity')}, urgency: {p.get('urgency')}."},
        ]

    if event_type == "work_order.started":
        return [{
            **common, "target_role": "admin",
            "title": f"Work started on issue {p.get('issue_id', '')[:8]}",
            "body": f"Assignee: {p.get('assignee')}",
        }]

    if event_type == "proof.uploaded":
        passed = p.get("passed_relevance")
        relevance = ("passed the automated relevance check" if passed
                     else "needs human review (relevance inconclusive)")
        return [{
            **common, "target_role": "admin",
            "title": "Proof of work uploaded — verification needed",
            "body": f"Proof by {p.get('uploaded_by')} {relevance}. Please verify the fix.",
        }]

    if event_type == "proof.rejected":
        return [{
            **common, "target_role": "maintenance", "target_user": p.get("uploaded_by"),
            "title": "Proof of work rejected — please re-upload",
            "body": f"Reason: {p.get('reason', 'not stated')}",
        }]

    if event_type == "issue.verified":
        return [{
            **common, "target_role": "reporter",
            "title": "Your issue has been fixed and verified",
            "body": "Please confirm the resolution to close the loop (it will auto-close after the grace period).",
        }]

    if event_type == "issue.status_changed":
        return [{
            **common, "target_role": "reporter", "target_user": p.get("reporter"),
            "title": f"Issue {ref} is now '{p.get('status')}'",
            "body": p.get("detail") or "",
        }]

    if event_type == "issue.closed":
        return [{
            **common, "target_role": "admin",
            "title": f"Issue {ref} closed (by {p.get('closed_by')})",
            "body": p.get("title", ""),
        }]

    return []
