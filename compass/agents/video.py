"""Verifying a model's claim that a real teaching video exists.

Every Tier 1 agent may propose one supplementary video per lesson. The risk this
module exists to manage: a model asked "find a video" will, if left unchecked,
confidently return a title, channel, and URL that sound entirely plausible and
correspond to nothing real. A dead or wrong link is a minor annoyance; a fabricated
one that happens to resolve to something unrelated (or unsuitable) is worse than no
suggestion at all.

So a claimed video is trusted only if all three hold:

1. Its URL corresponds to one the model's own web search actually returned this
   generation — not recalled from training data. `llm.py` collects every URL
   surfaced by the `web_search` tool during the request; this module accepts
   nothing else. Matching is by extracted YouTube video ID, not exact string
   equality, because a model told to "copy the URL exactly" still reliably adds
   a timestamp or tracking parameter, drops `www.`, or swaps `http` for `https`
   -- none of which changes which video it is, so exact-match would reject
   real, search-found videos over punctuation.
2. That URL is on a small allowlist of video hosts a parent already knows how to
   preview and control. A real, search-verified link to an unknown site is still
   not something this app will vouch for.
3. Its claimed channel is on this subject's own short list of vetted educational
   channels (`TRUSTED_CHANNELS`). This one is honest about its limits: Anthropic's
   search results give a title and URL, not a verified uploader, so `channel` is
   still the model's own claim rather than something this module can independently
   confirm. What narrows the risk is upstream, not this check alone -- the prompt
   directs the model to search *by channel name* ("Khan Academy two-step
   equations," not just "two-step equations"), so a real search naturally surfaces
   that channel's own uploads. This check then closes the loop: if the model
   claims a channel outside the approved list, the video is dropped regardless of
   how real or on-topic it otherwise looks. A cryptographic guarantee -- actually
   looking up the video's channel ID via the YouTube Data API -- would need a new
   API key and quota for a family homeschool app; this project's calibration has
   been the least infrastructure that solves the problem, so that's a deliberate
   choice to skip unless a family wants it.

Anything that fails any of the three is treated exactly like "no video was
found" — never surfaced half-verified.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

# Deliberately small. The point isn't to cover every video host that could ever be
# relevant — it's to keep this to one platform a parent already knows how to preview
# and set restrictions on. Widen this list only if a family specifically wants
# another host, not by default.
TRUSTED_VIDEO_DOMAINS = frozenset({"youtube.com", "youtu.be", "m.youtube.com"})

# One family's vetted list per subject, not a general "reputable education
# channel" ranking -- a family that trusts a different set should edit this
# directly. Channels appear on more than one list where that's genuinely true
# (Khan Academy and Crash Course both cover several subjects); TRUSTED_CHANNELS
# keys match each AgentSpec.key exactly, since that's what selects the list.
TRUSTED_CHANNELS: dict[str, tuple[str, ...]] = {
    "math": ("Khan Academy", "Math Antics", "Mashup Math"),
    "science": (
        "Khan Academy",
        "Crash Course",
        "SciShow",
        "Bozeman Science",
        "National Geographic",
    ),
    "english": ("Khan Academy", "Crash Course", "TED-Ed"),
    "history": ("Khan Academy", "Crash Course", "TED-Ed"),
}


def channels_for_prompt(agent_key: str) -> str:
    """The channel list as prose for this agent's system prompt."""
    return ", ".join(TRUSTED_CHANNELS.get(agent_key, ())) or "none configured"


def _normalize_channel(name: str) -> str:
    """Lowercase, letters-and-digits-only, so hyphens/spacing/case don't matter.

    "TED-Ed", "TED Ed", and "Ted-ed Official" all reduce to strings that contain
    "teded" -- which is exactly the tolerance a substring match needs.
    """
    return re.sub(r"[^a-z0-9]", "", name.lower())


def channel_is_trusted(agent_key: str, channel: str) -> bool:
    """Does the claimed channel match one of this subject's approved names?

    A subchannel like "Crash Course Chemistry" is meant to match the approved
    "Crash Course" entry -- checked as substring-of, not equality, for exactly
    that reason. "Math Antics" approved for math must NOT pass for a science
    lesson; the list is looked up per agent, never pooled across all four.
    """
    normalized_channel = _normalize_channel(channel)
    if not normalized_channel:
        return False
    allowed = TRUSTED_CHANNELS.get(agent_key, ())
    return any(_normalize_channel(name) in normalized_channel for name in allowed)

_EMPTY_VIDEO: dict[str, Any] = {
    "found": False,
    "title": "",
    "url": "",
    "channel": "",
    "why": "",
}


def _domain(url: str) -> str:
    host = (urlparse(url).netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_trusted_domain(url: str) -> bool:
    return _domain(url) in TRUSTED_VIDEO_DOMAINS


def _video_id(url: str) -> str | None:
    """The YouTube video ID inside a URL, in whichever of its common shapes.

    A model told to "copy the URL exactly" still routinely reformats it a
    little -- http vs https, a dropped `www.`, an added `&t=32s` or `&si=...`
    tracking suffix. None of that changes which video it points at, so an
    exact string match against search results is too brittle: it would reject
    a genuinely real, search-found video over punctuation. Comparing the
    extracted ID instead tolerates the reformatting without weakening the
    actual guarantee, since the ID still has to trace back to a URL a real
    search returned.
    """
    parsed = urlparse(url)
    host = _domain(url)

    if host in ("youtube.com", "m.youtube.com"):
        if parsed.path == "/watch":
            values = parse_qs(parsed.query).get("v")
            return values[0] if values else None
        for prefix in ("/embed/", "/shorts/", "/live/"):
            if parsed.path.startswith(prefix):
                tail = parsed.path[len(prefix):].split("/")[0]
                return tail or None
        return None

    if host == "youtu.be":
        tail = parsed.path.lstrip("/").split("/")[0]
        return tail or None

    return None


def _matches_a_real_result(url: str, search_urls: set[str]) -> bool:
    if url in search_urls:
        return True
    claimed_id = _video_id(url)
    if claimed_id is None:
        return False
    return any(claimed_id == _video_id(u) for u in search_urls)


def verify_video(payload: dict[str, Any], agent_key: str) -> list[str]:
    """Check `payload["video"]` against this generation's real search results.

    `agent_key` selects which subject's channel allowlist applies -- a channel
    approved for math is not automatically approved for science, even if it's a
    real, well-known name (see `channel_is_trusted`).

    `_search_result_urls` is a sidecar key `generate_lesson` attaches with every
    URL actually returned by web search this call; it is consumed and removed
    here rather than persisted, since it has no value once verification is done.

    Returns a parent-facing warning if a claim was dropped, exactly like the
    credit-normalization warnings this mirrors — a silent downgrade would be
    worse than not checking at all.
    """
    search_urls = set(payload.pop("_search_result_urls", None) or [])

    video = payload.get("video")
    if video is None:
        return []

    if not video.get("found"):
        # Defensive: force the clean shape even if the model left stray text
        # alongside found=False, so every lesson has one consistent "no video"
        # representation for the renderer to check.
        if any(video.get(k) for k in ("title", "url", "channel", "why")):
            payload["video"] = dict(_EMPTY_VIDEO)
        return []

    url = (video.get("url") or "").strip()

    if not url or not _matches_a_real_result(url, search_urls):
        payload["video"] = dict(_EMPTY_VIDEO)
        return [
            "Dropped a suggested video whose link didn't match an actual web "
            "search result — treating it as none found rather than risking a "
            "broken or invented link."
        ]

    if not is_trusted_domain(url):
        payload["video"] = dict(_EMPTY_VIDEO)
        return [
            f"Dropped a suggested video at an unrecognised site ({_domain(url) or url}) "
            "— only YouTube links are trusted for now."
        ]

    channel = video.get("channel") or ""
    if not channel_is_trusted(agent_key, channel):
        payload["video"] = dict(_EMPTY_VIDEO)
        return [
            f"Dropped a suggested video from a channel not on the approved list "
            f"for this subject ({channel or 'unlabeled'})."
        ]

    return []
