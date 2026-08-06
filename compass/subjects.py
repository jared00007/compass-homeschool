"""The 11 Washington-required subjects and the multi-subject tagging rules.

Washington requires *instruction* in eleven subjects. It does not prescribe an
hour split between them, so this module's job is two things:

1. Give every subject a single canonical key, so agent output, the activity log,
   and the compliance dashboard all speak the same vocabulary.
2. Describe which secondary subjects each agent's output can plausibly satisfy,
   so one field activity can credit hours to several subjects at once (Tier 2)
   without a human having to remember the mapping.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Subject:
    key: str
    label: str
    description: str


# Order matters only for display. All eleven are required by RCW 28A.225.010.
WA_SUBJECTS: tuple[Subject, ...] = (
    Subject("reading", "Reading", "Decoding, fluency, and comprehension of text."),
    Subject("writing", "Writing", "Composition, mechanics, and revision."),
    Subject("spelling", "Spelling", "Orthography and word construction."),
    Subject("language", "Language", "Grammar, usage, vocabulary, and communication."),
    Subject("math", "Math", "Number, algebra, geometry, and data."),
    Subject("science", "Science", "Life, physical, and earth science; inquiry."),
    Subject(
        "social_studies",
        "Social Studies",
        "Civics, geography, economics, and society.",
    ),
    Subject("history", "History", "Chronological study of people and events."),
    Subject("health", "Health", "Physical, nutritional, and mental wellbeing."),
    Subject(
        "occupational_education",
        "Occupational Education",
        "Career awareness, practical and technical skills.",
    ),
    Subject(
        "art_and_music",
        "Art & Music Appreciation",
        "Visual art, music, and aesthetic response.",
    ),
)

SUBJECT_KEYS: tuple[str, ...] = tuple(s.key for s in WA_SUBJECTS)
SUBJECTS_BY_KEY: dict[str, Subject] = {s.key: s for s in WA_SUBJECTS}


def label(key: str) -> str:
    """Human-readable label for a subject key, falling back to the raw key."""
    subject = SUBJECTS_BY_KEY.get(key)
    return subject.label if subject else key.replace("_", " ").title()


def is_valid(key: str) -> bool:
    return key in SUBJECTS_BY_KEY


# --- Tier 2 folding ----------------------------------------------------------
# Which secondary subjects each Tier 1 agent is allowed to claim credit for.
# The agent still has to justify the credit with a real activity component —
# this just bounds what it may claim, so a Math lesson can't quietly bill itself
# as art appreciation.

FOLDABLE_SUBJECTS: dict[str, tuple[str, ...]] = {
    "math": ("reading", "language", "occupational_education", "science"),
    "science": (
        "reading",
        "writing",
        "language",
        "math",
        "art_and_music",
        "health",
        "occupational_education",
    ),
    "english": ("reading", "writing", "spelling", "language", "art_and_music", "history"),
    "history": (
        "social_studies",
        "reading",
        "writing",
        "language",
        "art_and_music",
        "occupational_education",
    ),
}

# Subjects that are explicitly NOT satisfied by agent output. Health and
# occupational education can be *folded in* opportunistically (a field activity
# involving cooking or trail safety genuinely counts), but the family's primary
# coverage for them comes from the Core Life Skills checklist, not an agent.
NON_AGENTIC_SUBJECTS: tuple[str, ...] = ("health", "occupational_education")


def allowed_credit_subjects(agent_key: str, primary_subject: str) -> tuple[str, ...]:
    """Subjects an agent may credit hours to, primary first."""
    secondary = FOLDABLE_SUBJECTS.get(agent_key, ())
    ordered = [primary_subject] + [s for s in secondary if s != primary_subject]
    return tuple(s for s in ordered if is_valid(s))
