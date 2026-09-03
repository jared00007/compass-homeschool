"""Pull an assignment's discrete asks out of its own instructions, so a
parent can add the self-check gate (see ui's writing checklist) to a lesson
that was generated before checklists existed -- without rewriting it or
regenerating the day.

Deliberately small: it reads one activity's `instructions` and returns the
separate things the student has to do, one short line each. The parent sees
the result and edits or confirms it before it goes live -- this never writes
to a lesson on its own. Runs on `config.REVIEW_MODEL` (cheap), same as the
writing reviewer.
"""

from __future__ import annotations

from compass import config
from compass.agents.llm import _object, generate_lesson

SUGGEST_SCHEMA = _object(
    {
        "checklist": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Each distinct thing the instructions require, one short "
                "second-person line ('Answer all three questions', 'Give an "
                "example from the reading', 'Show your steps'). Only genuinely "
                "separate requirements he could forget and skip -- never a "
                "restatement of the whole task, never padding. Empty if the "
                "instructions really ask for only one thing."
            ),
        }
    }
)

SYSTEM_PROMPT = """\
You break a homeschool writing assignment into the separate parts a student \
has to complete, so he can tick each one off and can't hand in only half.

You are given the assignment's instructions. Return each distinct requirement \
as one short line written to the student in second person. Split on real, \
separate asks -- a multi-part question, "do X and then Y", "explain Z and give \
an example". Do NOT split a single instruction into artificial pieces, do NOT \
restate the whole task as one item, and do NOT invent requirements the \
instructions don't state. If the assignment genuinely asks for only one thing, \
return an empty list.
"""


def suggest_checklist(instructions: str) -> list[str]:
    """The discrete asks found in `instructions`, for the parent to confirm
    or edit. Blank instructions (or a one-ask assignment) return an empty
    list. Never writes anything -- the caller decides what to save."""
    instructions = (instructions or "").strip()
    if not instructions:
        return []
    payload = generate_lesson(
        system=SYSTEM_PROMPT,
        user_prompt=f"THE ASSIGNMENT INSTRUCTIONS:\n{instructions}",
        schema=SUGGEST_SCHEMA,
        model=config.REVIEW_MODEL,
        effort=None,
    )
    items = payload.get("checklist") or []
    return [str(item).strip() for item in items if str(item).strip()]
