"""Pure CSV -> app-model mapping for the ITeFM historical defect export.

No database access: every function here is deterministic and testable on its own.
`import_defects.py` owns the I/O; this module owns the field rules, which extend
the reference-schema mapping table in docs/02-data-model.md.

Run it directly for a mapping-only dry run (no DB needed):

    python scripts/defect_mapping.py raw_data/*.csv
"""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

# The export carries no timezone; the source system records Singapore local time.
SOURCE_TZ = timezone(timedelta(hours=8))
SOURCE_DT_FORMAT = "%d-%b-%Y %H:%M:%S"

# Location is a single path string:
#   "All Location > DSTA > Depot Road > <building> > <floor> > <room>"
# The first three segments are a constant prefix.
LOCATION_PREFIX_SEGMENTS = 3
UNKNOWN_BUILDING = "Unknown"   # 14 rows have no building segment
UNKNOWN_FLOOR = "Unspecified"  # 248 rows have no floor segment

# reporting.issues.title is TEXT (no DB constraint), but IssueCreate caps it at
# 200 and the dashboard renders it in a table cell — keep titles short.
TITLE_MAX_CHARS = 120
TITLE_MIN_CHARS = 3

# "Pending Review" rows carry no arrival, recovery or closure timestamp: they are
# unattended new reports, not repairs awaiting proof. Set this to
# "pending_verification" instead if you want them in the Fix & Verify queue.
PENDING_REVIEW_STATUS = "reported"

STATUS_MAP = {
    "Closed": "closed",
    "Pending Review": PENDING_REVIEW_STATUS,
    "Pending Rectification": "in_progress",
    "Cancelled": "cancelled",
    "Pending Closure": "verified",  # recovered but not yet closed
}

# Every source Problem Type collapses to `others`: the app's six-value enum has
# no home for ~42% of the corpus. The original value is preserved verbatim on the
# "imported" issue event, so this can be revisited without re-parsing the CSV.
DEFAULT_CATEGORY = "others"

# Source columns kept on the imported event for provenance / later re-mapping.
PROVENANCE_COLUMNS = (
    "Problem Type",
    "Status",
    "Issue",
    "Impact",
    "Emergency",
    "Requestor Name",
    "Exact Location",
    "Related Job Request NO.",
    "Resolution Type",
    "Is Critical System?",
)

_REPORTER_RE = re.compile(r"user (\d+)$")


class MappingError(ValueError):
    """A row could not be mapped (bad date, unknown status, ...)."""


def parse_dt(value: str | None) -> str | None:
    """'01-Jul-2025 09:14:27' (SGT) -> '2025-07-01T01:14:27+00:00' (UTC)."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        naive = datetime.strptime(value, SOURCE_DT_FORMAT)
    except ValueError as exc:
        raise MappingError(f"unparseable timestamp {value!r}") from exc
    return naive.replace(tzinfo=SOURCE_TZ).astimezone(timezone.utc).isoformat()


def parse_location(value: str | None) -> tuple[str, str, str | None]:
    """Split the location path into (building, floor, room)."""
    segments = [s.strip() for s in (value or "").split(">")]
    tail = segments[LOCATION_PREFIX_SEGMENTS:]
    building = tail[0] if len(tail) > 0 and tail[0] else UNKNOWN_BUILDING
    floor = tail[1] if len(tail) > 1 and tail[1] else UNKNOWN_FLOOR
    room = tail[2] if len(tail) > 2 and tail[2] else None
    return building, floor, room


# Recovering a floor the location path did not carry. The level is usually
# written into the free text instead — "Annex Level 3 pole B17", "L24 FW",
# "DTTCC #01-01B" — so these read it back out. Both patterns demand an explicit
# level marker, because the text is full of numbers that are not floors: "Tower
# 5", "Connection 1", "staircase 8", "Block 208", "pole B17", "24F63".
_LEVEL_RE = re.compile(r"(?:\b(?:level|lvl)\s*|\bl)(\d{1,2})\b", re.IGNORECASE)
_UNIT_RE = re.compile(r"#(\d{2})-\d")          # Singapore unit: #04-10G is level 4
_NUMERIC_FLOOR_RE = re.compile(r"^L?(\d{1,2})$", re.IGNORECASE)

# Where to look, most authoritative first. `Exact Location` is the structured
# free-text field; the description carries it when that one is blank.
FLOOR_TEXT_COLUMNS = ("Exact Location", "Problem Description")


def floor_formats(rows: list[dict]) -> dict[str, dict[int, str]]:
    """Each building's own spelling of each floor, learned from the rows whose
    location path *did* carry one: `{"DTTA": {7: "07"}, "BLK B": {3: "3"}}`.

    Not a constant, because the export has no single format: DTTA and Annex zero
    pad (`07`), BLK B does not (`3`), MSCP prefixes (`L07`). A recovered floor
    written in the wrong one lands beside its own building's group instead of in
    it — `Annex|3` next to `Annex|03` — which is a worse failure than leaving it
    unplaced, since it looks placed.

    Only floors that are a bare or `L`-prefixed number are learned. `PL1`,
    `Rooftop` and the one literal `Level 4` have no number to match text
    against, and `PL1` would otherwise claim level 1 from `01`. Where two
    spellings share a number the more common one wins.
    """
    seen: dict[str, dict[int, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for row in rows:
        building, floor, _ = parse_location(row.get("Location"))
        match = _NUMERIC_FLOOR_RE.match(floor)
        if match:
            seen[building][int(match.group(1))][floor] += 1
    return {
        building: {n: spellings.most_common(1)[0][0] for n, spellings in floors.items()}
        for building, floors in seen.items()
    }


def recover_floor(building: str, formats: dict[str, dict[int, str]], *texts: str | None) -> str | None:
    """The floor named in a row's free text, in its building's own format.

    Silent unless the text is unambiguous, in three ways. Text naming two
    levels ("Level 14 and Level 15") names neither. The plural is not a marker
    at all, so "dispensers at DTTA levels 14 and 15" matches nothing rather
    than taking the first number it sees. And a level the building has never
    had ("Level 30") is a misread, not a discovery.

    All three leave the row on `UNKNOWN_FLOOR`, where the insight rules already
    know not to trust it — 90 of 248 rows stay there, which is the right answer
    for "Level Staff Gantry" and for a fire door in Hillview Camp.
    """
    known = formats.get(building) or {}
    if not known:
        return None  # a building whose floors we have never seen spelled
    for text in texts:
        found = {int(n) for n in _LEVEL_RE.findall(text or "")}
        found |= {int(n) for n in _UNIT_RE.findall(text or "")}
        if len(found) == 1:
            level = found.pop()
            if level in known:
                return known[level]
    return None


def parse_equipment(value: str | None) -> str | None:
    """'All Equipment > LIGHTING > DIC-SL-0020' -> 'DIC-SL-0020'."""
    value = (value or "").strip()
    if not value:
        return None
    return value.split(">")[-1].strip() or None


def build_title(description: str, problem_type: str) -> str:
    """First line of the description, truncated; problem type as a fallback.

    907 of the 2,182 descriptions are multi-line, and line one is nearly always
    the summary ("Level 24FW #24-01" / "Door making screechy sound...").
    """
    first_line = " ".join((description or "").strip().splitlines()[:1]).strip()
    first_line = " ".join(first_line.split())
    if len(first_line) < TITLE_MIN_CHARS:
        first_line = (problem_type or "").strip()
    if len(first_line) > TITLE_MAX_CHARS:
        first_line = first_line[: TITLE_MAX_CHARS - 1].rstrip() + "…"
    return first_line or "Imported defect"


def build_description(description: str, issue: str) -> str:
    """Problem Description, with the structured `Issue` symptom appended."""
    body = (description or "").strip()
    symptom = (issue or "").strip()
    if symptom:
        body = f"{body}\n\nIssue: {symptom}" if body else f"Issue: {symptom}"
    return body


def allocate_reporters(rows: list[dict]) -> list[str]:
    """One reporter name per row; blanks continue the existing `user N` sequence.

    The masked export uses `user 1`..`user 971`; the 137 blank rows become
    `user 972` onward so they never collide with a real (masked) reporter.
    """
    highest = 0
    for row in rows:
        match = _REPORTER_RE.fullmatch((row.get("Reported By") or "").strip())
        if match:
            highest = max(highest, int(match.group(1)))

    names, next_n = [], highest + 1
    for row in rows:
        existing = (row.get("Reported By") or "").strip()
        if existing:
            names.append(existing)
        else:
            names.append(f"user {next_n}")
            next_n += 1
    return names


def map_row(
    row: dict, reporter_name: str, formats: dict[str, dict[int, str]] | None = None
) -> tuple[dict, dict]:
    """Map one CSV row to (Issue field kwargs, provenance detail).

    `formats` comes from `floor_formats` over the whole file; without it a row
    whose location path carries no floor stays on `UNKNOWN_FLOOR`.
    """
    source_status = (row.get("Status") or "").strip()
    if source_status not in STATUS_MAP:
        raise MappingError(f"unknown source status {source_status!r}")
    status = STATUS_MAP[source_status]

    building, floor, room = parse_location(row.get("Location"))
    # The path had no floor segment, but the free text usually names the level.
    recovered_floor = (
        recover_floor(building, formats or {}, *(row.get(c) for c in FLOOR_TEXT_COLUMNS))
        if floor == UNKNOWN_FLOOR else None
    )
    floor = recovered_floor or floor
    recovered_at = parse_dt(row.get("Recovery Date Time"))
    created_at = parse_dt(row.get("Reported Date Time"))
    if not created_at:
        raise MappingError("missing Reported Date Time")

    def optional(column: str) -> str | None:
        return (row.get(column) or "").strip() or None

    fields = {
        "reference_no": (row.get("Defect NO.") or "").strip(),
        "category": DEFAULT_CATEGORY,
        "category_source": "user",
        "title": build_title(row.get("Problem Description", ""), row.get("Problem Type", "")),
        "description": build_description(
            row.get("Problem Description", ""), row.get("Issue", "")
        ),
        "building": building,
        "floor": floor,
        "room": room,
        "equipment_name": parse_equipment(row.get("Equipment Name")),
        "reporter_name": reporter_name,
        # The masked export carries no contact numbers; the column is NOT NULL,
        # so historical rows import with an empty string rather than a value.
        "mobile_number": "",
        "status": status,
        # Triage never ran on this data — severity/urgency stay NULL, and
        # is_critical_system is write-only in the app today (nothing reads it).
        "severity": None,
        "urgency": None,
        "is_critical_system": False,
        # The source's Related Job Request NO. is strictly 1:1 (426 filled, 426
        # distinct), so the export contains no duplicate groups to carry over.
        "duplicate_group_id": None,
        "duplicate_count": 1,
        # Source Resolution Type is 90% blank and 227/231 of the rest are
        # "Others" — not worth mapping onto the app's enum.
        "resolution_type": None,
        "resolution_notes": optional("Problem Resolution"),
        "cancellation_reason": optional("Cancellation Remarks"),
        "closed_by": "admin" if status == "closed" else None,
        "created_at": created_at,
        "triaged_at": None,
        "work_started_at": parse_dt(row.get("Arrive On Site Date/Time")),
        "fixed_at": recovered_at,
        # No separate verification step existed; recovery is the best proxy.
        "verified_at": recovered_at,
        "closed_at": parse_dt(row.get("Closed Date Time")),
        "updated_at": parse_dt(row.get("Modified Date Time")) or created_at,
    }
    if not fields["reference_no"]:
        raise MappingError("missing Defect NO.")

    provenance = {
        "source": "ITeFM defect report export",
        "source_reference_no": fields["reference_no"],
        # An inferred floor is not a reported one; say so where the raw columns
        # that produced it are already kept.
        **({"floor_recovered_from_text": recovered_floor} if recovered_floor else {}),
        **{col: (row.get(col) or "").strip() for col in PROVENANCE_COLUMNS},
    }
    return fields, provenance


def load_rows(csv_path: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def map_file(csv_path: str) -> tuple[list[tuple[dict, dict]], list[tuple[int, str]]]:
    """Map an entire CSV. Returns (mapped rows, [(row number, error)])."""
    rows = load_rows(csv_path)
    reporters = allocate_reporters(rows)
    formats = floor_formats(rows)
    mapped: list[tuple[dict, dict]] = []
    errors: list[tuple[int, str]] = []
    for index, (row, reporter) in enumerate(zip(rows, reporters), start=2):
        try:
            mapped.append(map_row(row, reporter, formats))
        except MappingError as exc:
            errors.append((index, str(exc)))
    return mapped, errors


def _check() -> None:
    """Floor recovery, on the shapes the real export actually contains.

    Runs with no CSV and no database: `python scripts/defect_mapping.py`.
    """
    # Each building's own spelling, learned from the rows that carried one.
    rows = [
        {"Location": "All Location > DSTA > Depot Road > DTTA > 07 > Rm1"},
        {"Location": "All Location > DSTA > Depot Road > DTTA > 04"},
        {"Location": "All Location > DSTA > Depot Road > BLK B > 3"},
        {"Location": "All Location > DSTA > Depot Road > MSCP > L04"},
        {"Location": "All Location > DSTA > Depot Road > Annex > PL1"},
        {"Location": "All Location > DSTA > Depot Road > DTTA"},  # the unplaced kind
    ]
    formats = floor_formats(rows)
    assert formats["DTTA"] == {7: "07", 4: "04"}
    assert formats["BLK B"] == {3: "3"}, "BLK B does not zero-pad; do not impose one format"
    assert formats["MSCP"] == {4: "L04"}
    # PL1 has no number to match text against, and would otherwise claim level 1
    assert "Annex" not in formats

    # The level is written into the free text; read it back in the building's format.
    assert recover_floor("DTTA", formats, "L7 FW power tripped") == "07"
    assert recover_floor("DTTA", formats, "DTTCC Level 7") == "07"
    assert recover_floor("DTTA", formats, "#04-10G 2 lights flickering") == "04"
    assert recover_floor("BLK B", formats, "Blk B Level 3") == "3"
    assert recover_floor("MSCP", formats, "carpark lvl 4") == "L04"

    # Numbers that are not floors. Every one of these is in the real export.
    assert recover_floor("DTTA", formats, "Connection 1, Tower 5 Level 4") == "04"
    assert recover_floor("DTTA", formats, "Annex Level 7 staircase 8") == "07"
    assert recover_floor("DTTA", formats, "Block 208 staircase 1") is None
    assert recover_floor("DTTA", formats, "pole B17") is None
    assert recover_floor("DTTA", formats, "Level Staff Gantry") is None
    assert recover_floor("DTTA", formats, "Found 01 x rat in office drawer") is None

    # Ambiguity is silence, three ways.
    assert recover_floor("DTTA", formats, "Level 7 and Level 4 both dark") is None
    assert recover_floor("DTTA", formats, "dispensers at levels 14 and 15") is None
    assert recover_floor("DTTA", formats, "Level 30 penthouse") is None, "not a floor DTTA has"
    # ...as is a building whose floors we have never seen spelled.
    assert recover_floor("Gombak FMP", formats, "Level 4") is None
    assert recover_floor("DTTA", {}, "Level 4") is None

    # Most authoritative column first; fall through when it names nothing.
    assert recover_floor("DTTA", formats, "Level Staff Gantry", "L4 IRC toilet") == "04"
    assert recover_floor("DTTA", formats, None, "") is None

    # A row whose path carries a floor is never second-guessed from text.
    fields, prov = map_row(
        {"Location": "All Location > DSTA > Depot Road > DTTA > 07",
         "Exact Location": "Level 4", "Defect NO.": "X1", "Status": "Closed",
         "Reported Date Time": "01-Jul-2025 09:14:27"}, "user 1", formats)
    assert fields["floor"] == "07"
    assert "floor_recovered_from_text" not in prov
    # ...and one whose path does not says so in its provenance.
    fields, prov = map_row(
        {"Location": "All Location > DSTA > Depot Road > DTTA",
         "Exact Location": "L4 IRC toilet", "Defect NO.": "X2", "Status": "Closed",
         "Reported Date Time": "01-Jul-2025 09:14:27"}, "user 1", formats)
    assert fields["floor"] == "04"
    assert prov["floor_recovered_from_text"] == "04"

    print("defect_mapping: ok")


if __name__ == "__main__":
    import sys
    from collections import Counter

    _check()
    if len(sys.argv) != 2:
        sys.exit(0 if len(sys.argv) == 1 else "usage: python scripts/defect_mapping.py <export.csv>")

    mapped, errors = map_file(sys.argv[1])
    print(f"mapped {len(mapped)} rows, {len(errors)} errors")
    for line_no, message in errors[:10]:
        print(f"  line {line_no}: {message}")

    for label in ("status", "category", "building"):
        counts = Counter(fields[label] for fields, _ in mapped)
        print(f"\n{label}:")
        for value, count in counts.most_common(10):
            print(f"  {count:5d}  {value}")

    sentinel_floor = sum(1 for f, _ in mapped if f["floor"] == UNKNOWN_FLOOR)
    recovered = sum(1 for _, p in mapped if "floor_recovered_from_text" in p)
    print(
        f"\nsentinels: building={sum(1 for f, _ in mapped if f['building'] == UNKNOWN_BUILDING)}"
        f" floor={sentinel_floor}"
        f" (+{recovered} floors recovered from the free text)"
    )
