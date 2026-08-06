"""Science Agent — spiderweb branching from a topic or a location.

This is the shape the original roadschooling prototype had: pick a thread, pull
it, and let each lesson propose the next set of branches. Compass stores the web
so the thread survives between sessions instead of restarting every time.
"""

from __future__ import annotations

from typing import Any

from compass.agents.framework import AgentSpec, LessonAgent, StudentContext, TopicProposal
from compass.agents.prompts import build_standard_prompt
from compass.agents.strategies import record_spiderweb_result, spiderweb

GUIDANCE = """\
Science here is a spiderweb, not a syllabus. Each lesson pulls one thread and \
proposes the next branches, so the year's path is emergent and driven by where \
the family actually is.

What that means in practice:
- Location first. If the family is at a national park, a coastline, a lava field, \
a river, a farm — the lesson is about THAT, specifically. Use web search to get \
the real species, the real geology, the real conditions. "Some birds live here" \
is a failure; "the Clark's nutcracker caches whitebark pine seeds here, which is \
why the pines regenerate along ridgelines" is the job.
- Every lesson gets one genuine field or hands-on component. Observation, \
measurement, collection, a built thing. Not a worksheet with an outdoor theme.
- Teach the mechanism, not the label. An 8th grader should leave knowing why \
something happens, not just what it's called.
- Fold honestly. A field journal entry is real writing. Sketching a specimen with \
attention to structure is real art. Reading an interpretive sign is not reading \
instruction. Credit what you actually built into the activities.
- End with 2-4 `branches`: real, distinct next lessons this one opens up. Vary \
their direction — one that goes deeper, one that goes sideways into another \
discipline, one that follows the location. These become the pool the next lesson \
is drawn from, so a vague branch costs you later.
"""


def _prompt(ctx: StudentContext, proposal: TopicProposal) -> str:
    return build_standard_prompt(ctx, proposal, "science")


def _post_process(ctx: StudentContext, proposal: TopicProposal, payload: dict[str, Any]) -> None:
    record_spiderweb_result(ctx, proposal, payload, agent_key="science")


SPEC = AgentSpec(
    key="science",
    name="Science Agent",
    primary_subject="science",
    agent_guidance=GUIDANCE,
    next_topic=spiderweb,
    build_user_prompt=_prompt,
    use_web_search=True,
    max_web_searches=6,  # location grounding needs several; the video is one more
    post_process=_post_process,
)

AGENT = LessonAgent(SPEC)
