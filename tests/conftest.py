"""Shared test helpers.

`correct_pick` exists because the in-app quiz shuffles answer order per
attempt (compass/agents/quiz.py's `select_questions`) -- the whole point
being that "the answer was the second one" stops being true on a retry.
Tests therefore can't hardcode a radio index; they have to derive the same
selection the app did and read the correct position out of it.
"""

from __future__ import annotations

from typing import Any

from compass.agents.quiz import select_questions


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
