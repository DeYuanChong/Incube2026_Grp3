"""Every insight card's "See N defects" link must return exactly those N.

The check is end-to-end on purpose. The number comes from triage, the rows come
from reporting, and the request crosses the gateway — the failure this guards
against lived in the space between the three, where no service's own tests can
see it: the card counted 67, the gateway truncated the repeated `id` params to
the last one, and the button landed on a page showing 1.

    docker compose up -d
    python scripts/check_card_links.py

Exits non-zero on the first card whose rows disagree with its count.
"""

import json
import sys
import urllib.parse
import urllib.request

GATEWAY = "http://localhost:8000"
# The check reads across the whole population, which is the admin's scope. A
# reporter running this legitimately sees fewer rows — that is role scoping
# working, not a broken link.
HEADERS = {"X-User": "Admin", "X-Role": "admin"}


def get(path: str):
    req = urllib.request.Request(f"{GATEWAY}{path}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def main() -> int:
    cards = get("/api/triage?by=location")["insights"]
    failures = 0
    for card in cards:
        wanted = [link["issue_id"] for link in card["linked"]]
        if not wanted:
            continue  # no evidence, no button (vendor cards)
        query = urllib.parse.urlencode(
            [("id", i) for i in wanted] + [("limit", min(len(wanted), 500))]
        )
        got = {row["id"] for row in get(f"/api/reporting/issues?{query}")}
        missing, extra = len(set(wanted) - got), len(got - set(wanted))
        status = "ok" if not (missing or extra) else f"MISSING {missing}, EXTRA {extra}"
        if missing or extra:
            failures += 1
        print(f"{card['source']:<20} says {card['linked_count']:>4} · {status}")

    print(f"\n{len(cards)} cards checked, {failures} mismatched")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
