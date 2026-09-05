"""Chunking a topic into a multi-day lesson series.

A parent picks a topic; the generator decides how many days it genuinely
needs and lays out a one-line focus for each. Each day is then written as an
ordinary fixed-shape lesson (Learn -> worked example -> two graded activities
-> quiz) by the subject's own agent -- this module only decides the *shape* of
the series, not the lessons themselves.

Deliberately a cheap, offline-of-web planning call on REVIEW_MODEL: it reasons
over a title and a grade level, it doesn't need the frontier model or web
search. The expensive per-day generation stays on each agent's normal path.
"""

from __future__ import annotations

from compass import config
from compass.agents.llm import _object, generate_lesson

# A topic almost never needs more than a week of school days, and an unbounded
# count is an unbounded pile of expensive per-day generations -- so the planner
# is capped. One day is always valid: a small topic is a single lesson.
MAX_SERIES_DAYS = 8

SERIES_PLAN_SCHEMA = _object(
    {
        "days": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_SERIES_DAYS,
            "description": (
                "The topic split into consecutive day-sized lessons, in teaching "
                "order. Use as many days as the topic genuinely needs and no more: "
                "a small topic is one day; a big one is several. Each day is one "
                "self-contained lesson of the target length."
            ),
            "items": _object(
                {
                    "title": {
                        "type": "string",
                        "description": "A short, specific title for this day's lesson.",
                    },
                    "focus": {
                        "type": "string",
                        "description": (
                            "1-2 sentences naming exactly what THIS day teaches and "
                            "checks -- distinct from every other day, and small enough "
                            "to teach and check in the target time."
                        ),
                    },
                }
            ),
        },
    }
)

SYSTEM_PROMPT = """\
You break a single teaching topic into a short series of day-sized lessons for a \
homeschool student. Given a subject, grade level, a topic, and a per-day time \
budget, decide how many days the topic honestly needs and give each day a title \
and a one-to-two sentence focus.

Rules:
- Use as few days as the topic genuinely needs. A narrow skill is ONE day. Only \
split into more when a single day couldn't teach and check it all at the target \
length. Never pad a topic into more days than it warrants.
- The days must be in teaching order, each building on the ones before it, with \
no overlap -- day 2 must not re-teach day 1.
- Each day must be a complete lesson on its own: something to learn, then practice \
and check, sized to the per-day time budget. Don't make a day that is only review \
or only a test.
- Pitch every day at the given grade level.
"""


def plan_lesson_series(
    *,
    topic: str,
    subject_label: str,
    grade: int | str,
    minutes_per_day: int,
    context: str = "",
    model: str = config.REVIEW_MODEL,
) -> list[dict[str, str]]:
    """Split `topic` into an ordered list of `{"title", "focus"}` days.

    Returns at least one day. The caller (an agent's `generate_series`) writes a
    real fixed-shape lesson for each. On a blank or unusable model response the
    caller falls back to a single day, so this never returns an empty list for a
    non-empty topic.
    """
    parts = [
        f"Subject: {subject_label}",
        f"Grade level: {grade}",
        f"Per-day time budget: about {minutes_per_day} minutes of instruction.",
        "",
        "## Topic to split into a day-by-day series",
        topic,
    ]
    if context.strip():
        parts += ["", "## Context about where this sits", context.strip()]
    parts += ["", "Return the day-by-day plan in the required JSON format."]

    payload = generate_lesson(
        system=SYSTEM_PROMPT,
        user_prompt="\n".join(parts),
        schema=SERIES_PLAN_SCHEMA,
        model=model,
        effort=None,  # REVIEW_MODEL doesn't support the effort parameter at all
        use_web_search=False,
        max_turns=2,
    )
    days: list[dict[str, str]] = []
    for day in payload.get("days") or []:
        focus = (day.get("focus") or "").strip()
        if not focus:
            continue
        days.append({"title": (day.get("title") or "").strip() or focus, "focus": focus})
    return days[:MAX_SERIES_DAYS]
