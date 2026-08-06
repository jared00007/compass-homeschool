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

    lines += [
        "",
        f"Target length: about {ctx.minutes} minutes of instructional time.",
        "Return the lesson in the required JSON format.",
    ]
    return "\n".join(lines)
