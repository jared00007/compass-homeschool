"""The little daily-delight content: deterministic by date, well-formed."""

from __future__ import annotations

from datetime import date, timedelta

from compass import daily


def test_each_pick_is_stable_within_a_day_and_rotates_across_days():
    today = date(2026, 9, 2)
    # Same day -> same pick, no matter how many reruns.
    assert daily.greeting_of_the_day(today) == daily.greeting_of_the_day(today)
    assert daily.riddle_of_the_day(today) == daily.riddle_of_the_day(today)
    assert daily.word_of_the_day(today) == daily.word_of_the_day(today)
    assert daily.history_flashback(today) == daily.history_flashback(today)
    # A different day pulls a different index (the lists are long enough that
    # consecutive days never land on the same slot).
    tomorrow = today + timedelta(days=1)
    assert daily.riddle_of_the_day(today) != daily.riddle_of_the_day(tomorrow)


def test_content_lists_are_well_formed_and_nonempty():
    assert daily.GREETINGS and all(isinstance(g, str) and g for g in daily.GREETINGS)
    assert daily.HISTORY and all(isinstance(h, str) and h for h in daily.HISTORY)
    for question, answer in daily.RIDDLES:
        assert question and answer
    for word, part_of_speech, definition in daily.WORDS:
        assert word and part_of_speech and definition


def test_a_full_year_of_dates_never_raises_and_always_returns_content():
    start = date(2026, 1, 1)
    for offset in range(366):
        day = start + timedelta(days=offset)
        assert daily.greeting_of_the_day(day)
        q, a = daily.riddle_of_the_day(day)
        assert q and a
        w, p, d = daily.word_of_the_day(day)
        assert w and p and d
        assert daily.history_flashback(day)
