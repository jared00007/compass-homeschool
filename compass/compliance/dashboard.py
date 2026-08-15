"""Washington DOI compliance reporting.

The one arithmetic rule that governs this whole module:

    TOTAL instructional hours come from `activities.minutes`.
    PER-SUBJECT hours come from `activity_subject_credits.minutes`.

Those two do not reconcile, and they are not supposed to. A single 60-minute
waterfall lesson can credit 60 minutes of science, 25 of writing, and 15 of art
— that is Tier 2 folding, and it is how the family covers eleven subjects
without running eleven subjects. But it is still one hour of the student's life,
and the 1,000-hour floor counts hours of the student's life. Summing credits to
get a total would inflate the year by roughly 60%, which is the kind of error
that looks fine on a dashboard and falls apart under review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from compass import config
from compass.storage.db import Database
from compass.subjects import SUBJECT_KEYS, label

# Don't fire the Tier 3 balance warning until there's enough logged time for the
# percentage to mean anything. Ten hours.
MIN_MINUTES_FOR_TIER_SIGNAL = 600

# Above this, a "hours per week to catch up" figure is not a plan anyone can follow.
MAX_PLAUSIBLE_HOURS_PER_WEEK = 40

# Don't project a year-end day count from the first handful of days -- one day
# logged on day one projects to a wildly optimistic (or, one missed day,
# wildly pessimistic) year. Two weeks is enough for the rate to mean something.
MIN_ELAPSED_DAYS_FOR_DAY_PACE_SIGNAL = 14


@dataclass
class SubjectCoverage:
    key: str
    label: str
    minutes: int
    activity_count: int
    last_taught: str | None

    @property
    def hours(self) -> float:
        return round(self.minutes / 60, 1)

    @property
    def has_instruction(self) -> bool:
        return self.minutes > 0


@dataclass
class ComplianceReport:
    student_id: int
    start: str
    end: str

    total_minutes: int
    hour_target: int
    day_target: int
    instructional_days: int

    subjects: list[SubjectCoverage]
    minutes_by_tier: dict[str, int]
    tier3_cap_percent: int

    activity_count: int
    warnings: list[str] = field(default_factory=list)

    # -- headline numbers -----------------------------------------------------

    @property
    def total_hours(self) -> float:
        return round(self.total_minutes / 60, 1)

    @property
    def hours_remaining(self) -> float:
        return round(max(self.hour_target - self.total_hours, 0), 1)

    @property
    def hour_progress(self) -> float:
        return min(self.total_minutes / (self.hour_target * 60), 1.0) if self.hour_target else 0.0

    @property
    def day_progress(self) -> float:
        return min(self.instructional_days / self.day_target, 1.0) if self.day_target else 0.0

    # -- the 11-subject requirement ------------------------------------------

    @property
    def uncovered_subjects(self) -> list[SubjectCoverage]:
        return [s for s in self.subjects if not s.has_instruction]

    @property
    def subjects_covered(self) -> int:
        return sum(1 for s in self.subjects if s.has_instruction)

    @property
    def all_subjects_covered(self) -> bool:
        return not self.uncovered_subjects

    # -- Tier 3 family policy -------------------------------------------------

    @property
    def tier3_minutes(self) -> int:
        return self.minutes_by_tier.get(config.TIER_CHOICE, 0)

    @property
    def tier3_percent(self) -> float:
        if not self.total_minutes:
            return 0.0
        return round(100 * self.tier3_minutes / self.total_minutes, 1)

    @property
    def tier3_cap_minutes(self) -> int:
        """The Tier 3 allowance for a full year at the family's guideline."""
        return int(self.hour_target * 60 * self.tier3_cap_percent / 100)

    @property
    def tier3_over_cap(self) -> bool:
        """Soft signal only. Tier 3 hours always count — WA mandates no split.

        Checked two ways, because the absolute allowance alone is useless: 20% of
        1,000 hours is 200 hours, so a year that is 90% electives in October
        wouldn't trip it until roughly May — long past the point where the parent
        could rebalance. The proportional check is the one that's actionable, and
        it waits for a meaningful sample so a single first activity doesn't fire it.
        """
        if self.tier3_minutes > self.tier3_cap_minutes:
            return True
        return (
            self.total_minutes >= MIN_MINUTES_FOR_TIER_SIGNAL
            and self.tier3_percent > self.tier3_cap_percent
        )

    # -- pace -----------------------------------------------------------------

    def pace(self, today: date | None = None) -> dict[str, Any]:
        today = today or date.today()
        start = datetime.fromisoformat(self.start).date()
        end = datetime.fromisoformat(self.end).date()
        total_days = max((end - start).days + 1, 1)
        elapsed = min(max((today - start).days + 1, 0), total_days)
        remaining_days = max(total_days - elapsed, 0)

        expected_hours = round(self.hour_target * elapsed / total_days, 1)
        weeks_left = max(remaining_days / 7, 0.1)
        needed = round(self.hours_remaining / weeks_left, 1)

        # Straight-line projection of instructional *days* -- same technique
        # compass.costs.CostReport.projected_year_cost uses, extrapolating
        # today's rate to the end of the period. This is a genuinely separate
        # risk from hours: a single content day can carry three-plus hours
        # (four Tier 1 subjects at once), so the hour floor clears easily even
        # on a four-day week -- but a day only counts once something gets
        # logged on it, and volume on the days that do happen doesn't buy back
        # a day that never happened. A family running strictly Monday-Thursday
        # can clear 1,000 hours while still landing well short of 180 days.
        projected_days = (
            round(self.instructional_days * total_days / elapsed, 1) if elapsed else 0.0
        )

        return {
            "elapsed_days": elapsed,
            "remaining_days": remaining_days,
            "expected_hours_by_now": expected_hours,
            "ahead_by": round(self.total_hours - expected_hours, 1),
            "hours_per_week_needed": needed,
            # Past roughly a 40-hour week the "catch up" figure stops being a plan
            # and starts being arithmetic. Say so rather than printing a number
            # nobody can act on.
            "achievable": needed <= MAX_PLAUSIBLE_HOURS_PER_WEEK,
            "projected_days": projected_days,
            "days_on_track": projected_days >= self.day_target,
        }


def build_report(
    db: Database,
    student_id: int,
    start: str | None = None,
    end: str | None = None,
) -> ComplianceReport:
    if start is None or end is None:
        year_start, year_end = db.school_year_bounds()
        start = start or year_start
        end = end or year_end

    activities = db.list_activities(student_id, start=start, end=end)

    total_minutes = sum(int(a["minutes"]) for a in activities)
    instructional_days = len({a["occurred_on"] for a in activities})

    minutes_by_tier: dict[str, int] = {tier: 0 for tier in config.TIERS}
    subject_minutes: dict[str, int] = {key: 0 for key in SUBJECT_KEYS}
    subject_counts: dict[str, int] = {key: 0 for key in SUBJECT_KEYS}
    subject_last: dict[str, str | None] = {key: None for key in SUBJECT_KEYS}

    for activity in activities:
        tier = activity["tier"]
        minutes_by_tier[tier] = minutes_by_tier.get(tier, 0) + int(activity["minutes"])
        for subject, credited in (activity.get("credits") or {}).items():
            if subject not in subject_minutes:
                continue
            subject_minutes[subject] += int(credited)
            subject_counts[subject] += 1
            occurred = activity["occurred_on"]
            if subject_last[subject] is None or occurred > subject_last[subject]:
                subject_last[subject] = occurred

    subjects = [
        SubjectCoverage(
            key=key,
            label=label(key),
            minutes=subject_minutes[key],
            activity_count=subject_counts[key],
            last_taught=subject_last[key],
        )
        for key in SUBJECT_KEYS
    ]

    report = ComplianceReport(
        student_id=student_id,
        start=start,
        end=end,
        total_minutes=total_minutes,
        hour_target=db.get_int_setting("annual_hour_target"),
        day_target=db.get_int_setting("annual_day_target"),
        instructional_days=instructional_days,
        subjects=subjects,
        minutes_by_tier=minutes_by_tier,
        tier3_cap_percent=db.get_int_setting("tier3_cap_percent"),
        activity_count=len(activities),
    )

    if report.uncovered_subjects:
        names = ", ".join(s.label for s in report.uncovered_subjects)
        report.warnings.append(
            f"No instruction logged yet this year in: {names}. Washington requires "
            "instruction in all eleven."
        )
    if report.tier3_over_cap:
        student = db.get_student(student_id)
        tier3 = config.tier_label(config.TIER_CHOICE, student["name"] if student else "the student")
        report.warnings.append(
            f"{tier3} is {report.tier3_percent}% of logged hours, above the "
            f"family's {report.tier3_cap_percent}% guideline. These hours still count — "
            "Washington sets no split — but the year is leaning heavily toward electives."
        )
    return report
