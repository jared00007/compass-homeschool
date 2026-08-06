"""Tier 1 agents. Importing this package registers all four."""

from compass.agents.framework import (
    AgentSpec,
    GeneratedLesson,
    LessonAgent,
    StudentContext,
    TopicProposal,
    all_agents,
    get_agent,
    register,
)
from compass.agents.llm import LessonGenerationError, api_available

from compass.agents.math_agent import AGENT as MATH_AGENT
from compass.agents.science_agent import AGENT as SCIENCE_AGENT
from compass.agents.english_agent import AGENT as ENGLISH_AGENT
from compass.agents.history_agent import AGENT as HISTORY_AGENT

for _agent in (MATH_AGENT, SCIENCE_AGENT, ENGLISH_AGENT, HISTORY_AGENT):
    register(_agent)

__all__ = [
    "AgentSpec",
    "GeneratedLesson",
    "LessonAgent",
    "LessonGenerationError",
    "StudentContext",
    "TopicProposal",
    "MATH_AGENT",
    "SCIENCE_AGENT",
    "ENGLISH_AGENT",
    "HISTORY_AGENT",
    "all_agents",
    "api_available",
    "get_agent",
    "register",
]
