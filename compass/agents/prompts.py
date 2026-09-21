"""Shared user-prompt assembly.

The system prompt says who the agent is and what the compliance rules are. The
user prompt says what to teach today. Keeping the split clean means the system
prompt is byte-stable across a session, so it caches.
"""

from __future__ import annotations

from compass.agents.framework import StudentContext, TopicProposal


def build_standard_prompt(
    ctx: StudentContext, proposal: TopicProposal, subject_label: str
) -> str:
    lines = [
        f"Plan the next {subject_label} lesson for {ctx.name}.",
        "",
        "## What to teach",
        proposal.topic,
        "",
        f"Why this, and why now: {proposal.rationale}",
    ]

    if proposal.context_lines:
        lines += ["", "## Context", *[f"- {line}" for line in proposal.context_lines]]

    if proposal.guidance:
        lines += ["", "## How to approach it", proposal.guidance]

    if ctx.parent_note:
        lines += [
            "",
            "## The parent added a note for this specific lesson",
            ctx.parent_note,
            "Treat this as a constraint, not a suggestion.",
        ]

    if ctx.inputs.get("include_fun_extra"):
        lines += [
            "",
            "## Add an optional fun extra",
            "The parent asked for a light, OPTIONAL fun activity this time. Fill "
            "`fun_extra` with a quick, genuinely fun thing tied to today's topic -- a "
            "game, a challenge, a 'try this at home,' a doodle or a would-you-rather. "
            "It's ungraded, has no single right answer, takes about 5-10 minutes, and "
            "he can skip it. Keep it light -- a break, not a third check.",
        ]
    else:
        lines += ["", "Leave `fun_extra` empty (empty strings) -- none was requested."]

    lines += [
        "",
        f"Target length: about {ctx.minutes} minutes of instructional time.",
        "Return the lesson in the required JSON format.",
    ]
    return "\n".join(lines)
