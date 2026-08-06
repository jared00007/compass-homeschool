"""Anthropic API plumbing shared by every agent.

The agents differ in *what to teach next*; they do not differ in how they talk to
the model. That lives here: one structured-output schema, one request path, one
set of error semantics.
"""

from __future__ import annotations

import json
from typing import Any

from compass import config
from compass.subjects import SUBJECT_KEYS

# Server-side fallback: on the rare chance a safety classifier declines a
# request, re-serve it on Anthropic's recommended fallback model rather than
# handing the parent an error. Routed by refusal category.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

ACTIVITY_KINDS = (
    "instruction",
    "practice",
    "reading",
    "writing",
    "discussion",
    "field",
    "project",
    "assessment",
)


class LessonGenerationError(RuntimeError):
    """Raised when a lesson could not be generated. Message is parent-facing."""


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    """Structured outputs require every object to be closed and fully required."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


LESSON_SCHEMA: dict[str, Any] = _object(
    {
        "title": {"type": "string", "description": "Short, concrete lesson title."},
        "topic": {"type": "string", "description": "The topic taught, restated."},
        "overview": {
            "type": "string",
            "description": "Two or three sentences for the parent: what this covers and why now.",
        },
        "learning_objectives": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Observable objectives, phrased as what the student will be able to do.",
        },
        "activities": {
            "type": "array",
            "items": _object(
                {
                    "title": {"type": "string"},
                    "kind": {"type": "string", "enum": list(ACTIVITY_KINDS)},
                    "minutes": {"type": "integer"},
                    "instructions": {
                        "type": "string",
                        "description": (
                            "Written to the student in second person, specific enough to do "
                            "without further explanation."
                        ),
                    },
                }
            ),
        },
        "materials": {"type": "array", "items": {"type": "string"}},
        "assessment": _object(
            {
                "kind": {"type": "string"},
                "description": {"type": "string"},
                "mastery_criteria": {
                    "type": "string",
                    "description": "What counts as mastered, concretely enough to score.",
                },
            }
        ),
        "subject_credits": {
            "type": "array",
            "description": (
                "Which of the 11 Washington-required subjects this activity credits, and for "
                "how many minutes each. Minutes may sum to more than estimated_minutes when "
                "one activity genuinely teaches several subjects at once."
            ),
            "items": _object(
                {
                    "subject": {"type": "string", "enum": list(SUBJECT_KEYS)},
                    "minutes": {"type": "integer"},
                    "justification": {
                        "type": "string",
                        "description": "The specific part of the lesson that earns this credit.",
                    },
                }
            ),
        },
        "estimated_minutes": {"type": "integer"},
        "parent_notes": {
            "type": "string",
            "description": "How to run this, what to watch for, common misconceptions.",
        },
        "branches": {
            "type": "array",
            "description": (
                "Follow-on topics this lesson opens up. Used to grow the spiderweb for "
                "location-driven subjects; may be empty for graph-driven subjects."
            ),
            "items": _object({"topic": {"type": "string"}, "rationale": {"type": "string"}}),
        },
    }
)


def _client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - environment guard
        raise LessonGenerationError(
            "The `anthropic` package is not installed. Run: pip install -r requirements.txt"
        ) from exc
    try:
        return anthropic.Anthropic()
    except Exception as exc:  # pragma: no cover - environment guard
        raise LessonGenerationError(
            "Could not create an Anthropic client. Set ANTHROPIC_API_KEY, or run `ant auth login`."
        ) from exc


def _extract_json(content: list[Any]) -> dict[str, Any]:
    for block in content:
        if getattr(block, "type", None) == "text":
            text = block.text.strip()
            if not text:
                continue
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise LessonGenerationError(
                    f"The model returned text that was not valid JSON: {text[:200]}"
                ) from exc
    raise LessonGenerationError("The model returned no text content.")


def generate_lesson(
    system: str,
    user_prompt: str,
    *,
    use_web_search: bool = False,
    model: str = config.DEFAULT_MODEL,
    effort: str = config.DEFAULT_EFFORT,
    max_tokens: int = config.DEFAULT_MAX_TOKENS,
    max_turns: int = 6,
) -> dict[str, Any]:
    """Generate one lesson as a validated dict.

    `use_web_search` turns on Anthropic's server-side web search so the
    location-aware agents can ground a lesson in facts about where the family
    actually is this week.
    """
    import anthropic

    client = _client()

    tools: list[dict[str, Any]] = []
    if use_web_search:
        tools.append({"type": "web_search_20260209", "name": "web_search", "max_uses": 6})

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]
    request: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "output_config": {
            "effort": effort,
            "format": {"type": "json_schema", "schema": LESSON_SCHEMA},
        },
        "messages": messages,
    }
    if tools:
        request["tools"] = tools

    response = None
    for _ in range(max_turns):
        try:
            response = client.beta.messages.create(
                **request, betas=[FALLBACK_BETA], fallbacks="default"
            )
        except anthropic.BadRequestError:
            # Server-side fallbacks may not be enabled for this key/platform.
            # The lesson matters more than the safety net — retry without it.
            response = client.messages.create(**request)
        except anthropic.AuthenticationError as exc:
            raise LessonGenerationError(
                "Anthropic rejected the API key. Check ANTHROPIC_API_KEY."
            ) from exc
        except anthropic.RateLimitError as exc:
            raise LessonGenerationError(
                "Rate limited by the Anthropic API. Wait a moment and try again."
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LessonGenerationError(
                "Could not reach the Anthropic API. Check your network connection."
            ) from exc

        if response.stop_reason == "refusal":
            detail = getattr(response, "stop_details", None)
            category = getattr(detail, "category", None) or "unspecified"
            raise LessonGenerationError(
                f"The model declined this request ({category}). Try rephrasing the topic."
            )

        if response.stop_reason == "pause_turn":
            # A long server-tool turn hit its iteration limit. Echo the turn back
            # and let the server resume where it left off.
            messages.append({"role": "assistant", "content": response.content})
            continue

        if response.stop_reason == "max_tokens":
            raise LessonGenerationError(
                "The lesson was cut off before it finished. Try a shorter lesson length."
            )
        break

    if response is None:  # pragma: no cover - defensive
        raise LessonGenerationError("No response from the model.")

    lesson = _extract_json(response.content)
    lesson["_usage"] = {
        "input_tokens": getattr(response.usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(response.usage, "output_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(
            response.usage, "cache_creation_input_tokens", 0
        )
        or 0,
        # Server-tool queries are billed per search, not as tokens, so they have
        # to be counted off the content blocks.
        "web_searches": _count_web_searches(response.content),
        "model": getattr(response, "model", model),
    }
    return lesson


def _count_web_searches(content: list[Any]) -> int:
    return sum(
        1
        for block in content
        if getattr(block, "type", None) == "server_tool_use"
        and getattr(block, "name", None) == "web_search"
    )


def api_available() -> tuple[bool, str]:
    """Cheap preflight so the UI can explain itself before a user clicks Generate."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, "The `anthropic` package is not installed (pip install -r requirements.txt)."
    try:
        _client()
    except LessonGenerationError as exc:
        return False, str(exc)
    return True, "Ready."
