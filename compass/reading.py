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
