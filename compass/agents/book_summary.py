"""AI-drafted 2-3 sentence introduction to a book on his reading list --
what it's about, spoiler-light. A parent-triggered draft from the Books tab
of the English page, same as `course_summary`: one on-demand model call,
never automatic, cached on the book row so it's never regenerated just
because the first-day preview (or anything else) happened to render it.
"""

from __future__ import annotations

from typing import Any

from compass import config
from compass.agents.llm import _object, generate_lesson

AGENT_KEY = "book_summary"

SUMMARY_SCHEMA = _object(
    {
        "summary": {
            "type": "string",
            "description": (
                "2-3 sentences introducing the book to the student about to read it -- "
                "what it's about and what makes it worth reading. Spoiler-light: no "
                "ending, no late-book twists."
            ),
        },
    }
)

SYSTEM_PROMPT = """\
You write short, inviting book introductions for a homeschool student's reading \
list -- the kind of thing that makes him want to pick it up, not a book report. \
Given just a title and author, write 2-3 sentences: what the book is about and \
what makes it worth reading. Keep it spoiler-light -- no ending, no late-book \
twists. Plain and specific, not marketing copy.
"""


def generate_book_summary(db: Any, student: dict[str, Any], book: dict[str, Any]) -> str:
    """Draft a summary for `book` and cache it on the row -- a single
    on-demand model call per book, not one per page view. Logged under its
    own agent key purely so the Costs page counts it."""
    user_prompt = f"Title: {book['title']}\nAuthor: {book['author'] or 'unknown'}"
    payload = generate_lesson(
        system=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=SUMMARY_SCHEMA,
        model=config.REVIEW_MODEL,
        effort=config.EFFORT_MEDIUM,
    )
    summary = (payload.get("summary") or "").strip()
    if summary:
        db.update_book(book["id"], ai_summary=summary)
        db.save_lesson(
            student_id=student["id"],
            agent=AGENT_KEY,
            subject="reading",
            topic=book["title"],
            title=f"Book summary — {book['title']}",
            payload=payload,
            strategy="parent_requested",
            rationale="The parent asked for a drafted introduction to this book.",
        )
    return summary
