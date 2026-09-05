"""Reading the database into subject grades.

Kept separate from `compass/grades.py` on purpose: that module is pure
arithmetic with no database and no Streamlit, so the rules (how a retry is
weighted, how a missing component redistributes) can be tested directly.
This one does the querying and hands it over.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from compass import config, grades
from compass.curriculum import math_graph

# The four Tier 1 subjects that carry a grade. Life skills, choice topics,
# and Big Projects deliberately don't -- they're chosen, not assigned, and
# grading them would turn the part of the week he actually owns into more
# of the part he doesn't.
GRADED_AGENTS = ("math", "science", "english", "history")

AGENT_LABELS = {
    "math": "Math",
    "science": "Science",
    "english": "English",
    "history": "History",
}


def _weights(db: Any, agent: str) -> dict[str, int]:
    return grades.parse_weights(db.get_setting(f"grade_weights_{agent}") or "")


def _reading_percents(metadata: dict[str, Any]) -> list[float]:
    return [
        100 * check["correct"] / check["total"]
        for check in (metadata.get("reading_checks") or {}).values()
        if check.get("total")
    ]


def _mastery_percent(db: Any, student_id: int) -> float | None:
    """Share of the math skills he's actually attempted that reached
    mastery. Against attempted, not against the whole graph -- grading him
    on skills the curriculum hasn't reached yet would mean starting the year
    at 0%."""
    mastery = db.mastery_map(student_id)
    attempted = [
        row for skill_id, row in mastery.items() if skill_id in math_graph.MATH_GRAPH
    ]
    if not attempted:
        return None
    mastered = sum(1 for row in attempted if row["status"] == "mastered")
    return 100 * mastered / len(attempted)


def subject_grade(db: Any, student_id: int, agent: str) -> grades.SubjectGrade:
    """One subject's grade, read straight out of what's already recorded."""
    deduction = db.get_int_setting("quiz_retry_deduction_percent")
    floor = db.get_int_setting("quiz_retry_floor_percent")
    limit = config.GRADED_QUIZ_ATTEMPTS

    lessons = [
        lesson
        for lesson in db.list_lessons(student_id, agent=agent, limit=500)
        if lesson["status"] != "skipped"
    ]

    # Two graded surfaces. `quiz_percents` carries both the auto quiz and the
    # auto reading checks -- they're the same kind of objective, self-graded
    # check, so they share one component the parent sees as "Quiz". Writing is
    # deliberately NOT its own component any more: its quality is judged when the
    # parent grades the hand-in (`assessment`). The write -> review -> revise
    # coaching loop still runs untouched; it just informs the hand-in rather
    # than scoring a separate lane.
    quiz_percents: list[float] = []
    assessment_percents: list[float] = []

    for lesson in lessons:
        metadata = lesson.get("metadata") or {}
        # Oldest-first: the retry deduction is by position, so order is the
        # meaning. list_quiz_attempts returns newest-first.
        attempts = list(reversed(db.list_quiz_attempts(student_id, lesson_id=lesson["id"])))
        percent, _ = grades.quiz_score(attempts, deduction, floor, limit)
        if percent is not None:
            quiz_percents.append(percent)

        # Reading checks fold in with the quiz -- both auto-graded objective checks.
        quiz_percents.extend(_reading_percents(metadata))

        verdict = (metadata.get("assessment_result") or {}).get("verdict")
        if verdict in config.ASSESSMENT_VERDICT_SCORES:
            assessment_percents.append(float(config.ASSESSMENT_VERDICT_SCORES[verdict]))

    grade = grades.subject_grade(
        agent,
        _weights(db, agent),
        quiz_percents=quiz_percents,
        mastery_percent=_mastery_percent(db, student_id) if agent == "math" else None,
        assessment_percents=assessment_percents,
    )
    return _apply_override(db, agent, grade)


def _apply_override(db: Any, agent: str, grade: grades.SubjectGrade) -> grades.SubjectGrade:
    """Let a parent's hand-set grade win over the computed one.

    Read from the `grade_override_<agent>` setting (a plain percent) plus an
    optional `grade_override_note_<agent>`. The computed components stay on the
    grade untouched, so the report card can still show what the math *would*
    have produced next to the number the parent chose. An empty or unparseable
    setting is simply no override -- the computed grade passes straight
    through, same tolerance `grades.parse_weights` already applies to settings."""
    raw = db.get_setting(f"grade_override_{agent}")
    if not raw:
        return grade
    try:
        percent = float(raw)
    except (TypeError, ValueError):
        return grade
    grade.percent = max(0.0, min(100.0, percent))
    grade.overridden = True
    grade.override_note = db.get_setting(f"grade_override_note_{agent}") or ""
    return grade


def set_override(db: Any, agent: str, percent: float | None, note: str = "") -> None:
    """Store (or clear, with percent=None) a parent's hand-set grade for one
    subject. Clearing removes both the percent and its note so the computed
    grade takes back over cleanly."""
    if percent is None:
        db.set_setting(f"grade_override_{agent}", "")
        db.set_setting(f"grade_override_note_{agent}", "")
        return
    db.set_setting(f"grade_override_{agent}", str(round(float(percent), 1)))
    db.set_setting(f"grade_override_note_{agent}", note.strip())


def all_subject_grades(db: Any, student_id: int) -> list[grades.SubjectGrade]:
    return [subject_grade(db, student_id, agent) for agent in GRADED_AGENTS]


@dataclass
class GradedItem:
    """One individual thing that fed a subject grade -- a single quiz, a
    reading check, a hand-in verdict, or a math skill. The component averages
    on the report card are built from these, but a parent asking "why is his
    grade bad" needs to see the items themselves, worst first, not just the
    rolled-up average that hides which two quizzes tanked it."""

    component: str   # "quizzes" | "assessment" | "mastery" -- matches Component.key
    title: str       # the lesson it came from, or the skill's name
    percent: float   # 0-100; for mastery, 100 mastered / 0 not yet
    detail: str      # "best of 2 attempts", "reading check", the verdict, the status
    # What a parent needs to *edit* this item's grade, when it's editable:
    # `lesson_id` + `verdict` for a hand-in (re-graded via record_assessment),
    # `skill_id` for a math skill (re-set via set_mastery). Quizzes and reading
    # checks are auto-graded off his actual answers, so they carry neither --
    # the way to change one is to have him retake it, not to hand-edit a score.
    lesson_id: int | None = None
    skill_id: str | None = None
    verdict: str | None = None

    @property
    def component_label(self) -> str:
        return grades.COMPONENT_LABELS.get(self.component, self.component.title())

    @property
    def editable(self) -> bool:
        """A hand-in verdict or a math skill -- the parent-judged items, the
        ones a parent can legitimately override. An auto-graded quiz/reading
        check is not."""
        return (self.component == "assessment" and self.lesson_id is not None) or (
            self.component == "mastery" and self.skill_id is not None
        )


def graded_items(db: Any, student_id: int, agent: str) -> list[GradedItem]:
    """Every individual graded item behind a subject's grade, worst score
    first -- the drill-down under the component averages. Reads exactly the
    same records `subject_grade` averages, so an item shown here is one that
    actually counted (a skipped lesson, an ungraded hand-in, an untaken quiz
    never appears). Sorted lowest-percent-first so the reason a grade is low
    is the first thing a parent reads, not something to hunt for."""
    deduction = db.get_int_setting("quiz_retry_deduction_percent")
    floor = db.get_int_setting("quiz_retry_floor_percent")
    limit = config.GRADED_QUIZ_ATTEMPTS

    lessons = [
        lesson
        for lesson in db.list_lessons(student_id, agent=agent, limit=500)
        if lesson["status"] != "skipped"
    ]

    items: list[GradedItem] = []
    for lesson in lessons:
        metadata = lesson.get("metadata") or {}
        title = lesson.get("title") or lesson.get("topic") or "a lesson"

        attempts = list(reversed(db.list_quiz_attempts(student_id, lesson_id=lesson["id"])))
        percent, used = grades.quiz_score(attempts, deduction, floor, limit)
        if percent is not None:
            detail = "best score" if used == 1 else f"best of {used} attempts"
            items.append(GradedItem("quizzes", title, percent, detail))

        for check in (metadata.get("reading_checks") or {}).values():
            if check.get("total"):
                pct = 100 * check["correct"] / check["total"]
                items.append(
                    GradedItem(
                        "quizzes", title, pct,
                        f"reading check · {check['correct']}/{check['total']}",
                    )
                )

        verdict = (metadata.get("assessment_result") or {}).get("verdict")
        if verdict in config.ASSESSMENT_VERDICT_SCORES:
            items.append(
                GradedItem(
                    "assessment", title,
                    float(config.ASSESSMENT_VERDICT_SCORES[verdict]),
                    f"hand-in · {verdict}",
                    lesson_id=lesson["id"],
                    verdict=verdict,
                )
            )

    # Math mastery is per-skill, not per-lesson -- each attempted skill is its
    # own line so a parent can see exactly which ones haven't landed yet.
    if agent == "math":
        mastery = db.mastery_map(student_id)
        for skill_id, row in mastery.items():
            skill = math_graph.MATH_GRAPH.get(skill_id)
            if skill is None:
                continue
            mastered = row["status"] == "mastered"
            items.append(
                GradedItem(
                    "mastery",
                    skill.title,
                    100.0 if mastered else 0.0,
                    "mastered" if mastered else f"{row['status']} — not yet mastered",
                    skill_id=skill_id,
                )
            )

    items.sort(key=lambda i: i.percent)
    return items
