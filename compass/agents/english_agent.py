"""English / Language Arts Agent — tied to whatever he is currently reading.

The distinguishing constraint: this agent refuses to run without a current book.
Generic passage-and-question sets are exactly what this agent exists to avoid,
so "no book recorded" is a blocked state, not a fallback.
"""

from __future__ import annotations

from typing import Any

from compass.agents.framework import AgentSpec, LessonAgent, StudentContext, TopicProposal
from compass.agents.prompts import build_standard_prompt
from compass.agents.strategies import reading_tied, record_english_result

GUIDANCE = """\
Language arts here is anchored to one thing: the book he is actually reading right \
now. Reading level, vocabulary, and writing all come off that book.

What that means in practice:
- Quote the book. Refer to its characters, its events, its sentences. If you \
cannot ground an exercise in this specific text, it does not belong in the lesson.
- Never go past his current page. Assume he has read up to it and no further.
- Vocabulary is spaced repetition, not a list. Words due for review are given to \
you — weave them into discussion, writing prompts, or the text itself so he meets \
them again in context rather than being quizzed. New words should be words this \
book actually uses.
- Writing prompts respond to the book: argue with a character's choice, rewrite a \
scene from another point of view, defend an interpretation with textual evidence. \
Give him a length target and say what a strong response does.
- Spelling and grammar instruction should come out of his own writing or the \
author's sentences, not a decontextualized rule sheet.

Vocabulary format, exactly:
Put any new words in `materials` as lines shaped `VOCAB: word — definition`. \
Compass parses those into his review deck, so a malformed line silently loses the \
word. Six new words is plenty for one lesson.
"""


def _prompt(ctx: StudentContext, proposal: TopicProposal) -> str:
    return build_standard_prompt(ctx, proposal, "English / language arts")


def _post_process(ctx: StudentContext, proposal: TopicProposal, payload: dict[str, Any]) -> None:
    record_english_result(ctx, proposal, payload)


SPEC = AgentSpec(
    key="english",
    name="English & Language Arts Agent",
    primary_subject="reading",
    agent_guidance=GUIDANCE,
    next_topic=reading_tied,
    build_user_prompt=_prompt,
    # On, but only for the shared video search -- the book itself is the source
    # of truth here, not the web, so the budget stays tight.
    use_web_search=True,
    max_web_searches=2,
    post_process=_post_process,
)

AGENT = LessonAgent(SPEC)
