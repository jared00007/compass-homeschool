"""Annual month-day dates that recur every year.

Two things in Compass are "this same date, every year": the first day of the
school year, and Washington's Declaration of Intent filing deadline. Both need
the same arithmetic -- the next occurrence of a given MM-DD, today or later --
so it lives in one place rather than twice.
"""

from __future__ import annotations

from datetime import date


def date_in_year(mmdd: str, year: int) -> date:
    """`mmdd` (MM-DD) realized in a specific year.

    Falls back to September 1st on a malformed setting or an impossible date
    (Feb 29 in a non-leap year) rather than raising -- a typo in a
    family-editable setting should degrade, not break the page.
    """
    try:
        month, day = (int(part) for part in mmdd.split("-"))
        return date(year, month, day)
    except (ValueError, TypeError, AttributeError):
        return date(year, 9, 1)


def next_annual_date(mmdd: str, on: date | None = None) -> date:
    """The next date matching `mmdd` that is `on` or later."""
    on = on or date.today()
    candidate = date_in_year(mmdd, on.year)
    if candidate < on:
        candidate = date_in_year(mmdd, on.year + 1)
    return candidate


def days_until(target: date, on: date | None = None) -> int:
    return (target - (on or date.today())).days
