"""Cost arithmetic. Wrong numbers here are worse than no numbers."""

from __future__ import annotations

from datetime import date

import pytest

from compass.costs import (
    PRICING,
    WEB_SEARCH_COST_PER_QUERY,
    build_cost_report,
    lesson_cost,
    rates_for,
)
from compass.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def usage(**overrides):
    base = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "web_searches": 0,
        "model": "claude-opus-5",
    }
    base.update(overrides)
    return base


def test_cost_of_a_million_tokens_matches_the_published_rate():
    assert lesson_cost(usage(input_tokens=1_000_000)) == pytest.approx(5.00)
    assert lesson_cost(usage(output_tokens=1_000_000)) == pytest.approx(25.00)


def test_cached_reads_are_a_tenth_of_input():
    full = lesson_cost(usage(input_tokens=1_000_000))
    cached = lesson_cost(usage(cache_read_input_tokens=1_000_000))
    assert cached == pytest.approx(full * 0.1)


def test_cache_writes_carry_the_premium():
    full = lesson_cost(usage(input_tokens=1_000_000))
    written = lesson_cost(usage(cache_creation_input_tokens=1_000_000))
    assert written == pytest.approx(full * 1.25)


def test_web_searches_are_billed_per_query_not_per_token():
    assert lesson_cost(usage(web_searches=3)) == pytest.approx(3 * WEB_SEARCH_COST_PER_QUERY)


def test_a_realistic_lesson_lands_where_expected():
    """~1.8k in, ~3.8k out on Opus 5 should be roughly a dime."""
    cost = lesson_cost(usage(input_tokens=1800, output_tokens=3800))
    assert 0.08 < cost < 0.13


def test_missing_usage_costs_nothing_rather_than_crashing():
    assert lesson_cost(None) == 0.0
    assert lesson_cost({}) == 0.0


def test_rates_tolerate_provider_prefixes_and_unknown_models():
    assert rates_for("anthropic.claude-opus-5") == PRICING["claude-opus-5"]
    assert rates_for("claude-sonnet-5") == PRICING["claude-sonnet-5"]
    # Unknown model must not crash the dashboard.
    assert rates_for("claude-something-new")["input"] > 0


def test_sonnet_is_cheaper_than_opus_for_the_same_work():
    opus = lesson_cost(usage(input_tokens=2000, output_tokens=4000))
    sonnet = lesson_cost(
        usage(input_tokens=2000, output_tokens=4000, model="claude-sonnet-5")
    )
    assert sonnet < opus


def _save(db, student, agent, created_on, **use):
    db.save_lesson(
        student["id"],
        agent,
        "science",
        "topic",
        "title",
        payload={"_usage": usage(**use)},
    )
    db.conn.execute(
        "UPDATE lessons SET created_at = ? WHERE id = (SELECT MAX(id) FROM lessons)",
        (f"{created_on} 12:00:00",),
    )
    db.conn.commit()


def test_report_aggregates_by_agent(db, student):
    _save(db, student, "math", "2026-03-01", input_tokens=1800, output_tokens=3800)
    _save(db, student, "math", "2026-03-02", input_tokens=1800, output_tokens=3800)
    _save(
        db, student, "science", "2026-03-03",
        input_tokens=10800, output_tokens=4800, web_searches=3,
    )

    report = build_cost_report(db, student["id"], "2026-03-01", "2026-03-31")

    assert report.measured_lessons == 3
    assert {e.agent for e in report.by_agent} == {"math", "science"}
    science = next(e for e in report.by_agent if e.agent == "science")
    math = next(e for e in report.by_agent if e.agent == "math")
    assert science.cost > math.per_lesson, "search-grounded lessons cost more"
    assert science.web_searches == 3
    assert report.total_cost == pytest.approx(math.cost + science.cost)


def test_report_excludes_lessons_outside_the_range(db, student):
    _save(db, student, "math", "2026-01-15", input_tokens=1000, output_tokens=1000)
    _save(db, student, "math", "2026-03-15", input_tokens=1000, output_tokens=1000)
    report = build_cost_report(db, student["id"], "2026-03-01", "2026-03-31")
    assert report.measured_lessons == 1


def test_lessons_without_usage_are_counted_but_not_priced(db, student):
    db.save_lesson(student["id"], "math", "math", "t", "t", payload={"title": "old"})
    report = build_cost_report(db, student["id"], "2000-01-01", "2100-01-01")
    assert report.unmeasured_lessons == 1
    assert report.measured_lessons == 0
    assert report.total_cost == 0.0
    assert report.total_lessons == 1


def test_projection_is_withheld_until_there_is_enough_history(db, student):
    for day in range(1, 4):
        _save(db, student, "math", f"2026-03-0{day}", input_tokens=1800, output_tokens=3800)
    report = build_cost_report(db, student["id"], "2026-03-01", "2026-03-31")
    assert report.projected_year_cost(today=date(2026, 3, 3)) is None


def test_projection_extrapolates_straight_line(db, student):
    for day in range(1, 11):
        _save(
            db, student, "math", f"2026-03-{day:02d}",
            input_tokens=1800, output_tokens=3800,
        )
    report = build_cost_report(db, student["id"], "2026-03-01", "2026-03-31")
    projected = report.projected_year_cost(today=date(2026, 3, 10))

    # 10 days of spend extrapolated across a 31-day window.
    assert projected == pytest.approx(report.total_cost * 31 / 10)


def test_empty_report_is_safe(db, student):
    report = build_cost_report(db, student["id"], "2026-03-01", "2026-03-31")
    assert report.total_cost == 0.0
    assert report.per_lesson == 0.0
    assert report.projected_year_cost() is None
