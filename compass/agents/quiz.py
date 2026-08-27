"""Server-side handling for the in-app, auto-graded quiz.

Three separate concerns live here:

  * `verify_quiz` -- the model's JSON schema enforces types, not invariants
    across fields. Nothing stops it from returning `correct_index: 4` for a
    four-choice question, or three choices instead of four. A bad question
    like that doesn't just look wrong, it silently breaks grading (a correct
    answer that can never be selected), so this drops anything malformed
    before a quiz ever reaches the student.

  * `select_questions` -- a lesson carries a pool of ~20 questions but only
    a handful are asked at a time, rotating so a retry is a genuinely
    different quiz rather than the same five questions with the answers
    already memorized.

  * `grade` / `passed` -- pure functions with no Streamlit dependency, so the
    scoring logic that decides whether a skill gets marked mastered can be
    tested directly rather than through a simulated form submission.
"""

from __future__ import annotations

import random
from typing import Any

CHOICE_COUNT = 4

# How many of the pool get asked in any one sitting. A pool of 20 at 5 a
# time means four straight retries before a question can repeat -- long
# enough that re-taking is real recall, not pattern matching on a screen he
# just saw.
QUESTIONS_PER_ATTEMPT = 5


def verify_quiz(payload: dict[str, Any]) -> list[str]:
    """Drop any question that isn't well-formed and answerable. Returns warnings."""
    raw = payload.get("quiz")
    if not isinstance(raw, list):
        payload["quiz"] = []
        return []

    warnings: list[str] = []
    kept: list[dict[str, Any]] = []
    for item in raw:
        verified = _well_formed(item)
        if verified is None:
            text = item.get("question") if isinstance(item, dict) else None
            warnings.append(f"Dropped a malformed quiz question: {text or '(no text)'}")
            continue
        kept.append(verified)

    payload["quiz"] = kept
    return warnings


def _well_formed(item: Any) -> dict[str, Any] | None:
    """One question, normalized, or None if it isn't answerable.

    The JSON schema enforces types but not invariants across fields --
    nothing stops `correct_index: 4` on a four-choice question, which is a
    correct answer that can never be selected.
    """
    if not isinstance(item, dict):
        return None
    question = (item.get("question") or "").strip()
    choices = item.get("choices")
    correct_index = item.get("correct_index")
    if (
        not question
        or not isinstance(choices, list)
        or len(choices) != CHOICE_COUNT
        or any(not isinstance(c, str) or not c.strip() for c in choices)
        or not isinstance(correct_index, int)
        or isinstance(correct_index, bool)
        or not (0 <= correct_index < CHOICE_COUNT)
    ):
        return None
    return {
        "question": question,
        "choices": [c.strip() for c in choices],
        "correct_index": correct_index,
        "explanation": (item.get("explanation") or "").strip(),
    }


def verify_reading_checks(payload: dict[str, Any]) -> list[str]:
    """Drop any malformed reading-check question, per activity.

    Same reasoning as `verify_quiz`, but these are graded against a book
    the model is recalling rather than content it just wrote, so a
    half-formed question here is if anything more likely.
    """
    warnings: list[str] = []
    for activity in payload.get("activities") or []:
        if not isinstance(activity, dict):
            continue
        raw = activity.get("reading_check")
        if not isinstance(raw, list):
            activity["reading_check"] = []
            continue
        kept = []
        for item in raw:
            verified = _well_formed(item)
            if verified is None:
                warnings.append(
                    "Dropped a malformed reading-check question in "
                    f"{activity.get('title', 'an activity')}."
                )
                continue
            kept.append(verified)
        activity["reading_check"] = kept
    return warnings


def _shuffled_choices(item: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """One question with its answers reordered, `correct_index` moved to
    match. Without this a retry still shows "the answer was the third one"
    even when the questions themselves have rotated."""
    order = list(range(len(item["choices"])))
    rng.shuffle(order)
    return {
        **item,
        "choices": [item["choices"][i] for i in order],
        "correct_index": order.index(item["correct_index"]),
    }


def select_questions(
    quiz: list[dict[str, Any]], attempt: int, seed: int = 0
) -> list[dict[str, Any]]:
    """The questions to ask on attempt number `attempt` (0-based).

    Walks a contiguous window through the pool -- attempt 0 takes the first
    `QUESTIONS_PER_ATTEMPT`, attempt 1 the next, wrapping when it runs off
    the end -- so consecutive retries are guaranteed not to repeat a
    question until the whole pool has been used, which random sampling
    would not give. Question order within the window, and the answer order
    inside each question, are then shuffled.

    Deterministic in `(attempt, seed)`: Streamlit re-runs the render
    function on every interaction, so an unseeded shuffle would deal a
    different quiz on every click. Pass the lesson id as `seed` so two
    lessons don't rotate in lockstep.

    A pool smaller than the window (every lesson generated before the pool
    existed has 3-5 questions) just returns all of it, still shuffled.
    """
    if not quiz:
        return []
    # A single int, not a tuple -- random.Random rejects tuple seeds. The
    # multiplier just keeps two lessons from dealing identical orders.
    rng = random.Random(seed * 1_000_003 + attempt)
    window = min(QUESTIONS_PER_ATTEMPT, len(quiz))
    start = (attempt * window) % len(quiz)
    picked = [quiz[(start + offset) % len(quiz)] for offset in range(window)]
    rng.shuffle(picked)
    return [_shuffled_choices(item, rng) for item in picked]


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
