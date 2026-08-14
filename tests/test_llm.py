"""The Anthropic request/response plumbing shared by every agent.

No live API calls here -- these test the pure functions that turn a response's
content blocks into the things the rest of the app trusts: usage numbers, and the
real URLs a search actually returned.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from compass.agents.llm import (
    LESSON_SCHEMA,
    LessonGenerationError,
    _count_web_searches,
    _search_result_urls,
    generate_lesson,
)


def result_block(urls: list[str]):
    return SimpleNamespace(
        type="web_search_tool_result",
        content=[SimpleNamespace(type="web_search_result", url=u, title="t") for u in urls],
    )


def error_block():
    """A failed search: `content` is an error object, not a list of results."""
    return SimpleNamespace(
        type="web_search_tool_result",
        content=SimpleNamespace(type="web_search_tool_result_error", error_code="timeout"),
    )


def test_search_result_urls_collects_across_multiple_tool_calls():
    content = [
        SimpleNamespace(type="text", text="{}"),
        result_block(["https://www.youtube.com/watch?v=a"]),
        SimpleNamespace(type="server_tool_use", name="web_search"),
        result_block(["https://www.youtube.com/watch?v=b", "https://example.com/x"]),
    ]
    urls = _search_result_urls(content)
    assert urls == [
        "https://www.youtube.com/watch?v=a",
        "https://www.youtube.com/watch?v=b",
        "https://example.com/x",
    ]


def test_search_result_urls_skips_error_blocks():
    urls = _search_result_urls([error_block(), result_block(["https://www.youtube.com/watch?v=a"])])
    assert urls == ["https://www.youtube.com/watch?v=a"]


def test_search_result_urls_is_empty_with_no_search_blocks():
    content = [SimpleNamespace(type="text", text="{}")]
    assert _search_result_urls(content) == []


def test_count_web_searches_counts_tool_use_blocks_not_results():
    content = [
        SimpleNamespace(type="server_tool_use", name="web_search"),
        SimpleNamespace(type="server_tool_use", name="web_search"),
        result_block(["https://www.youtube.com/watch?v=a"]),
    ]
    assert _count_web_searches(content) == 2


def test_lesson_schema_requires_the_video_object_closed():
    """One video per activity now, not one per lesson -- see LESSON_SCHEMA's
    activities item."""
    activity_schema = LESSON_SCHEMA["properties"]["activities"]["items"]
    video_schema = activity_schema["properties"]["video"]
    assert video_schema["additionalProperties"] is False
    assert set(video_schema["required"]) == {"found", "title", "url", "channel", "why"}
    assert video_schema["properties"]["found"]["type"] == "boolean"


def test_lesson_schema_requires_a_worked_example_on_every_activity():
    """Every activity must model the skill before he's asked to do it himself
    -- structurally required, not left to a hopefully-remembered prompt line."""
    activity_schema = LESSON_SCHEMA["properties"]["activities"]["items"]
    assert "example" in activity_schema["properties"]
    assert "example" in activity_schema["required"]
    assert activity_schema["additionalProperties"] is False


def test_an_unresolved_credential_typeerror_becomes_a_lessongenerationerror():
    """The Anthropic SDK raises a bare TypeError (not one of its own
    exception classes) when it can't resolve any credential at all -- caught
    live during this session's own testing, where it surfaced as a raw
    traceback across the Streamlit page instead of the friendly error every
    other auth failure gets. Must be wrapped the same way."""
    fake_client = MagicMock()
    fake_client.beta.messages.create.side_effect = TypeError(
        "Could not resolve authentication method."
    )
    with patch("compass.agents.llm._client", return_value=fake_client):
        with pytest.raises(LessonGenerationError, match="authenticate"):
            generate_lesson(system="system prompt", user_prompt="write it")
