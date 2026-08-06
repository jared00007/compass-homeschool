"""Verifying a claimed supplementary video against real search results.

The risk this guards against: asked to "find a video," a model will happily
return a plausible title, channel, and URL that correspond to nothing real. This
module's whole job is refusing to trust that claim unless it's backed by something
the app can check for itself -- a URL a real search actually returned, on a
platform a parent already knows how to preview.
"""

from __future__ import annotations

from compass.agents.video import is_trusted_domain, verify_video

REAL_URL = "https://www.youtube.com/watch?v=abc123"


def a_payload(**overrides):
    payload = {
        "video": {
            "found": True,
            "title": "Two-Step Equations Explained",
            "url": REAL_URL,
            "channel": "Some Channel",
            "why": "Shows the steps worked in real time.",
        },
        "_search_result_urls": [REAL_URL, "https://www.youtube.com/watch?v=other"],
    }
    payload.update(overrides)
    return payload


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


# --- the main gate: a real, verifiable video is kept ----------------------------


def test_a_real_search_verified_video_is_kept():
    payload = a_payload()
    warnings = verify_video(payload)
    assert not warnings
    assert payload["video"]["found"] is True
    assert payload["video"]["url"] == REAL_URL


def test_the_search_urls_sidecar_is_removed_either_way():
    """It has no value once verification is done and must not be persisted."""
    payload = a_payload()
    verify_video(payload)
    assert "_search_result_urls" not in payload

    payload = a_payload(video={"found": False, "title": "", "url": "", "channel": "", "why": ""})
    verify_video(payload)
    assert "_search_result_urls" not in payload


# --- a video that doesn't match a real search result is dropped ----------------


def test_a_url_not_in_the_search_results_is_dropped():
    """The central anti-hallucination check: an invented URL is caught here."""
    payload = a_payload(
        video={
            "found": True,
            "title": "A Video That Sounds Real",
            "url": "https://www.youtube.com/watch?v=totallymadeup",
            "channel": "Definitely Real Channel",
            "why": "Very convincing.",
        }
    )
    warnings = verify_video(payload)
    assert payload["video"] == {
        "found": False, "title": "", "url": "", "channel": "", "why": "",
    }
    assert any("didn't match an actual web search result" in w for w in warnings)


def test_an_empty_url_with_found_true_is_dropped():
    payload = a_payload(video={"found": True, "title": "x", "url": "", "channel": "", "why": ""})
    warnings = verify_video(payload)
    assert payload["video"]["found"] is False
    assert warnings


# --- a real, search-verified video on an untrusted host is still dropped -------


def test_a_search_verified_video_on_an_untrusted_domain_is_dropped():
    """Real doesn't mean vouched-for. Only a known, previewable platform is."""
    sketchy_url = "https://randomvideosite.example/watch?v=abc123"
    payload = a_payload(
        video={
            "found": True,
            "title": "Some Video",
            "url": sketchy_url,
            "channel": "Some Channel",
            "why": "Relevant.",
        },
        _search_result_urls=[sketchy_url],
    )
    warnings = verify_video(payload)
    assert payload["video"]["found"] is False
    assert any("unrecognised site" in w for w in warnings)


# --- "no video found" is left alone, and cleaned up if inconsistent -----------


def test_found_false_is_passed_through():
    payload = a_payload(video={"found": False, "title": "", "url": "", "channel": "", "why": ""})
    warnings = verify_video(payload)
    assert not warnings
    assert payload["video"]["found"] is False


def test_found_false_with_stray_text_is_cleaned_up():
    """Defensive: some stray filler text alongside found=False shouldn't survive."""
    payload = a_payload(
        video={"found": False, "title": "leftover title", "url": "", "channel": "", "why": ""}
    )
    verify_video(payload)
    assert payload["video"] == {
        "found": False, "title": "", "url": "", "channel": "", "why": "",
    }


def test_a_payload_with_no_video_key_is_a_no_op():
    """Life-skill plans and pre-feature cached lessons have no `video` key at all."""
    payload = {"_search_result_urls": ["https://www.youtube.com/watch?v=x"]}
    warnings = verify_video(payload)
    assert warnings == []
    assert "video" not in payload
    assert "_search_result_urls" not in payload
