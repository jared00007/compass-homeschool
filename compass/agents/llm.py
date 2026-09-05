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

# Every lesson reads as Learn -> Worked example -> Two checks -> Quiz. The
# teaching half is `learn` (explanation + one video) and `worked_example` (one
# problem walked step by step); the graded half is the two `activities` (parent-
# graded against each one's `answer`) plus the `quiz` (auto-graded).
#
# ACTIVITY_PHASES is retained only for back-compat: lessons generated under the
# older Learn/Practice model still carry a `phase`, and some rendering/tests
# still read it. New lessons don't set it.
ACTIVITY_PHASES = ("learn", "practice")


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
        "learn": _object(
            {
                "explanation": {
                    "type": "string",
                    "description": (
                        "The teaching section -- today's ONE idea explained in plain "
                        "language he reads on his own: what it is, why it matters, and a "
                        "short worked example inside the prose if it helps. He is not "
                        "graded here; teach it well enough that the two checks below are "
                        "fair. Write for a 13-year-old (see the writing rules), not a "
                        "parent-facing summary."
                    ),
                },
                "video": _object(_VIDEO_PROPERTIES),
            }
        ),
        "worked_example": _object(
            {
                "problem": {
                    "type": "string",
                    "description": (
                        "ONE problem of exactly the type the two activities will ask -- but "
                        "with DIFFERENT specifics (different numbers, a different sentence, a "
                        "different scenario) than either activity, so it models the move "
                        "rather than handing him an answer. A single problem, not several."
                    ),
                },
                "steps": {
                    "type": "string",
                    "description": (
                        "The full step-by-step walkthrough of `problem`, solved for him "
                        "start to finish. Break it into small, numbered steps in plain "
                        "language, and use a relatable hook or comparison where one fits "
                        "his age. This is the 'let's do one together' that comes right "
                        "before he tries his own -- he is NOT graded on it. For math or "
                        "anything procedural, show every step and the check; for writing, "
                        "model the thinking that produces a strong response."
                    ),
                },
            }
        ),
        "activities": {
            "type": "array",
            "description": (
                "EXACTLY TWO short comprehension checks on what `learn` just taught -- no "
                "more, no fewer. Both are graded: he does each, and the parent grades it "
                "against its own `answer`. Keep each one small and focused (a single clear "
                "task, not a multi-part project). Math and procedural subjects: keep them "
                "simple and objective -- a few problems with an exact worked answer. Every "
                "other subject: require some writing -- a few sentences or a short "
                "paragraph in his own words."
            ),
            "items": _object(
                {
                    "title": {"type": "string"},
                    "minutes": {"type": "integer"},
                    "instructions": {
                        "type": "string",
                        "description": (
                            "Written to the student in second person, specific enough to do "
                            "without further explanation. A single clear task."
                        ),
                    },
                    "requires_written_response": {
                        "type": "boolean",
                        "description": (
                            "True whenever `instructions` asks him to put an answer into "
                            "words -- write a sentence, answer a question, explain why, argue "
                            "a position. This puts an actual typing box in front of him. "
                            "False for anything genuinely done on paper instead: solving a "
                            "math problem by hand, drawing a diagram, a hands-on task. Every "
                            "non-math subject's checks should almost always be True."
                        ),
                    },
                    "writing_requirements": _object(
                        {
                            "min_words": {
                                "type": ["integer", "null"],
                                "description": (
                                    "The minimum word count `instructions` actually asks for, "
                                    "e.g. 150 for '150 to 200 words'. Null if requires_written_"
                                    "response is false, or you gave a sentence count instead."
                                ),
                            },
                            "max_words": {
                                "type": ["integer", "null"],
                                "description": (
                                    "The maximum word count, e.g. 200 for '150 to 200 words'. "
                                    "Null if you gave no ceiling."
                                ),
                            },
                            "min_sentences": {
                                "type": ["integer", "null"],
                                "description": (
                                    "The minimum sentence count `instructions` asks for, e.g. "
                                    "3 for '3-4 sentences'. Null if you gave a word count "
                                    "instead, or no count at all."
                                ),
                            },
                            "requires_quote": {
                                "type": "boolean",
                                "description": (
                                    "True only if `instructions` explicitly tells him to quote "
                                    "a source or text in quotation marks. False otherwise."
                                ),
                            },
                        }
                    ),
                    "answer": {
                        "type": "string",
                        "description": (
                            "The answer key for THIS activity, so the parent grades it "
                            "without solving it themselves. For math or anything procedural, "
                            "the full step-by-step worked solution and the final answer. For "
                            "a written response, describe concretely what a correct/complete "
                            "answer must contain (and, where there's a defensible range, that "
                            "any answer meeting the bar counts). The student NEVER sees this."
                        ),
                    },
                }
            ),
        },
        "materials": {"type": "array", "items": {"type": "string"}},
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
                "A pool of AT LEAST 20 multiple-choice questions checking whether he "
                "actually learned today's content, for him to take himself and get "
                "graded automatically. Separate from the two `activities`, which the "
                "parent grades.\n\n"
                "He is only asked five at a time, drawn from this pool and rotated on "
                "each retry, so the pool needs real breadth: cover every part of the "
                "lesson, at a mix of difficulties, and approach the same underlying "
                "idea from genuinely different angles rather than rewording one "
                "question twenty times. Two questions that would be answered correctly "
                "by the exact same piece of knowledge, phrased differently, are one "
                "question -- write another instead."
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
    effort: str | None = config.DEFAULT_EFFORT,
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

    `effort` is omitted from the request entirely when `None` rather than sent
    as a value the API might reject -- `output_config.effort` is a frontier-model
    tuning knob the smaller `config.REVIEW_MODEL` (writing review, book
    summaries) doesn't support at all, and passing it there is a 400, not a
    no-op.
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
        # 1-hour TTL, not the 5-minute default: a subject's four lessons in one
        # batch can each take a couple of minutes at high effort with web
        # search, so the default window can lapse before the batch finishes,
        # quietly losing the cache discount on every call after the first.
        # Costs more to write (2x vs 1.25x) but pays for itself within the
        # batch alone, well before accounting for later calls the same day.
        "system": [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}
        ],
        "output_config": {
            "format": {"type": "json_schema", "schema": schema or LESSON_SCHEMA},
        },
        "messages": messages,
    }
    if effort is not None:
        request["output_config"]["effort"] = effort
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
