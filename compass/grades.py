"""Turning what Compass already records into an actual grade.

Nothing new is measured here. Quiz attempts, reading checks, math mastery,
writing approvals, and the parent's own assessment band are all already
stored; this decides how they combine.

Two design rules worth keeping:

  * **Show the arithmetic.** A bare "B+" tells a student nothing he can act
    on; "writing 78%, quizzes 92%" tells him exactly what's dragging. Every
    result here carries its components, and the UI renders them.

  * **Effort is not achievement.** Hours logged and the school-day streak
    stay out of the grade entirely. They measure showing up, which the
    streak already rewards on its own terms -- folding them in would quietly
    inflate a B into an A and make the number mean less.

The retry rule is the subtle part. A first attempt counts in full; each
retry is worth less (down to a floor), and the grade takes the **best
weighted** attempt. Best-weighted rather than latest means a careless retry
can never lower a grade, so there is never a reason to avoid trying again --
while an 85% first try still beating a perfect fourth try keeps the
incentive pointed at "think before you submit."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from compass import config

# What each component is called on screen.
COMPONENT_LABELS = {
    "quizzes": "Quizzes",
    "writing": "Writing",
    "reading": "Reading checks",
    "mastery": "Mastery",
    "assessment": "Assessment",
}


@dataclass
class Component:
    """One weighted input to a subject grade."""

    key: str
    percent: float
    weight: int
    detail: str = ""

    @property
    def label(self) -> str:
        return COMPONENT_LABELS.get(self.key, self.key.title())


@dataclass
class SubjectGrade:
    subject: str
    percent: float | None
    components: list[Component] = field(default_factory=list)

    @property
    def letter(self) -> str | None:
        return config.letter_for(self.percent) if self.percent is not None else None

    @property
    def graded(self) -> bool:
        """Whether there was anything to grade at all. A subject he hasn't
        started shows as "not graded yet", never as an F -- an absent grade
        and a failed one are completely different facts."""
        return self.percent is not None


def parse_weights(raw: str) -> dict[str, int]:
    """`"quizzes:45,mastery:35"` -> `{"quizzes": 45, "mastery": 35}`.

    Tolerant of junk: a malformed pair is skipped rather than raising, since
    this comes from an editable setting and a typo shouldn't take down the
    page that shows the grade.
    """
    weights: dict[str, int] = {}
    for chunk in (raw or "").split(","):
        key, _, value = chunk.partition(":")
        key = key.strip()
        if not key or key not in COMPONENT_LABELS:
            continue
        try:
            weights[key] = int(value.strip())
        except ValueError:
            continue
    return weights


def attempt_multiplier(attempt_number: int, deduction: int, floor: int) -> float:
    """What a given attempt's score is worth, 0-1. `attempt_number` is
    1-based, so the first attempt is always worth 1.0."""
    if attempt_number <= 1:
        return 1.0
    value = 100 - deduction * (attempt_number - 1)
    return max(value, floor) / 100


def quiz_score(
    attempts: list[dict[str, Any]], deduction: int, floor: int, graded_limit: int
) -> tuple[float | None, int]:
    """The best weighted score across a lesson's attempts, and how many
    attempts counted.

    `attempts` must be oldest-first -- the deduction is by position, so the
    order is the meaning. Attempts past `graded_limit` are ignored entirely:
    that's where the question pool runs out and the quiz stops being a fresh
    measurement.
    """
    graded = [a for a in attempts if a.get("total")][:graded_limit]
    if not graded:
        return None, 0
    best = max(
        100 * a["correct"] / a["total"] * attempt_multiplier(i, deduction, floor)
        for i, a in enumerate(graded, start=1)
    )
    return best, len(graded)


def can_improve(
    attempts: list[dict[str, Any]], deduction: int, floor: int, graded_limit: int
) -> bool:
    """Whether another attempt could actually raise the banked score.

    False once the attempt limit is hit, or once a perfect next attempt
    would still score below what's already banked. Drives the "practice --
    won't change your grade" label: the retry stays available either way,
    but saying so beats letting him grind at something already earned.
    """
    banked, used = quiz_score(attempts, deduction, floor, graded_limit)
    if used >= graded_limit:
        return False
    if banked is None:
        return True
    ceiling = 100 * attempt_multiplier(used + 1, deduction, floor)
    return ceiling > banked


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def subject_grade(
    subject: str,
    weights: dict[str, int],
    *,
    quiz_percents: list[float],
    writing_percents: list[float],
    reading_percents: list[float],
    mastery_percent: float | None,
    assessment_percents: list[float],
) -> SubjectGrade:
    """One subject's grade from its already-computed component averages.

    A component with no data is dropped and its weight redistributed across
    the rest, rather than counted as a zero -- "hasn't written anything yet"
    must never read as "failed the writing."
    """
    raw = {
        "quizzes": _mean(quiz_percents),
        "writing": _mean(writing_percents),
        "reading": _mean(reading_percents),
        "mastery": mastery_percent,
        "assessment": _mean(assessment_percents),
    }
    counts = {
        "quizzes": len(quiz_percents),
        "writing": len(writing_percents),
        "reading": len(reading_percents),
        "mastery": 1 if mastery_percent is not None else 0,
        "assessment": len(assessment_percents),
    }

    components = [
        Component(
            key=key,
            percent=value,
            weight=weights.get(key, 0),
            detail=(
                f"{counts[key]} graded" if key != "mastery" else "skills mastered"
            ),
        )
        for key, value in raw.items()
        if value is not None and weights.get(key, 0) > 0
    ]
    total_weight = sum(c.weight for c in components)
    if not total_weight:
        return SubjectGrade(subject=subject, percent=None, components=[])

    percent = sum(c.percent * c.weight for c in components) / total_weight
    return SubjectGrade(subject=subject, percent=percent, components=components)
