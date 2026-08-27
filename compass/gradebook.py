"""Reading the database into subject grades.

Kept separate from `compass/grades.py` on purpose: that module is pure
arithmetic with no database and no Streamlit, so the rules (how a retry is
weighted, how a missing component redistributes) can be tested directly.
This one does the querying and hands it over.
"""

from __future__ import annotations

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


def _writing_percent(metadata: dict[str, Any]) -> list[float]:
    """Approved writing counts full; still-in-revision counts partial.

    Deliberately gentler than the quiz rule, and deliberately no penalty for
    the number of drafts: revision is the process working as designed here,
    not a retry at the same measurement. Docking a second draft would teach
    exactly the submit-once-and-never-revise habit this all exists to fix.
    """
    reviews = (metadata.get("writing_review") or {}).values()
    scores = []
    for review in reviews:
        status = review.get("status")
        if status == config.WRITING_APPROVED:
            scores.append(100.0)
        elif status == config.WRITING_NEEDS_REVISION:
            scores.append(70.0)
        # draft / submitted: not judged yet, so not scored yet
    return scores


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

    quiz_percents: list[float] = []
    writing_percents: list[float] = []
    reading_percents: list[float] = []
    assessment_percents: list[float] = []

    for lesson in lessons:
        metadata = lesson.get("metadata") or {}
        # Oldest-first: the retry deduction is by position, so order is the
        # meaning. list_quiz_attempts returns newest-first.
        attempts = list(reversed(db.list_quiz_attempts(student_id, lesson_id=lesson["id"])))
        percent, _ = grades.quiz_score(attempts, deduction, floor, limit)
        if percent is not None:
            quiz_percents.append(percent)

        writing_percents.extend(_writing_percent(metadata))
        reading_percents.extend(_reading_percents(metadata))

        verdict = (metadata.get("assessment_result") or {}).get("verdict")
        if verdict in config.ASSESSMENT_VERDICT_SCORES:
            assessment_percents.append(float(config.ASSESSMENT_VERDICT_SCORES[verdict]))

    return grades.subject_grade(
        agent,
        _weights(db, agent),
        quiz_percents=quiz_percents,
        writing_percents=writing_percents,
        reading_percents=reading_percents,
        mastery_percent=_mastery_percent(db, student_id) if agent == "math" else None,
        assessment_percents=assessment_percents,
    )


def all_subject_grades(db: Any, student_id: int) -> list[grades.SubjectGrade]:
    return [subject_grade(db, student_id, agent) for agent in GRADED_AGENTS]
