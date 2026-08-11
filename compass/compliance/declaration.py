"""Washington's annual Declaration of Intent to homeschool (RCW 28A.200.010).

Distinct from `dashboard.py`'s hours/subjects report on purpose: this isn't
about what gets taught, it's a once-a-year filing with the local school
district that has nothing to do with lesson content or logged hours. A family
perfectly on pace for 1,000 hours can still be about to miss this deadline,
so it's tracked and surfaced separately rather than folded into the hours
report.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from compass.school_calendar import date_in_year, days_until
from compass.storage.db import Database


@dataclass
class DeclarationStatus:
    due_on: date
    filed_on: str | None
    days_remaining: int
    url: str

    @property
    def filed(self) -> bool:
        return self.filed_on is not None

    @property
    def overdue(self) -> bool:
        return not self.filed and self.days_remaining < 0


def status(db: Database, student_id: int, on: date | None = None) -> DeclarationStatus:
    """Which deadline currently applies, and whether it's been filed.

    The relevant deadline is simply this calendar year's occurrence of the
    configured month-day -- it does not roll forward to next year's the
    instant it passes. That distinction matters: rolling forward immediately
    (the way `next_annual_date` does for the school-year-start countdown,
    where there's nothing to miss) would turn a missed filing into a calm,
    350-day countdown instead of a warning. Staying on this year's date for
    the rest of the year means an unfiled deadline reads as overdue, and a
    filed one keeps reading as filed, right up until the calendar itself
    rolls into a year where the deadline is back in the future.
    """
    on = on or date.today()
    mmdd = db.get_setting("declaration_due") or "09-15"
    due_on = date_in_year(mmdd, on.year)

    row = db.declaration_status(student_id, due_on.isoformat())
    return DeclarationStatus(
        due_on=due_on,
        filed_on=row["filed_on"] if row else None,
        days_remaining=days_until(due_on, on),
        url=(db.get_setting("declaration_url") or "").strip(),
    )
