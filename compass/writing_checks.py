"""Automated, mechanical checks against a writing activity's stated
requirements: word count, sentence count, whether a quote is present.

Deliberately narrow. Whether the argument actually makes sense, or the
physics is right, needs a parent -- not a regex. This catches the purely
mechanical stuff instead (did he write enough, did he include the quote he
was told to) that he's been skipping on his own, so a parent isn't the one
who has to notice it every single time.
"""

from __future__ import annotations

import re

_QUOTE_RE = re.compile(r'["“][^"”]{2,}["”]')
_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+")


def count_words(text: str) -> int:
    return len(text.split())


def count_sentences(text: str) -> int:
    """Splits on sentence-ending punctuation and drops empty fragments --
    trailing punctuation, an ellipsis, or a stray period leaves no real
    sentence behind and shouldn't count as one."""
    return len([p for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()])


def has_quote(text: str) -> bool:
    """A quoted phrase of at least two characters, straight or curly
    quotes either way -- autocorrect on a tablet or phone often swaps one
    for the other mid-typing."""
    return bool(_QUOTE_RE.search(text))


def check_writing(text: str, requirements: dict | None) -> list[str]:
    """Every problem with `text` against `requirements`, plain-English,
    shown to him directly. Empty list means it passes.

    An empty/missing `requirements` (a lesson generated before this
    existed, or one where nothing specific was asked for) always passes
    everything but the blank-response check -- there's nothing else to
    check it against.
    """
    requirements = requirements or {}
    text = (text or "").strip()
    if not text:
        return ["Write something before submitting."]

    problems: list[str] = []
    words = count_words(text)
    min_words = requirements.get("min_words")
    if min_words and words < min_words:
        problems.append(f"Needs at least {min_words} words — you have {words}.")
    max_words = requirements.get("max_words")
    if max_words and words > max_words:
        problems.append(f"Keep it under {max_words} words — you have {words}.")

    min_sentences = requirements.get("min_sentences")
    if min_sentences:
        sentences = count_sentences(text)
        if sentences < min_sentences:
            problems.append(f"Needs at least {min_sentences} sentences — you have {sentences}.")

    if requirements.get("requires_quote") and not has_quote(text):
        problems.append("Needs at least one quote, in quotation marks.")

    return problems
