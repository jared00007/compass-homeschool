"""The Khan mastery ladder -- Landon marks Familiar/Proficient/Mastered on a
Khan card, a parent confirms, and each confirmed tier (plus a mastered unit)
earns XP that flows into the same lifetime + weekly totals as everything else."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import compass.ui as ui
from compass import config, khan_mastery as km, xp
from compass.agents import khan_card
from compass.storage.db import Database


class _Rec:
    """A stand-in for streamlit that records every string it's shown and makes
    buttons/forms falsy, so a render can be exercised without a live app."""
    session_state: dict = {}

    def __init__(self):
        self.written: list[str] = []

    def __getattr__(self, _name):
        def rec(*a, **k):
            for x in list(a) + list(k.values()):
                if isinstance(x, str):
                    self.written.append(x)
            return self
        return rec

    def __getitem__(self, _i):
        return self

    def __iter__(self):
        return iter([self, self])

    def __enter__(self):
        return self

    def __exit__(self, *e):
        return False

    def __bool__(self):
        return False


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "km.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def _card(db, student, unit="Exponents", day=None):
    return khan_card.create_khan_card(
        db, student, subject="math", unit=unit, minutes=30, day_iso=day, quiz=[],
    )


# --- level helpers -----------------------------------------------------------

def test_levels_are_ordered_low_to_high():
    assert km.level_index("familiar") < km.level_index("proficient") < km.level_index("mastered")
    assert km.level_index(None) == -1            # 'nothing yet' sits below all
    assert km.next_level(None) == "familiar"
    assert km.next_level("proficient") == "mastered"
    assert km.next_level("mastered") is None     # nothing past the top


# --- claim + confirm on one card ---------------------------------------------

def test_claim_is_pending_until_a_parent_confirms(db, student):
    lid = _card(db, student)
    km.claim_mastery(db, lid, "proficient", on="2026-09-21")
    lesson = db.get_lesson(lid)
    assert km.pending_claim(lesson) == "proficient"   # waiting on a parent
    assert km.confirmed_level(lesson) is None          # nothing confirmed yet
    assert km.card_xp(lesson) == 0                      # a claim alone earns nothing


def test_confirm_climbs_every_tier_and_awards_their_xp(db, student):
    lid = _card(db, student)
    km.claim_mastery(db, lid, "proficient")
    awarded = km.confirm_mastery(db, lid, on="2026-09-23")   # one-tap: confirm the claim
    assert awarded == config.KHAN_MASTERY_XP["familiar"] + config.KHAN_MASTERY_XP["proficient"]
    lesson = db.get_lesson(lid)
    assert km.confirmed_level(lesson) == "proficient"
    assert km.pending_claim(lesson) is None            # claim satisfied, cleared
    assert km.card_xp(lesson) == awarded
    # Both tiers passed through are dated the confirm day, for the weekly strip.
    assert km.card_bumps(lesson) == [("2026-09-23", 5), ("2026-09-23", 5)]


def test_confirm_can_partially_grant_below_the_claim(db, student):
    lid = _card(db, student)
    km.claim_mastery(db, lid, "mastered")
    km.confirm_mastery(db, lid, "familiar", on="2026-09-20")   # only Familiar
    lesson = db.get_lesson(lid)
    assert km.confirmed_level(lesson) == "familiar"
    assert km.card_xp(lesson) == config.KHAN_MASTERY_XP["familiar"]
    assert km.pending_claim(lesson) == "mastered"      # the rest still pends


def test_confirm_is_monotonic_and_never_lowers(db, student):
    lid = _card(db, student)
    km.confirm_mastery(db, lid, "mastered", on="2026-09-20")
    assert km.confirm_mastery(db, lid, "familiar") == 0   # can't go back down
    lesson = db.get_lesson(lid)
    assert km.confirmed_level(lesson) == "mastered"
    # A full climb is worth every tier once.
    assert km.card_xp(lesson) == sum(config.KHAN_MASTERY_XP.values())


def test_reject_clears_a_claim_without_awarding(db, student):
    lid = _card(db, student)
    km.claim_mastery(db, lid, "mastered")
    km.reject_claim(db, lid)
    lesson = db.get_lesson(lid)
    assert km.pending_claim(lesson) is None and km.card_xp(lesson) == 0


def test_claim_at_or_below_confirmed_is_a_noop(db, student):
    lid = _card(db, student)
    km.confirm_mastery(db, lid, "proficient", on="2026-09-20")
    km.claim_mastery(db, lid, "familiar")              # already past this
    assert km.pending_claim(db.get_lesson(lid)) is None


def test_only_khan_cards_take_mastery(db, student):
    # A plain saved lesson under a different agent is rejected.
    lid = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="x",
        title="x", payload={}, strategy="s", rationale="r", metadata={},
    )
    with pytest.raises(ValueError):
        km.confirm_mastery(db, lid, "familiar")


# --- aggregates across cards -------------------------------------------------

def test_total_and_bumps_span_all_cards(db, student):
    a, b = _card(db, student, "Exponents"), _card(db, student, "Radicals")
    km.confirm_mastery(db, a, "mastered", on="2026-09-22")
    km.confirm_mastery(db, b, "familiar", on="2026-09-23")
    full = sum(config.KHAN_MASTERY_XP.values())
    assert km.total_mastery_xp(db, student["id"]) == full + config.KHAN_MASTERY_XP["familiar"]
    # Bumps carry their confirm dates for weekly attribution.
    dates = {d for d, _ in km.mastery_bumps(db, student["id"])}
    assert dates == {"2026-09-22", "2026-09-23"}


def test_pending_claims_lists_the_confirm_queue(db, student):
    a, b = _card(db, student), _card(db, student)
    km.claim_mastery(db, a, "proficient")
    # b has no claim -> not in the queue.
    queue = km.pending_claims(db, student["id"])
    assert [q["lesson"]["id"] for q in queue] == [a]
    assert queue[0]["claim"] == "proficient"


# --- unit rollups + the "master the unit" bonus ------------------------------

def _unit(db, student, name, n):
    res = khan_card.create_course(
        db, student, subject="math", course=name,
        lessons=[f"Skill {i}" for i in range(n)], minutes=30,
    )
    return res["created"]


def test_unit_summary_counts_levels_and_target(db, student):
    ids = _unit(db, student, "Exponents & radicals", 5)   # target = ceil(5*0.8) = 4
    for lid in ids[:3]:
        km.confirm_mastery(db, lid, "proficient", on="2026-09-21")
    summary = km.unit_summaries(db, student["id"])[0]
    assert summary["total"] == 5 and summary["target_count"] == 4
    assert summary["proficient_plus"] == 3 and summary["target_met"] is False
    assert summary["by_level"]["proficient"] == 3
    assert summary["xp_earned"] == 3 * (config.KHAN_MASTERY_XP["familiar"] + config.KHAN_MASTERY_XP["proficient"])


def test_unit_bonus_fires_when_the_target_is_crossed(db, student):
    ids = _unit(db, student, "Exponents & radicals", 5)   # target = 4
    for i, lid in enumerate(ids[:4]):
        km.confirm_mastery(db, lid, "proficient", on=f"2026-09-2{i + 1}")  # 21..24
    summary = km.unit_summaries(db, student["id"])[0]
    assert summary["target_met"] is True
    assert summary["crossed_on"] == "2026-09-24"          # the 4th to cross
    assert km.unit_bonuses(db, student["id"]) == [("2026-09-24", config.KHAN_UNIT_MASTERY_BONUS)]


def test_active_unit_prefers_the_one_scheduled_this_week(db, student):
    today = date.today()
    # An older unit, all in the backlog...
    _unit(db, student, "Old unit", 3)
    # ...and a newer one with a card planned for today.
    fresh = _unit(db, student, "This week's unit", 3)
    db.reschedule_lesson(fresh[0], today.isoformat())
    active = km.active_unit(db, student["id"], today=today)
    assert active["course"] == "This week's unit"


# --- integration with the XP totals ------------------------------------------

def test_mastery_xp_lands_on_the_lifetime_total(db, student):
    lid = _card(db, student)
    before = xp.total_xp(db, student["id"])
    km.confirm_mastery(db, lid, "mastered", on="2026-09-20")
    after = xp.total_xp(db, student["id"])
    assert after - before == sum(config.KHAN_MASTERY_XP.values())


def test_mastery_and_unit_bonus_land_on_the_weekly_bar(db, student):
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    ids = _unit(db, student, "Exponents", 5)              # target = 4
    # Take 4 skills to Proficient, all dated this Monday.
    for lid in ids[:4]:
        km.confirm_mastery(db, lid, "proficient", on=monday.isoformat())
    progress = xp.weekly_progress(db, student["id"], today=today)
    # Monday's column carries the 4 skills' tier XP (familiar+proficient each).
    per_prof = config.KHAN_MASTERY_XP["familiar"] + config.KHAN_MASTERY_XP["proficient"]
    assert progress.days[0].mastery_xp == 4 * per_prof
    assert progress.days[0].xp >= 4 * per_prof
    # ...and the unit bonus shows as extra credit this week.
    assert any(b.emoji == "🏆" and b.xp == config.KHAN_UNIT_MASTERY_BONUS
               for b in progress.bonus_items)
    assert progress.total >= 4 * per_prof + config.KHAN_UNIT_MASTERY_BONUS


# --- the marking UI (rendering only; the actions are covered above) -----------

def test_boost_shows_the_ladder_for_a_finished_card(db, student, monkeypatch):
    lid = _card(db, student, "Exponents")
    db.set_lesson_status(lid, "completed")
    rec = _Rec()
    monkeypatch.setattr(ui, "st", rec)
    ui.render_khan_mastery_boost(db, student)
    page = "\n".join(rec.written)
    assert "Level up your mastery" in page
    assert "Not rated yet" in page          # nothing confirmed on it yet
    assert "Exponents" in page              # the unit name groups it


def test_boost_shows_pending_when_he_has_claimed(db, student, monkeypatch):
    lid = _card(db, student, "Exponents")
    db.set_lesson_status(lid, "completed")
    km.claim_mastery(db, lid, "proficient")
    rec = _Rec()
    monkeypatch.setattr(ui, "st", rec)
    ui.render_khan_mastery_boost(db, student)
    assert "Waiting on a parent to confirm" in "\n".join(rec.written)


def test_confirmations_list_the_queue_with_the_award(db, student, monkeypatch):
    lid = _card(db, student, "Exponents")
    db.set_lesson_status(lid, "completed")
    km.claim_mastery(db, lid, "proficient")
    rec = _Rec()
    monkeypatch.setattr(ui, "st", rec)
    ui.render_khan_mastery_confirmations(db, student)
    page = "\n".join(rec.written)
    assert "Mastery to confirm" in page
    award = km.xp_to_reach(None, "proficient")
    assert f"Confirm Proficient (+{award})" in page


def test_confirmations_render_nothing_with_an_empty_queue(db, student, monkeypatch):
    _card(db, student)  # a card, but no claim
    rec = _Rec()
    monkeypatch.setattr(ui, "st", rec)
    ui.render_khan_mastery_confirmations(db, student)
    assert "Mastery to confirm" not in "\n".join(rec.written)


def test_unit_meter_shows_this_weeks_unit_and_progress(db, student, monkeypatch):
    today = date.today()
    ids = _unit(db, student, "Exponents & radicals", 5)
    db.reschedule_lesson(ids[0], today.isoformat())   # makes it this week's active unit
    km.confirm_mastery(db, ids[0], "proficient", on=today.isoformat())
    rec = _Rec()
    monkeypatch.setattr(ui, "st", rec)
    ui.render_khan_unit_mastery_meter(db, student, today.isoformat())
    page = "\n".join(rec.written)
    assert "This week’s unit" in page and "Exponents & radicals" in page
    assert "banked from mastery" in page


def test_unit_meter_is_silent_without_any_units(db, student, monkeypatch):
    _card(db, student)  # a standalone card, not part of a unit
    rec = _Rec()
    monkeypatch.setattr(ui, "st", rec)
    ui.render_khan_unit_mastery_meter(db, student, date.today().isoformat())
    assert "This week’s unit" not in "\n".join(rec.written)


def test_finishing_a_khan_card_awards_the_smaller_khan_rate(db, student):
    """A Khan card is a small single skill, so finishing one is worth the reduced
    XP_PER_KHAN_LESSON, not a full lesson's XP_PER_LESSON."""
    assert config.XP_PER_KHAN_LESSON < config.XP_PER_LESSON
    lid = _card(db, student)
    before = xp.total_xp(db, student["id"])
    db.mark_student_done(lid)
    assert xp.total_xp(db, student["id"]) - before == config.XP_PER_KHAN_LESSON


def test_khan_card_uses_the_smaller_rate_on_the_weekly_bar(db, student):
    today = date.today()
    lid = _card(db, student)
    db.mark_student_done(lid)                       # stamps student_done_on = today
    progress = xp.weekly_progress(db, student["id"], today=today)
    if today.weekday() < 5:                         # Mon-Fri: it lands on the bar
        day = progress.days[today.weekday()]
        assert day.lessons == 1 and day.khan_lessons == 1
        assert day.xp == config.XP_PER_KHAN_LESSON  # the reduced rate, not XP_PER_LESSON


def test_daily_due_lessons_tile_counts_khan_cards(db, student, monkeypatch):
    """Khan cards assigned to today count in the 'Lessons — N of M' Due-today
    tile, each on its own -- a day of Khan work shouldn't read as zero lessons."""
    today = date.today().isoformat()
    a = _card(db, student, "Exponents", day=today)
    _card(db, student, "Radicals", day=today)          # still to do
    db.submit_lesson(a)                                 # turned in -> counts as "in"
    rec = _Rec()
    monkeypatch.setattr(ui, "st", rec)
    ui.render_daily_due(db, student, today)
    assert "Lessons — 1 of 2 submitted" in "\n".join(rec.written)
