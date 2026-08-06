"""Compliance arithmetic — the part that must not be wrong."""

from __future__ import annotations

from datetime import date

import pytest

from compass import config
from compass.compliance import build_report
from compass.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def test_multi_subject_credit_does_not_inflate_total_hours(db, student):
    """The whole point: one 60-minute lesson credits three subjects but is one hour."""
    db.log_activity(
        student_id=student["id"],
        title="Waterfall field study",
        tier=config.TIER_CORE,
        primary_subject="science",
        minutes=60,
        subject_credits={"science": 60, "writing": 25, "art_and_music": 15},
        occurred_on="2026-09-15",
    )
    report = build_report(db, student["id"], "2026-09-01", "2027-08-31")

    assert report.total_minutes == 60, "total hours must come from elapsed time"
    credited = {s.key: s.minutes for s in report.subjects}
    assert credited["science"] == 60
    assert credited["writing"] == 25
    assert credited["art_and_music"] == 15
    assert sum(credited.values()) == 100, "per-subject credit legitimately exceeds elapsed time"


def test_uncovered_subjects_are_flagged(db, student):
    db.log_activity(
        student_id=student["id"],
        title="Algebra",
        tier=config.TIER_CORE,
        primary_subject="math",
        minutes=60,
        subject_credits={"math": 60},
        occurred_on="2026-09-15",
    )
    report = build_report(db, student["id"], "2026-09-01", "2027-08-31")

    assert report.subjects_covered == 1
    assert not report.all_subjects_covered
    assert len(report.uncovered_subjects) == 10
    assert any("eleven" in w for w in report.warnings)


def test_instructional_days_count_distinct_dates(db, student):
    for _ in range(3):
        db.log_activity(
            student_id=student["id"],
            title="Session",
            tier=config.TIER_CORE,
            primary_subject="math",
            minutes=30,
            subject_credits={"math": 30},
            occurred_on="2026-09-15",
        )
    db.log_activity(
        student_id=student["id"],
        title="Session",
        tier=config.TIER_CORE,
        primary_subject="math",
        minutes=30,
        subject_credits={"math": 30},
        occurred_on="2026-09-16",
    )
    report = build_report(db, student["id"], "2026-09-01", "2027-08-31")

    assert report.activity_count == 4
    assert report.instructional_days == 2
    assert report.total_minutes == 120


def test_tier3_counts_fully_but_warns_over_the_family_cap(db, student):
    db.set_setting("tier3_cap_percent", "20")
    db.log_activity(
        student_id=student["id"],
        title="Core work",
        tier=config.TIER_CORE,
        primary_subject="math",
        minutes=100,
        subject_credits={"math": 100},
        occurred_on="2026-09-15",
    )
    db.log_activity(
        student_id=student["id"],
        title="Game modding",
        tier=config.TIER_CHOICE,
        primary_subject="occupational_education",
        minutes=900,
        subject_credits={"occupational_education": 900},
        occurred_on="2026-09-16",
    )
    report = build_report(db, student["id"], "2026-09-01", "2027-08-31")

    # Counted fully — WA mandates no split.
    assert report.total_minutes == 1000
    assert report.tier3_minutes == 900
    # But flagged against the family guideline, mid-year, on share not absolute total.
    assert report.tier3_percent == 90.0
    assert report.tier3_over_cap
    assert any("Tier 3" in w for w in report.warnings)


def test_tier3_warning_waits_for_a_meaningful_sample(db, student):
    """One elective activity in September must not trip the balance warning."""
    db.set_setting("tier3_cap_percent", "20")
    db.log_activity(
        student_id=student["id"],
        title="Guitar",
        tier=config.TIER_CHOICE,
        primary_subject="art_and_music",
        minutes=90,
        subject_credits={"art_and_music": 90},
        occurred_on="2026-09-15",
    )
    report = build_report(db, student["id"], "2026-09-01", "2027-08-31")

    assert report.tier3_percent == 100.0
    assert not report.tier3_over_cap, "too little data to judge the year's balance"


def test_tier3_within_the_guideline_does_not_warn(db, student):
    db.set_setting("tier3_cap_percent", "20")
    db.log_activity(
        student_id=student["id"],
        title="Core work",
        tier=config.TIER_CORE,
        primary_subject="math",
        minutes=900,
        subject_credits={"math": 900},
        occurred_on="2026-09-15",
    )
    db.log_activity(
        student_id=student["id"],
        title="Coding",
        tier=config.TIER_CHOICE,
        primary_subject="occupational_education",
        minutes=100,
        subject_credits={"occupational_education": 100},
        occurred_on="2026-09-16",
    )
    report = build_report(db, student["id"], "2026-09-01", "2027-08-31")

    assert report.tier3_percent == 10.0
    assert not report.tier3_over_cap


def test_hour_target_defaults_to_the_wa_floor(db, student):
    report = build_report(db, student["id"], "2026-09-01", "2027-08-31")
    assert report.hour_target == config.WA_ANNUAL_HOURS
    assert report.day_target == config.WA_ANNUAL_DAYS


def test_pace_flags_an_unachievable_catch_up(db, student):
    """11 hours logged with days left is arithmetic, not a plan — say so."""
    db.log_activity(
        student_id=student["id"],
        title="Math",
        tier=config.TIER_CORE,
        primary_subject="math",
        minutes=60,
        subject_credits={"math": 60},
        occurred_on="2026-08-25",
    )
    report = build_report(db, student["id"], "2025-09-01", "2026-08-31")
    pace = report.pace(today=date(2026, 8, 25))

    assert pace["remaining_days"] == 6  # today is counted as elapsed
    assert pace["hours_per_week_needed"] > 100
    assert not pace["achievable"]


def test_pace_is_achievable_when_the_year_is_on_track(db, student):
    db.log_activity(
        student_id=student["id"],
        title="Term of work",
        tier=config.TIER_CORE,
        primary_subject="math",
        minutes=30000,  # 500 hours
        subject_credits={"math": 30000},
        occurred_on="2026-03-01",
    )
    report = build_report(db, student["id"], "2025-09-01", "2026-08-31")
    pace = report.pace(today=date(2026, 3, 1))

    assert report.total_hours == 500
    assert pace["achievable"]
    assert pace["hours_per_week_needed"] < 40


def test_activities_outside_the_range_are_excluded(db, student):
    db.log_activity(
        student_id=student["id"],
        title="Last year",
        tier=config.TIER_CORE,
        primary_subject="math",
        minutes=60,
        subject_credits={"math": 60},
        occurred_on="2025-05-01",
    )
    report = build_report(db, student["id"], "2026-09-01", "2027-08-31")
    assert report.total_minutes == 0
