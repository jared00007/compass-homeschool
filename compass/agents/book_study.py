"""Book study -- a structured book report and an optional comprehension quiz over
the book Landon is reading.

Two deliberately different things:

- **The report** is his first ever, so it's a FIXED, teachable scaffold, not an
  AI generation: a set of sections, each with a plain "what to write here," a
  sentence starter, and a rough length, plus a parent rubric. It's built as an
  ordinary lesson whose activities are those sections, so he writes into it and a
  parent grades it through the exact same writing + review pipeline every other
  lesson uses. No model call -- the value is the structure, and it's free and
  identical every time.

- **The quiz** IS an AI generation: a comprehension check over the specific book,
  auto-graded like any lesson quiz. One on-demand call, costed like every other
  agent.

Both are parent-triggered from the English page's Books tab, over the book that's
currently being read.
"""

from __future__ import annotations

from typing import Any

from compass import config
from compass.agents.llm import _object, generate_lesson
from compass.agents.quiz import verify_quiz

AGENT_KEY_REPORT = "book_report"
AGENT_KEY_QUIZ = "book_quiz"


# --- the report: a fixed scaffold, taught section by section --------------------

# Each section becomes one writing activity. `instructions` is written to him and
# carries the whole teaching load: what this part is for, a sentence starter to
# get unstuck, and roughly how long. Kept deliberately concrete for a first-timer.
REPORT_SECTIONS: tuple[dict[str, Any], ...] = (
    {
        "title": "1. The book & why you picked it",
        "minutes": 5,
        "instructions": (
            "Start with the basics: the title, the author, and what kind of book it is "
            "(adventure, mystery, fantasy, true story…). Then say in a sentence or two "
            "why you chose it or what made you want to read it.\n\n"
            "Try starting with: \"The book I read is ___ by ___. It's a ___ story, and "
            "I picked it because ___.\""
        ),
    },
    {
        "title": "2. What it's about",
        "minutes": 12,
        "instructions": (
            "Give a short summary of what happens -- 3 to 5 sentences, in your OWN words. "
            "Cover the beginning and the main problem the story is about. Don't give away "
            "the ending; leave that for someone who reads it.\n\n"
            "Try starting with: \"The story is about ___. At the start, ___. The big "
            "problem is ___.\""
        ),
    },
    {
        "title": "3. The main characters",
        "minutes": 8,
        "instructions": (
            "Introduce the one or two most important characters. Who are they, and what "
            "are they like? Give an example of something they do that shows what kind of "
            "person they are.\n\n"
            "Try starting with: \"The main character is ___. They are ___. For example, "
            "___.\""
        ),
    },
    {
        "title": "4. Where and when it happens",
        "minutes": 5,
        "instructions": (
            "Describe the setting -- where the story takes place and when. Then say one "
            "way the setting matters to the story (how it changes what can happen).\n\n"
            "Try starting with: \"The story takes place in ___. This matters because ___.\""
        ),
    },
    {
        "title": "5. Your favorite part",
        "minutes": 8,
        "instructions": (
            "Pick one moment you liked best. Say what happened, then -- most importantly "
            "-- WHY it stuck with you. This is your opinion, so there's no wrong answer, "
            "but back it up.\n\n"
            "Try starting with: \"My favorite part was when ___. I liked it because ___.\""
        ),
    },
    {
        "title": "6. What you thought & who should read it",
        "minutes": 7,
        "instructions": (
            "Wrap up: did you enjoy the book, and would you recommend it? Say who you "
            "think would like it and why. Give it a rating out of 5 stars if you want.\n\n"
            "Try starting with: \"Overall, I thought this book was ___. I'd recommend it "
            "to ___ because ___.\""
        ),
    },
)

# What a good report looks like, for the parent grading it -- shown in the review
# card's parent notes, not to him.
REPORT_RUBRIC = (
    "First book report -- grade for effort and structure, not polish. Look for: "
    "each section attempted in his own words (not copied); the summary covers the "
    "start and the main problem without spoiling the ending; the favorite-part and "
    "recommendation sections give a REASON, not just \"it was good.\" Nudge on one "
    "thing at a time -- this is a skill he's building, so celebrate a genuine "
    "attempt and send back only what's clearly incomplete."
)

REPORT_OVERVIEW = (
    "A book report is you telling someone about a book you read -- what it's about, "
    "who's in it, and what you thought. This is your first one, so it's broken into "
    "small parts. Do them in order, write in your own words (a few sentences each is "
    "plenty), and use an example from the book wherever you can. Take your time -- "
    "there's no rush to finish it in one sitting."
)


def build_book_report(db: Any, student: dict[str, Any], book: dict[str, Any]) -> int:
    """Create a book-report assignment for `book` and return its lesson id.

    A fixed scaffold, not a model call: the sections are the same every time, so
    he learns one repeatable shape. Stored as a `book_report` lesson whose
    activities are the sections, so it flows through the ordinary writing +
    parent-review pipeline. Carries an all-zero `_usage` so the Costs page prices
    it (correctly, at $0 -- there's no API call) rather than lumping it in with
    legacy un-tracked lessons.
    """
    title = book.get("title") or "your book"
    author = book.get("author") or ""
    byline = f" by {author}" if author else ""
    activities = [dict(section, requires_written_response=True) for section in REPORT_SECTIONS]
    payload = {
        "title": f"Book report — {title}",
        "overview": (
            f"{REPORT_OVERVIEW}\n\nYou're writing about **{title}**{byline}."
        ),
        "learning_objectives": [
            "Summarize a book in your own words without spoiling the ending",
            "Describe characters and setting with examples from the text",
            "Give and support an opinion about what you read",
        ],
        "activities": activities,
        "parent_notes": REPORT_RUBRIC,
        # Rough plan-time credit split for a writing assignment; the parent still
        # sets the real hours when they approve it, same as any lesson.
        "subject_credits": [
            {"subject": "writing", "minutes": 30, "justification": "Composing the report."},
            {"subject": "reading", "minutes": 15, "justification": "Recalling the book."},
        ],
        "estimated_minutes": sum(s["minutes"] for s in REPORT_SECTIONS),
        # No API call was made, but record zero usage so the Costs page prices it
        # at $0 rather than counting it among legacy, un-priced lessons.
        "_usage": {
            "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0, "web_searches": 0, "model": config.DEFAULT_MODEL,
        },
    }
    return db.save_lesson(
        student_id=student["id"],
        agent=AGENT_KEY_REPORT,
        subject="writing",
        topic="Book report",
        title=f"📖 Book report — {title}",
        payload=payload,
        strategy="parent_requested",
        rationale="The parent assigned a structured book report over the current book.",
        metadata={"book_report": True, "book_id": book.get("id")},
    )


# --- the quiz: an AI comprehension check over the book -------------------------

QUIZ_SCHEMA = _object(
    {
        "overview": {
            "type": "string",
            "description": (
                "One or two warm sentences to the student introducing this quiz -- that "
                "it checks how well he followed the book. Written to a 13-year-old."
            ),
        },
        "quiz": {
            "type": "array",
            "description": (
                "A pool of {min}-{max} multiple-choice comprehension questions about THIS "
                "book -- plot, characters, setting, and what things mean. He's asked five "
                "at a time, rotated on retry, so give it breadth across the whole book at "
                "a mix of difficulties. Exactly four choices each, one clearly correct."
            ).format(min=config.BOOK_QUIZ_POOL_MIN, max=config.BOOK_QUIZ_POOL_MAX),
            "items": _object(
                {
                    "question": {"type": "string"},
                    "choices": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Exactly four answer choices, one correct and three plausible.",
                    },
                    "correct_index": {
                        "type": "integer",
                        "description": "0-based index into `choices` of the correct answer.",
                    },
                    "explanation": {
                        "type": "string",
                        "description": "One sentence on why that answer is correct, shown after he answers.",
                    },
                }
            ),
        },
    }
)

QUIZ_SYSTEM_PROMPT = """\
You write a reading-comprehension quiz for Compass, a family's homeschool app, \
for a {age}-year-old {grade}th grader named {name}. The quiz is over one book he \
has read; check whether he understood it -- plot, characters, setting, and what \
events mean -- not trivia only a re-read would catch.

Write to him plainly and fairly. Since this is a check after reading, questions \
may cover the whole book including the ending. Every question must have exactly \
four choices with one clearly correct answer and three plausible distractors. If \
you are not confident about a specific detail of this book, ask about it at a \
level you ARE sure of (major characters, central conflict, overall outcome) \
rather than inventing specifics.

## The book
- Title: {title}
- Author: {author}
- Reading level: {level}
"""


def generate_book_quiz(db: Any, student: dict[str, Any], book: dict[str, Any]) -> int:
    """Draft a comprehension quiz over `book`, persist it as a `book_quiz` lesson,
    and return its id. One on-demand model call, logged for cost tracking. The
    quiz is auto-graded like any lesson quiz; it carries no writing, so it never
    needs a parent grading step."""
    system = QUIZ_SYSTEM_PROMPT.format(
        age=student.get("age") or 13,
        grade=student.get("grade") or "8",
        name=student.get("name") or "the student",
        title=book.get("title") or "the book",
        author=book.get("author") or "unknown",
        level=book.get("reading_level") or "grade 8",
        min=config.BOOK_QUIZ_POOL_MIN,
        max=config.BOOK_QUIZ_POOL_MAX,
    )
    payload = generate_lesson(
        system=system,
        user_prompt="Write the comprehension quiz now. Return the overview and quiz pool only.",
        schema=QUIZ_SCHEMA,
        effort=config.DEFAULT_EFFORT,
    )
    verify_quiz(payload)
    title = book.get("title") or "your book"
    # Shape as an ordinary (quiz-only) lesson so it renders through the standard
    # lesson UI. No learn/activities -- just the overview and the quiz.
    payload["title"] = f"Book quiz — {title}"
    payload["overview"] = payload.get("overview") or ""
    payload["learning_objectives"] = [f"Show you understood {title}"]
    payload["activities"] = []
    return db.save_lesson(
        student_id=student["id"],
        agent=AGENT_KEY_QUIZ,
        subject="reading",
        topic="Book comprehension quiz",
        title=f"📚 Book quiz — {title}",
        payload=payload,
        strategy="parent_requested",
        rationale="The parent asked for a comprehension quiz over the current book.",
        metadata={"book_quiz": True, "book_id": book.get("id")},
    )
