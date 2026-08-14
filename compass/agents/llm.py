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


_VIDEO_PROPERTIES: dict[str, Any] = {
    "found": {
        "type": "boolean",
        "description": (
            "True only if a real web search this turn returned a specific video "
            "with a URL you are copying exactly, that genuinely matches this "
            "activity's own skill. Set false whenever you are not certain -- "
            "never true just because a good video probably exists somewhere, "
            "and never true for an activity type (discussion, writing a "
            "paragraph, a field observation) that a video wouldn't actually "
            "help with."
        ),
    },
    "title": {"type": "string", "description": "Exact title from the search result. Empty if found is false."},
    "url": {
        "type": "string",
        "description": (
            "The exact URL from the search result, character for character. "
            "Empty if found is false."
        ),
    },
    "channel": {"type": "string", "description": "Empty if found is false."},
    "why": {
        "type": "string",
        "description": (
            "One sentence: what he'll actually see in it that this activity's "
            "own instructions and example don't already show him. Empty if "
            "found is false."
        ),
    },
}

LESSON_SCHEMA: dict[str, Any] = _object(
    {
        "title": {"type": "string", "description": "Short, concrete lesson title."},
        "topic": {"type": "string", "description": "The topic taught, restated."},
        "overview": {
            "type": "string",
            "description": (
                "Two or three sentences setting up what this covers and why now. He "
                "reads this himself, same as the activities -- see the system prompt's "
                "writing-for-a-13-year-old rules, not a parent-facing summary."
            ),
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
                    "example": {
                        "type": "string",
                        "description": (
                            "A worked demonstration of exactly this activity's skill, using "
                            "different specifics (different numbers, a different sentence, a "
                            "different scenario) than what he's actually asked to do in "
                            "`instructions` -- modeling the move once before he tries it "
                            "himself, not the answer to his own problem. For math or anything "
                            "procedural, a full step-by-step worked solution. Required for "
                            "every activity, not just the ones that feel like they need one."
                        ),
                    },
                    "video": _object(_VIDEO_PROPERTIES),
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
        "quiz": {
            "type": "array",
            "description": (
                "Three to five multiple-choice questions checking whether he actually "
                "learned today's content, for him to take himself and get graded "
                "automatically. Separate from `assessment`, which the parent uses."
            ),
            "items": _object(
                {
                    "question": {"type": "string"},
                    "choices": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Exactly four answer choices, one clearly correct and three "
                            "plausible distractors."
                        ),
                    },
                    "correct_index": {
                        "type": "integer",
                        "description": "0-based index into `choices` of the correct answer.",
                    },
                    "explanation": {
                        "type": "string",
                        "description": "One sentence on why that answer is correct, shown after he answers.",
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
    max_web_searches: int = 6,
    schema: dict[str, Any] | None = None,
    model: str = config.DEFAULT_MODEL,
    effort: str = config.DEFAULT_EFFORT,
    max_tokens: int = config.DEFAULT_MAX_TOKENS,
    max_turns: int = 6,
) -> dict[str, Any]:
    """Generate one lesson as a validated dict.

    `use_web_search` turns on Anthropic's server-side web search so the
    location-aware agents can ground a lesson in facts about where the family
    actually is this week, and so any agent can look for a real supplementary
    video. `max_web_searches` bounds how many queries one generation may spend --
    Science and History need several for location grounding; an agent only
    looking for one video needs far fewer.

    `schema` defaults to the Tier 1 lesson shape. The life-skills planner passes
    its own, because a plan for teaching a tire change is not a lesson with an
    answer key — but everything else about the request path is identical, and
    duplicating the retry, refusal, and usage-capture logic to say so would be a
    poor trade.
    """
    import anthropic

    client = _client()

    tools: list[dict[str, Any]] = []
    if use_web_search:
        tools.append(
            {"type": "web_search_20260209", "name": "web_search", "max_uses": max_web_searches}
        )

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]
    request: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "output_config": {
            "effort": effort,
            "format": {"type": "json_schema", "schema": schema or LESSON_SCHEMA},
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
        except TypeError as exc:
            # The SDK raises a plain TypeError (not one of its own exception
            # classes) when it can't resolve any credential at all -- caught
            # here so a parent sees the same friendly error as every other
            # auth failure, not a raw stack trace across their screen.
            raise LessonGenerationError(
                "Could not authenticate with the Anthropic API. Check ANTHROPIC_API_KEY."
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
    # Every URL a real search actually surfaced this turn -- the only thing a
    # claimed `video.url` is allowed to match. Consumed and removed by
    # `video.verify_video` before the lesson is persisted.
    lesson["_search_result_urls"] = _search_result_urls(response.content)
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


def _search_result_urls(content: list[Any]) -> list[str]:
    """Every URL a `web_search_tool_result` block actually returned this turn.

    This is the ground truth `video.py` checks a claimed video against. A failed
    search (`WebSearchToolResultError`) has no `.url` to read and is skipped.
    """
    urls: list[str] = []
    for block in content:
        if getattr(block, "type", None) != "web_search_tool_result":
            continue
        results = getattr(block, "content", None)
        if not isinstance(results, list):
            continue  # an error block, not a list of results
        for result in results:
            url = getattr(result, "url", None)
            if url:
                urls.append(url)
    return urls


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
