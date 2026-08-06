"""Verifying a claimed supplementary video against real search results.

The risk this guards against: asked to "find a video," a model will happily
return a plausible title, channel, and URL that correspond to nothing real. This
module's whole job is refusing to trust that claim unless it's backed by three
things the app can check for itself: a URL a real search actually returned, on a
platform a parent already knows how to preview, from a channel that subject's
own vetted list actually names.
"""

from __future__ import annotations

from compass.agents.video import (
    TRUSTED_CHANNELS,
    channel_is_trusted,
    channels_for_prompt,
    is_trusted_domain,
    verify_video,
)

REAL_URL = "https://www.youtube.com/watch?v=abc123"


def a_payload(**overrides):
    payload = {
        "video": {
            "found": True,
            "title": "Two-Step Equations Explained",
            "url": REAL_URL,
            "channel": "Khan Academy",
            "why": "Shows the steps worked in real time.",
        },
        "_search_result_urls": [REAL_URL, "https://www.youtube.com/watch?v=other"],
    }
    payload.update(overrides)
    return payload


def verify(payload, agent_key="math"):
    return verify_video(payload, agent_key)


# --- domain checking -----------------------------------------------------------


def test_youtube_domains_are_trusted():
    assert is_trusted_domain("https://www.youtube.com/watch?v=abc")
    assert is_trusted_domain("https://youtube.com/watch?v=abc")
    assert is_trusted_domain("https://youtu.be/abc")
    assert is_trusted_domain("https://m.youtube.com/watch?v=abc")


def test_other_domains_are_not_trusted():
    assert not is_trusted_domain("https://vimeo.com/12345")
    assert not is_trusted_domain("https://example.com/watch?v=abc")
    assert not is_trusted_domain("https://youtube.com.evil.example/watch?v=abc")
    assert not is_trusted_domain("")


# --- the main gate: a real, verifiable, on-list video is kept -------------------


def test_a_real_search_verified_trusted_channel_video_is_kept():
    payload = a_payload()
    warnings = verify(payload)
    assert not warnings
    assert payload["video"]["found"] is True
    assert payload["video"]["url"] == REAL_URL


def test_the_search_urls_sidecar_is_removed_either_way():
    """It has no value once verification is done and must not be persisted."""
    payload = a_payload()
    verify(payload)
    assert "_search_result_urls" not in payload

    payload = a_payload(video={"found": False, "title": "", "url": "", "channel": "", "why": ""})
    verify(payload)
    assert "_search_result_urls" not in payload


# --- a video that doesn't match a real search result is dropped ----------------


def test_a_url_not_in_the_search_results_is_dropped():
    """The central anti-hallucination check: an invented URL is caught here."""
    payload = a_payload(
        video={
            "found": True,
            "title": "A Video That Sounds Real",
            "url": "https://www.youtube.com/watch?v=totallymadeup",
            "channel": "Khan Academy",
            "why": "Very convincing.",
        }
    )
    warnings = verify(payload)
    assert payload["video"] == {
        "found": False, "title": "", "url": "", "channel": "", "why": "",
    }
    assert any("didn't match an actual web search result" in w for w in warnings)


def test_an_empty_url_with_found_true_is_dropped():
    payload = a_payload(video={"found": True, "title": "x", "url": "", "channel": "Khan Academy", "why": ""})
    warnings = verify(payload)
    assert payload["video"]["found"] is False
    assert warnings


# --- reformatted-but-real URLs are still recognized ----------------------------
#
# A model told to copy a URL exactly still reliably reformats it a little: adds
# a timestamp, drops "www.", swaps http for https. None of that changes which
# video it is, so these must NOT be treated as hallucinations.


def test_a_url_with_an_added_timestamp_param_still_matches():
    real = "https://www.youtube.com/watch?v=abc123"
    payload = a_payload(
        video={
            "found": True,
            "title": "Two-Step Equations Explained",
            "url": "https://www.youtube.com/watch?v=abc123&t=32s",
            "channel": "Khan Academy",
            "why": "x",
        },
        _search_result_urls=[real],
    )
    warnings = verify(payload)
    assert not warnings
    assert payload["video"]["found"] is True


def test_a_shortened_youtu_be_url_matches_the_long_form_result():
    payload = a_payload(
        video={
            "found": True,
            "title": "Two-Step Equations Explained",
            "url": "https://youtu.be/abc123",
            "channel": "Khan Academy",
            "why": "x",
        },
        _search_result_urls=["https://www.youtube.com/watch?v=abc123"],
    )
    warnings = verify(payload)
    assert not warnings
    assert payload["video"]["found"] is True


def test_dropping_www_and_switching_scheme_still_matches():
    payload = a_payload(
        video={
            "found": True,
            "title": "Two-Step Equations Explained",
            "url": "http://youtube.com/watch?v=abc123",
            "channel": "Khan Academy",
            "why": "x",
        },
        _search_result_urls=["https://www.youtube.com/watch?v=abc123"],
    )
    warnings = verify(payload)
    assert not warnings
    assert payload["video"]["found"] is True


def test_a_different_video_id_on_the_same_host_is_still_rejected():
    """The ID-tolerant matching must not turn into "any youtube.com URL is fine"."""
    payload = a_payload(
        video={
            "found": True,
            "title": "A Different Video",
            "url": "https://www.youtube.com/watch?v=totallydifferentid",
            "channel": "Khan Academy",
            "why": "x",
        },
        _search_result_urls=["https://www.youtube.com/watch?v=abc123"],
    )
    warnings = verify(payload)
    assert payload["video"]["found"] is False
    assert any("didn't match an actual web search result" in w for w in warnings)


# --- a real, search-verified video on an untrusted host is still dropped -------


def test_a_search_verified_video_on_an_untrusted_domain_is_dropped():
    """Real doesn't mean vouched-for. Only a known, previewable platform is."""
    sketchy_url = "https://randomvideosite.example/watch?v=abc123"
    payload = a_payload(
        video={
            "found": True,
            "title": "Some Video",
            "url": sketchy_url,
            "channel": "Khan Academy",
            "why": "Relevant.",
        },
        _search_result_urls=[sketchy_url],
    )
    warnings = verify(payload)
    assert payload["video"]["found"] is False
    assert any("unrecognised site" in w for w in warnings)


# --- the channel allowlist, per subject -----------------------------------------


def test_every_agent_key_has_a_channel_list():
    for key in ("math", "science", "english", "history"):
        assert TRUSTED_CHANNELS[key], key


def test_a_channel_not_on_the_list_is_dropped():
    payload = a_payload(
        video={
            "found": True,
            "title": "Two-Step Equations",
            "url": REAL_URL,
            "channel": "Some Random YouTuber",
            "why": "x",
        }
    )
    warnings = verify(payload, "math")
    assert payload["video"]["found"] is False
    assert any("not on the approved list" in w for w in warnings)
    assert any("Some Random YouTuber" in w for w in warnings)


def test_the_channel_list_is_scoped_per_subject_not_pooled():
    """Math Antics is approved for math but must not pass for a science lesson,
    even though it's a real, legitimate channel."""
    assert channel_is_trusted("math", "Math Antics")
    assert not channel_is_trusted("science", "Math Antics")

    payload = a_payload(
        video={
            "found": True,
            "title": "Two-Step Equations",
            "url": REAL_URL,
            "channel": "Math Antics",
            "why": "x",
        }
    )
    warnings = verify(payload, "science")
    assert payload["video"]["found"] is False
    assert any("not on the approved list" in w for w in warnings)


def test_crash_course_subchannels_are_recognized():
    """"Crash Course Chemistry" and "Crash Course US History" are separate
    YouTube channels in practice, but both should match the approved "Crash
    Course" entry -- a family doesn't vet each spinoff by name."""
    assert channel_is_trusted("science", "Crash Course Chemistry")
    assert channel_is_trusted("history", "Crash Course US History")
    assert channel_is_trusted("english", "Crash Course Literature")


def test_ted_ed_formatting_variants_are_recognized():
    for spelling in ("TED-Ed", "TED Ed", "Ted-Ed", "tededucation"):
        assert channel_is_trusted("history", spelling), spelling


def test_an_empty_channel_with_a_real_url_is_dropped():
    payload = a_payload(
        video={
            "found": True,
            "title": "Two-Step Equations",
            "url": REAL_URL,
            "channel": "",
            "why": "x",
        }
    )
    warnings = verify(payload)
    assert payload["video"]["found"] is False
    assert any("not on the approved list" in w for w in warnings)


def test_channels_for_prompt_lists_only_that_agents_channels():
    math_text = channels_for_prompt("math")
    science_text = channels_for_prompt("science")
    assert "Khan Academy" in math_text
    assert "Math Antics" in math_text
    assert "SciShow" not in math_text
    assert "SciShow" in science_text


# --- "no video found" is left alone, and cleaned up if inconsistent -----------


def test_found_false_is_passed_through():
    payload = a_payload(video={"found": False, "title": "", "url": "", "channel": "", "why": ""})
    warnings = verify(payload)
    assert not warnings
    assert payload["video"]["found"] is False


def test_found_false_with_stray_text_is_cleaned_up():
    """Defensive: some stray filler text alongside found=False shouldn't survive."""
    payload = a_payload(
        video={"found": False, "title": "leftover title", "url": "", "channel": "", "why": ""}
    )
    verify(payload)
    assert payload["video"] == {
        "found": False, "title": "", "url": "", "channel": "", "why": "",
    }


def test_a_payload_with_no_video_key_is_a_no_op():
    """Life-skill plans and pre-feature cached lessons have no `video` key at all."""
    payload = {"_search_result_urls": ["https://www.youtube.com/watch?v=x"]}
    warnings = verify(payload)
    assert warnings == []
    assert "video" not in payload
    assert "_search_result_urls" not in payload
