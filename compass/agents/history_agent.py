"""History / Social Studies Agent — timeline-driven, location-aware.

Same spiderweb mechanics as Science for the branch pool, but the *selection* rule
is different: coverage across a fixed timeline of eras, with a standing override
for wherever the family physically is.
"""

from __future__ import annotations

from typing import Any

from compass.agents.framework import AgentSpec, LessonAgent, StudentContext, TopicProposal
from compass.agents.prompts import build_standard_prompt
from compass.agents.strategies import record_spiderweb_result, timeline

GUIDANCE = """\
History and social studies are one agent here, because at 8th grade they are one \
subject: events in order, and the civic and geographic systems those events \
produced.

What that means in practice:
- Where you are beats what's next in the book — but only when the connection is \
real. A battlefield, a treaty line, a portage route, a mining town, a dam that \
rearranged a river and a people. Verify it with web search before building on it. \
If the location has no genuine hook, say so implicitly by just teaching the \
least-covered era well.
- Always place the lesson in time. What came before, what came after, what it \
caused. An 8th grader should leave able to put the event on a timeline and say \
what it changed.
- Use primary sources at least once per lesson: a letter, a photograph, a treaty \
clause, a census line, a newspaper column. Give him the actual text or a faithful \
excerpt, and ask him what the author wanted the reader to believe.
- Teach contested history honestly and at grade level. Where accounts conflict — \
and for treaties, removal, and settlement they almost always do — present the \
conflict as the historical content, not a footnote.
- Fold honestly: a written source analysis is real writing; examining the \
composition of a period photograph or the architecture of a standing building is \
real art appreciation. Credit what you actually built.
- End with 2-4 `branches` for where the thread goes next.
"""


def _prompt(ctx: StudentContext, proposal: TopicProposal) -> str:
    return build_standard_prompt(ctx, proposal, "history and social studies")


def _post_process(ctx: StudentContext, proposal: TopicProposal, payload: dict[str, Any]) -> None:
    record_spiderweb_result(ctx, proposal, payload, agent_key="history")


SPEC = AgentSpec(
    key="history",
    name="History & Social Studies Agent",
    primary_subject="history",
    agent_guidance=GUIDANCE,
    next_topic=timeline,
    build_user_prompt=_prompt,
    use_web_search=True,
    max_web_searches=6,  # location grounding needs several; the video is one more
    post_process=_post_process,
)

AGENT = LessonAgent(SPEC)
