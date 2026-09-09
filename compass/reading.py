"""Reading-assignment maths -- turning a book's pages-per-day rate into the
page he should reach by the end of today.

Kept pure and db-free so it's unit-testable: the UI hands in the book's current
numbers and the page he was on when today began (frozen at the start of the day
via `reading_log`, so the target doesn't drift as he reports progress), and the
Home reading tile renders the result. A book with no rate, or no known length,
has no target -- the plain progress bar still shows.
"""

from __future__ import annotations


def daily_reading_target(
    total_pages: int | None, day_start_page: int | None, pages_per_day: int | None
) -> int | None:
    """The page he should reach by end of today: his start-of-day page plus the
    daily rate, capped at the book's length. None when there's no rate set or no
    total length to cap against."""
    if not pages_per_day or not total_pages:
        return None
    start = max(0, int(day_start_page or 0))
    return min(start + int(pages_per_day), int(total_pages))


# Which weekdays the standing reading card is assigned. Stored as a CSV of
# Python weekday numbers (Monday=0 .. Sunday=6); an empty string means "every
# day" (the default, and what an on-the-board book had before per-day control
# existed).

WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def parse_reading_days(reading_days: str | None) -> set[int] | None:
    """The set of weekdays reading is assigned, or None for 'every day' (the
    empty/unset default). Tolerant of junk -- a malformed entry is dropped."""
    if not reading_days:
        return None
    days: set[int] = set()
    for part in str(reading_days).split(","):
        part = part.strip()
        if part.isdigit() and 0 <= int(part) <= 6:
            days.add(int(part))
    return days


def serialize_reading_days(days: set[int] | None) -> str:
    """Store a weekday set as a sorted CSV; None or the full week collapses back
    to '' ('every day') so the common case stays the simple default."""
    if not days or set(days) == set(range(7)):
        return ""
    return ",".join(str(d) for d in sorted(days))


def reading_active_on(reading_days: str | None, weekday: int) -> bool:
    """Whether reading is assigned on a given weekday (Monday=0 .. Sunday=6).
    Empty/unset means every day."""
    days = parse_reading_days(reading_days)
    return days is None or weekday in days
