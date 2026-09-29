"""Lightning lessons -- one short, focused mini-lesson on a topic the parent
names, the quick companion to a Khan skill.

Khan carries the depth and the drill; a lightning lesson is Compass giving a
fast Learn + one worked example + a quick check on a single idea, so the parent
can wrap a bite-sized Compass lesson around whatever Landon is doing on Khan.

It reuses the subject agent's normal writer, so a lightning lesson is a real,
fixed-shape lesson that renders, quizzes, and grades like any other -- it just
tells the writer to keep it short and teach only this one topic, and folds in
the parent's own editable instructions. Like every generated lesson, it lands
in the parent's Backlog (held_back) to schedule by day.
"""

from __future__ import annotations

from typing import Any

from compass.agents import get_agent
from compass.agents.framework import GeneratedLesson, StudentContext, TopicProposal

# The subjects that have a lesson-writing agent behind them.
LIGHTNING_AGENTS: tuple[str, ...] = ("math", "science", "english", "history")

# The fixed directive that makes a lesson "lightning" -- prepended to whatever
# the parent types so the writer keeps it small and single-topic.
LIGHTNING_GUIDANCE = (
    "Keep this LIGHTNING SHORT: a single focused mini-lesson a student can do in "
    "about 10-15 minutes. Teach ONLY the one topic named above -- a brief Learn "
    "(a few sentences, not a wall of text), one clear worked example, and keep the "
    "graded activities quick and to the point. This is a fast companion to his "
    "Khan Academy practice, not a full multi-day build."
)

# The editable prompt the panel opens with -- a sensible default the parent can
# alter per generation ("adjust what it's about").
DEFAULT_INSTRUCTIONS = (
    "Keep it short and focused for an 8th grader. Plain, encouraging language, one "
    "clear worked example, and a couple of quick practice questions."
)

# Which lesson-writing agent a Khan card's WA subject spins off through. The four
# graded agents cover these; a Khan card in a subject not listed here (health,
# art & music, occupational ed) has no writer to spin off from.
_SUBJECT_TO_AGENT = {
    "math": "math",
    "science": "science",
    "reading": "english", "writing": "english", "spelling": "english", "language": "english",
    "history": "history", "social_studies": "history",
}


def agent_for_subject(subject: str) -> str | None:
    """The lesson agent that can write a spin-off for a Khan card in `subject`,
    or None when the subject has no writer (health, art & music, ...)."""
    return _SUBJECT_TO_AGENT.get(subject)


def spinoff_seed_prompt(skill: str) -> str:
    """The editable prompt a Khan spin-off opens with -- seeded from the skill so
    the companion lesson teaches exactly what he just practiced on Khan."""
    skill = (skill or "the skill").strip()
    return (
        f"A companion to the Khan Academy skill “{skill}” he just practiced. "
        "Teach it in Compass's own voice for an 8th grader: a brief clear explanation, "
        "one worked example, and a couple of quick practice questions that go a little "
        "deeper than rote drill."
    )


def generate_lightning_lesson(
    db: Any,
    student: dict[str, Any],
    agent_key: str,
    *,
    topic: str,
    instructions: str = "",
    minutes: int = 15,
    link: dict[str, Any] | None = None,
) -> GeneratedLesson:
    """Write one short lesson on `topic` in `agent_key`'s subject, using the
    parent's editable `instructions`. Lands in the Backlog like any generated
    lesson. `link`, when given, is stored on the lesson's metadata (used to record
    that a lesson was spun off from a Khan skill). Raises ValueError for an unknown
    subject or an empty topic."""
    if agent_key not in LIGHTNING_AGENTS:
        raise ValueError(f"'{agent_key}' isn't a lightning-lesson subject.")
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("Give the lightning lesson a topic.")

    agent = get_agent(agent_key)
    instructions = (instructions or "").strip()
    ctx = StudentContext(
        db=db, student_id=student["id"], student=student,
        inputs={"minutes": minutes, "parent_note": instructions},
    )
    guidance = LIGHTNING_GUIDANCE
    if instructions:
        guidance += "\n\nParent's instructions for this one: " + instructions
    metadata: dict[str, Any] = {"lightning": True}
    if link:
        metadata["spun_off_from"] = dict(link)
    proposal = TopicProposal(
        topic=topic,
        rationale="Parent asked for a quick lightning lesson on this topic.",
        strategy="parent_lightning",
        guidance=guidance,
        metadata=metadata,
    )
    # target_days=1 skips the multi-day planner and writes the whole topic as one
    # short lesson.
    return agent.generate_series(ctx, proposal, target_days=1)[0]
