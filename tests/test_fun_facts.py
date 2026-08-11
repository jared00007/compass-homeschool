"""fact_of_the_day is the whole surface worth testing here: deterministic on
the date (not random -- the point is it holds steady across reruns), and
never crashes the home page with an empty list or a non-string entry."""

from __future__ import annotations

from datetime import date

from compass import fun_facts


def test_facts_list_is_non_empty_strings():
    assert len(fun_facts.FACTS) > 1
    assert all(isinstance(fact, str) and fact.strip() for fact in fun_facts.FACTS)


def test_facts_cover_a_full_year_without_repeating():
    """The point of sizing this list generously: a school year (or any
    365/366-day stretch) walks through fact_of_the_day without ever wrapping
    around to a fact it already showed."""
    assert len(fun_facts.FACTS) >= 366


def test_facts_have_no_duplicates():
    assert len(set(fun_facts.FACTS)) == len(fun_facts.FACTS)


def test_fact_of_the_day_is_deterministic_for_a_given_date():
    today = date(2026, 3, 14)
    assert fun_facts.fact_of_the_day(today) == fun_facts.fact_of_the_day(today)


def test_fact_of_the_day_rotates_across_dates():
    facts_seen = {fun_facts.fact_of_the_day(date(2026, 1, day)) for day in range(1, 15)}
    assert len(facts_seen) > 1


def test_fact_of_the_day_defaults_to_today():
    assert fun_facts.fact_of_the_day() == fun_facts.fact_of_the_day(date.today())
