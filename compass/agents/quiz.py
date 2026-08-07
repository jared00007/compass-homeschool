"""Server-side handling for the in-app, auto-graded quiz.

Two separate concerns live here:

  * `verify_quiz` -- the model's JSON schema enforces types, not invariants
    across fields. Nothing stops it from returning `correct_index: 4` for a
    four-choice question, or three choices instead of four. A bad question
    like that doesn't just look wrong, it silently breaks grading (a correct
    answer that can never be selected), so this drops anything malformed
    before a quiz ever reaches the student.

  * `grade` / `passed` -- pure functions with no Streamlit dependency, so the
    scoring logic that decides whether a skill gets marked mastered can be
    tested directly rather than through a simulated form submission.
"""

from __future__ import annotations

from typing import Any

CHOICE_COUNT = 4


def verify_quiz(payload: dict[str, Any]) -> list[str]:
    """Drop any question that isn't well-formed and answerable. Returns warnings."""
    raw = payload.get("quiz")
    if not isinstance(raw, list):
        payload["quiz"] = []
        return []

    warnings: list[str] = []
    kept: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        question = (item.get("question") or "").strip()
        choices = item.get("choices")
        correct_index = item.get("correct_index")

        malformed = (
            not question
            or not isinstance(choices, list)
            or len(choices) != CHOICE_COUNT
            or any(not isinstance(c, str) or not c.strip() for c in choices)
            or not isinstance(correct_index, int)
            or isinstance(correct_index, bool)
            or not (0 <= correct_index < CHOICE_COUNT)
        )
        if malformed:
            warnings.append(f"Dropped a malformed quiz question: {question or '(no text)'}")
            continue

        kept.append(
            {
                "question": question,
                "choices": [c.strip() for c in choices],
                "correct_index": correct_index,
                "explanation": (item.get("explanation") or "").strip(),
            }
        )

    payload["quiz"] = kept
    return warnings


def grade(quiz: list[dict[str, Any]], picks: list[int | None]) -> tuple[int, int]:
    """(correct_count, total) for a set of picks against a verified quiz."""
    correct = sum(
        1 for item, pick in zip(quiz, picks) if pick is not None and pick == item["correct_index"]
    )
    return correct, len(quiz)


def passed(correct: int, total: int, threshold_percent: int) -> bool:
    if total == 0:
        return False
    return (100 * correct / total) >= threshold_percent
