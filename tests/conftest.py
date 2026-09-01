"""Shared test helpers.

`correct_pick` exists because the in-app quiz shuffles answer order per
attempt (compass/agents/quiz.py's `select_questions`) -- the whole point
being that "the answer was the second one" stops being true on a retry.
Tests therefore can't hardcode a radio index; they have to derive the same
selection the app did and read the correct position out of it.
"""

from __future__ import annotations

from typing import Any

import pytest

from compass.agents.quiz import select_questions


@pytest.fixture(autouse=True)
def _suppress_first_day_celebration(request, monkeypatch):
    """Keep the "Issue #1" first-day cover out of Home-page AppTest runs.

    render_first_day_celebration fires on the actual first day of the school
    year and st.stop()s the rest of Home so it's the whole page -- exactly
    what it's meant to do. But school_year_bounds() returns "the year
    containing today," so whenever the calendar clock happens to sit on that
    start date (the CI/sandbox box that runs these tests can), the cover
    intercepts every AppTest that opens Home and the real content those tests
    look for never renders. Stubbing it to "already seen" here is the steady
    state every one of those tests actually means to exercise.

    test_ui.py drives the celebration directly (not through Home) and asserts
    its contents, so it opts out and keeps the real function.
    """
    if request.module.__name__ == "test_ui":
        return
    from compass import ui

    monkeypatch.setattr(
        ui, "render_first_day_celebration", lambda db, student: False
    )


def asked_questions(
    pool: list[dict[str, Any]], lesson_id: int, attempt: int = 0
) -> list[dict[str, Any]]:
    """The questions the app will actually ask on `attempt`, in order --
    the same call `render_quiz` makes, with the same seed."""
    return select_questions(pool, attempt, seed=lesson_id)


def correct_pick(
    pool: list[dict[str, Any]], lesson_id: int, question_index: int, attempt: int = 0
) -> int:
    """The radio index that is the right answer for the question shown at
    `question_index` on `attempt`."""
    return asked_questions(pool, lesson_id, attempt)[question_index]["correct_index"]


def wrong_pick(
    pool: list[dict[str, Any]], lesson_id: int, question_index: int, attempt: int = 0
) -> int:
    """Any radio index that is *not* the right answer."""
    right = correct_pick(pool, lesson_id, question_index, attempt)
    return 0 if right != 0 else 1
