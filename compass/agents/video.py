"""Verifying a model's claim that a real teaching video exists.

Every Tier 1 agent may propose one supplementary video per lesson. The risk this
module exists to manage: a model asked "find a video" will, if left unchecked,
confidently return a title, channel, and URL that sound entirely plausible and
correspond to nothing real. A dead or wrong link is a minor annoyance; a fabricated
one that happens to resolve to something unrelated (or unsuitable) is worse than no
suggestion at all.

So a claimed video is trusted only if both hold:

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

Anything that fails either check is treated exactly like "no video was found" —
never surfaced half-verified.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

# Deliberately small. The point isn't to cover every video host that could ever be
# relevant — it's to keep this to one platform a parent already knows how to preview
# and set restrictions on. Widen this list only if a family specifically wants
# another host, not by default.
TRUSTED_VIDEO_DOMAINS = frozenset({"youtube.com", "youtu.be", "m.youtube.com"})

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


def verify_video(payload: dict[str, Any]) -> list[str]:
    """Check `payload["video"]` against this generation's real search results.

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

    return []
