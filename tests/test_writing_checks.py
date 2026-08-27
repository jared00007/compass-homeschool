"""compass/writing_checks.py -- the mechanical, automated checks (word
count, sentence count, whether a quote is present) that gate submitting a
writing response, so a parent isn't the one who has to notice by eye that
a 200-word assignment came back as two sentences.
"""

from __future__ import annotations

from compass.writing_checks import check_writing, count_sentences, count_words, has_quote


def test_count_words():
    assert count_words("one two three") == 3
    assert count_words("") == 0
    assert count_words("  extra   spaces  here ") == 3


def test_count_sentences():
    assert count_sentences("One sentence.") == 1
    assert count_sentences("One. Two! Three?") == 3
    assert count_sentences("Trailing punctuation...") == 1
    assert count_sentences("") == 0
    assert count_sentences("No terminal punctuation") == 1


def test_has_quote_detects_straight_and_curly_quotes():
    assert has_quote('He said "hello there" to us.')
    assert has_quote("He said “hello there” to us.")
    assert not has_quote("No quotes in this sentence at all.")
    assert not has_quote('Just one stray " mark.')


def test_blank_response_always_fails_even_with_no_requirements():
    assert check_writing("", {}) == ["Write something before submitting."]
    assert check_writing("   ", None) == ["Write something before submitting."]


def test_no_requirements_passes_anything_nonblank():
    assert check_writing("short", {}) == []
    assert check_writing("short", None) == []


def test_min_words_enforced():
    problems = check_writing("only four words here", {"min_words": 10})
    assert any("at least 10 words" in p for p in problems)
    assert "you have 4" in problems[0]


def test_max_words_enforced():
    text = " ".join(["word"] * 20)
    problems = check_writing(text, {"max_words": 10})
    assert any("under 10 words" in p for p in problems)


def test_word_count_within_range_passes():
    text = " ".join(["word"] * 15)
    assert check_writing(text, {"min_words": 10, "max_words": 20}) == []


def test_min_sentences_enforced():
    problems = check_writing("Only one sentence here.", {"min_sentences": 3})
    assert any("at least 3 sentences" in p for p in problems)


def test_requires_quote_enforced():
    problems = check_writing("No quote in this response.", {"requires_quote": True})
    assert any("quote" in p.lower() for p in problems)
    assert check_writing('He said "it worked" in the end.', {"requires_quote": True}) == []


def test_multiple_failures_are_all_reported_together():
    problems = check_writing("short", {"min_words": 50, "requires_quote": True})
    assert len(problems) == 2
