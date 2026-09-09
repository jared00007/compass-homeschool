"""The life-skills planner.

The point of this module is what it *doesn't* do — it never picks a skill — so
most of these tests are about the boundary rather than the output. The rest check
that a plan gets the same credit policing a Tier 1 lesson does, since the hours
land in the same compliance record either way.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.agents import life_skills
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


@pytest.fixture()
def skill(db, student):
    skill_id = db.add_life_skill(
        student["id"],
        "Change a tire",
        category="Vehicle",
        description="Swaps the spare on unaided, torques the nuts in a star pattern.",
        credit_subject="occupational_education",
    )
    return next(s for s in db.list_life_skills(student["id"]) if s["id"] == skill_id)


def a_plan(**overrides):
    payload = {
        "title": "Changing a tire on the trailer",
        "overview": "Do it in the driveway before you have to do it on a shoulder.",
        "prep": "Park on level ground. Find the jack.",
        "materials": ["The spare", "Jack", "Lug wrench"],
        "steps": [
            {
                "title": "Break the nuts loose",
                "minutes": 20,
                "what_he_does": "Loosen each nut a quarter turn before jacking.",
                "what_you_do": "Demonstrate one, then hand it over and stay quiet.",
            },
            {
                "title": "Jack and swap",
                "minutes": 40,
                "what_he_does": "Raise the vehicle and swap the wheel.",
                "what_you_do": "Watch the jack point. Say nothing else.",
            },
        ],
        "watch_for": ["A jack on soft ground will sink."],
        "done_looks_like": "Spare on, nuts torqued in a star pattern, tools stowed.",
        "follow_ups": ["Next flat is his."],
        "subject_credits": [
            {"subject": "occupational_education", "minutes": 60, "justification": "The swap."}
        ],
        "estimated_minutes": 60,
        "_usage": {"input_tokens": 10, "output_tokens": 20},
    }
    payload.update(overrides)
    return payload


def generate(db, student, skill, payload, **kwargs):
    with patch("compass.agents.life_skills.generate_lesson", return_value=payload) as call:
        plan = life_skills.generate_plan(db, student, skill, minutes=60, **kwargs)
    return plan, call


# --- the boundary ------------------------------------------------------------


def test_the_planner_is_not_a_registered_agent():
    """It has no next-topic strategy because it never chooses a topic."""
    from compass.agents import all_agents

    assert life_skills.AGENT_KEY not in all_agents()


def test_the_prompt_forbids_proposing_a_different_skill(db, student, skill):
    _, call = generate(db, student, skill, a_plan())
    system = call.call_args.kwargs["system"]
    assert "Do not \\\npropose a different skill" in system or "propose a different skill" in system
    user = call.call_args.kwargs["user_prompt"]
    assert "Change a tire" in user
    assert "star pattern" in user, "the parent's own bar for 'done' has to reach the model"


def test_science_is_not_claimable(db, student, skill):
    """Cooking chemistry is a Science lesson; letting both claim it double-counts."""
    assert "science" not in life_skills.SECONDARY_CREDIT_SUBJECTS
    payload = a_plan(
        subject_credits=[
            {"subject": "occupational_education", "minutes": 60, "justification": "swap"},
            {"subject": "science", "minutes": 30, "justification": "leverage"},
        ]
    )
    plan, _ = generate(db, student, skill, payload)
    assert plan.credits == {"occupational_education": 60}
    assert any("outside this agent's scope" in w for w in plan.warnings)


def test_web_search_is_off_unless_asked_for(db, student, skill):
    _, call = generate(db, student, skill, a_plan())
    assert call.call_args.kwargs["use_web_search"] is False

    _, call = generate(db, student, skill, a_plan(), use_web_search=True)
    assert call.call_args.kwargs["use_web_search"] is True


# --- credits -----------------------------------------------------------------


def test_secondary_credits_cannot_exceed_the_session(db, student, skill):
    payload = a_plan(
        subject_credits=[
            {"subject": "occupational_education", "minutes": 60, "justification": "swap"},
            {"subject": "math", "minutes": 40, "justification": "torque figures"},
            {"subject": "health", "minutes": 40, "justification": "safety"},
        ]
    )
    plan, _ = generate(db, student, skill, payload)
    secondary = sum(m for s, m in plan.credits.items() if s != "occupational_education")
    assert secondary <= plan.total_minutes
    assert any("scaled down to fit" in w for w in plan.warnings)


def test_the_parents_chosen_subject_is_always_credited(db, student, skill):
    payload = a_plan(
        subject_credits=[{"subject": "math", "minutes": 30, "justification": "torque"}]
    )
    plan, _ = generate(db, student, skill, payload)
    assert plan.credits["occupational_education"] == 60


def test_total_time_is_reconciled_against_the_steps(db, student, skill):
    plan, _ = generate(db, student, skill, a_plan(estimated_minutes=200))
    assert plan.total_minutes == 60, "60 minutes of steps is 60 minutes, whatever it claimed"


def test_the_parents_subject_wins_even_outside_the_narrow_list(db, student, skill):
    """The starter checklist bills "write a polite email" as Language, and it's right.

    Silently rebilling it as occupational education because Language isn't on the
    planner's own shortlist would be the exact silent wrong answer this track is
    meant to avoid. The shortlist bounds what the model *adds*, not what the
    parent chose.
    """
    db.conn.execute(
        "UPDATE life_skills SET credit_subject = 'art_and_music' WHERE id = ?", (skill["id"],)
    )
    db.conn.commit()
    reloaded = next(s for s in db.list_life_skills(student["id"]) if s["id"] == skill["id"])

    assert life_skills.allowed_credits(reloaded)[0] == "art_and_music"
    plan, call = generate(db, student, reloaded, a_plan())
    assert plan.credits["art_and_music"] == 60, "the parent's subject is credited in full"
    enum = call.call_args.kwargs["schema"]["properties"]["subject_credits"]["items"][
        "properties"
    ]["subject"]["enum"]
    assert enum[0] == "art_and_music", "the schema has to offer it, or the model can't return it"


def test_a_nonsense_credit_subject_falls_back(db, student, skill):
    db.conn.execute(
        "UPDATE life_skills SET credit_subject = 'underwater_basketry' WHERE id = ?",
        (skill["id"],),
    )
    db.conn.commit()
    reloaded = next(s for s in db.list_life_skills(student["id"]) if s["id"] == skill["id"])
    assert life_skills.allowed_credits(reloaded)[0] == life_skills.DEFAULT_PRIMARY


# --- persistence -------------------------------------------------------------


def test_a_plan_is_stored_against_its_skill_and_costed(db, student, skill):
    plan, _ = generate(db, student, skill, a_plan())

    found = db.latest_life_skill_plan(student["id"], skill["id"])
    assert found["id"] == plan.lesson_id
    assert found["metadata"]["life_skill_id"] == skill["id"]

    start, end = db.school_year_bounds()
    usage = db.lesson_usage_between(student["id"], start, end)
    assert [u["agent"] for u in usage] == [life_skills.AGENT_KEY], "plans must show on the bill"


def test_the_newest_plan_wins(db, student, skill):
    generate(db, student, skill, a_plan(title="first attempt"))
    plan, _ = generate(db, student, skill, a_plan(title="second attempt"))
    found = db.latest_life_skill_plan(student["id"], skill["id"])
    assert found["id"] == plan.lesson_id
    assert found["payload"]["title"] == "second attempt"


def test_renaming_a_skill_does_not_orphan_its_plan(db, student, skill):
    generate(db, student, skill, a_plan())
    db.conn.execute(
        "UPDATE life_skills SET title = 'Change a tire (trailer)' WHERE id = ?", (skill["id"],)
    )
    db.conn.commit()
    assert db.latest_life_skill_plan(student["id"], skill["id"]) is not None


def test_plans_do_not_reach_the_students_home_page(db, student, skill):
    """The plan is written to the parent — 'stay quiet and let him fail' is not his."""
    generate(db, student, skill, a_plan())
    lessons = db.list_lessons(student["id"], limit=25)
    visible = [l for l in lessons if l["agent"] != life_skills.AGENT_KEY]
    assert lessons and not visible


# --- assigning a skill to a specific day, and Home's card for it ----------------


def _open_home(monkeypatch, db_path):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_a_skill_assigned_for_today_shows_up_on_home(monkeypatch, tmp_path):
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    skill_id = database.add_life_skill(s["id"], "Change a tire", "Vehicle")
    database.schedule_life_skill(skill_id, date.today().isoformat())
    database.close()

    at = _open_home(monkeypatch, db_path)
    text = " ".join(m.value for m in at.markdown)
    assert "Life Skills (1)" in text
    labels = [pl.label for pl in at.get("page_link")]
    assert any("Change a tire" in label for label in labels)


def test_scheduling_a_locked_skill_in_the_master_list_keeps_it_unlocked(monkeypatch, tmp_path):
    """Regression: `schedule_life_skill`'s automatic unlock used to get
    silently undone one rerun later. The "Unlocked" checkbox renders on the
    same run that scheduling flips `active` to 1, but that checkbox's own
    widget state was still the pre-scheduling `False` from before -- read as
    a real user click on the *next* run, it wrote the lock straight back."""
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    skill_id = database.add_life_skill(s["id"], "Read a map", "Navigation")
    # `add_life_skill` defaults to active=1 -- the bug this test pins down
    # only fires for a skill that starts *locked*, so it has to be
    # explicitly re-locked here rather than relying on that default.
    database.set_life_skill_active(skill_id, False)
    database.close()

    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(str(REPO_ROOT / "pages" / "6_Life_Skills.py"))
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]

    # The full 161-skill catalog auto-backfills onto any student who already
    # has one life_skill row (see `_backfill_life_skill_catalog`), so every
    # skill's "Assign this to a specific day" checkbox shares the same
    # label -- only `key`, which embeds the skill id, picks out this one.
    master_tab = [t for t in at.tabs if t.label == "Master list"][0]
    assign = [c for c in master_tab.checkbox if c.key == f"ls_assign_toggle_{skill_id}"][0]
    assign.set_value(True).run()
    assert not at.exception, [e.message for e in at.exception]

    # Ticking the box only opens the picker now -- it must not schedule today on
    # its own. The scheduling (and the unlock it triggers) happens on the button.
    unscheduled = next(
        r for r in Database(db_path).list_life_skills(s["id"]) if r["id"] == skill_id
    )
    assert unscheduled["scheduled_for"] is None

    [b for b in at.button if (b.key or "") == f"ls_assign_btn_{skill_id}"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    skill = next(row for row in database.list_life_skills(s["id"]) if row["id"] == skill_id)
    database.close()
    assert skill["scheduled_for"] is not None
    assert skill["active"] == 1  # scheduling still keeps it unlocked


def test_the_move_control_never_shows_in_the_students_checklist(monkeypatch, tmp_path):
    """Regression: render_life_skill_cards used to render the shared
    story-move control (backlog/schedule popover) on every checklist card
    unconditionally. Every *other* surface that control got wired into
    (Big Projects, Choice Topics, lesson review cards) already gated it on
    is_parent(), so this omission wasn't caught by copy-paste review. This
    is parent-only: he never gets to backlog or reschedule his own skill."""
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    database.add_life_skill(s["id"], "Read a map", "Navigation")
    database.close()

    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)  # student view: parent_unlocked left unset
    at.switch_page(str(REPO_ROOT / "pages" / "6_Life_Skills.py"))
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]

    move_keys = [c.key for c in at.checkbox if c.key and c.key.startswith("move_ls_")]
    assert move_keys == []


def test_home_life_skills_shows_the_empty_state_when_nothing_is_assigned(
    monkeypatch, tmp_path
):
    """The folded 'Due today' block always renders, but a family that never
    assigns a day should see its plain caught-up state, not a due item that
    was never actually assigned."""
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    database.add_life_skill(s["id"], "Bake bread", "Cooking")  # never assigned a day
    database.close()

    at = _open_home(monkeypatch, db_path)
    text = " ".join(m.value for m in at.markdown)
    assert "Life Skills (0)" in text
    labels = [pl.label for pl in at.get("page_link")]
    assert not any("Bake bread" in label for label in labels)


def test_due_today_links_out_to_morning_routine_and_check_in(monkeypatch, tmp_path):
    """Reported: "squeeze morning routine and daily check in on that due today
    list ... just links to the actual function." Both ride the Due-today block
    as tight tiles that link to their own pages -- not the full widget inline."""
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    database.ensure_default_student()
    auth.set_pin(database, "1234")
    database.close()

    at = _open_home(monkeypatch, db_path)
    text = " ".join(m.value for m in at.markdown)
    assert "Morning Routine — start your day" in text
    assert "Check-In — say how you're doing" in text
    # The tiles link out to the actual pages (page attr drops the numeric
    # prefix). Morning Routine has no sidebar entry, so its link can only come
    # from the Due-today tile.
    hrefs = [pl.page for pl in at.get("page_link")]
    assert "Morning_Routine" in hrefs
    assert "Check_In" in hrefs
    labels = [pl.label for pl in at.get("page_link")]
    assert "Do it now" in labels
    assert "Open Check-In" in labels


def test_due_today_reflects_a_completed_routine_and_check_in(monkeypatch, tmp_path):
    """Once he's done the routine and checked in, the tiles flip to their calm
    'done' state instead of still nagging him to start."""
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    today = date.today().isoformat()
    database.log_morning_routine(s["id"], today, "box_breathing")
    database.save_journal_entry(s["id"], today, "Good")
    database.close()

    at = _open_home(monkeypatch, db_path)
    text = " ".join(m.value for m in at.markdown)
    # Standardized "done for today ✅" across the Due-today tiles.
    assert "Morning Routine — done for today ✅" in text
    assert "Check-In — done for today ✅" in text
    # And the "check in again" link sits inline in the tile, not on its own line.
    assert 'href="Check_In"' in text


def test_home_merges_choice_topics_and_coding_into_the_daily_due_block(monkeypatch, tmp_path):
    """Reported directly: Life Skills and Choice Topics (and, once Coding
    folded into the same page too, Coding) used to each get their own
    fixed-column tile on Home, all three of them pointing at the exact same
    page -- "theres should really be one." The folded 'Due today' block now
    carries a compact count for Choice and Coding rather than a whole separate
    card apiece."""
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    topic_id = database.add_choice_topic(s["id"], "Learn guitar chords")
    database.set_choice_status(topic_id, "active")
    module_id = database.add_coding_module(s["id"], "Zzz Custom Test Module")
    database.schedule_coding_module(module_id, date.today().isoformat())
    database.close()

    at = _open_home(monkeypatch, db_path)
    captions = [c.value for c in at.caption]
    assert any("⭐ 1 Choice" in c for c in captions)
    assert any("💻 1 coding due" in c for c in captions)
    # No separate "Choice Topics" card heading anymore -- it's the same block.
    markdowns = [m.value for m in at.markdown]
    assert not any("Choice Topics" in m for m in markdowns)


def test_a_skill_assigned_for_later_shows_an_upcoming_hint_on_home(monkeypatch, tmp_path):
    """Reported directly: assigning a skill for tomorrow made it show up
    nowhere on Home at all until the day actually arrived. It should read
    as "coming up," the same way a lesson planned for later in the week
    already does, not just go quiet until its day."""
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    skill_id = database.add_life_skill(s["id"], "Read a map", "Navigation")
    # 7 days out is always past this week's Friday regardless of what day
    # "today" happens to be when this test runs -- lands in the "later
    # week" bucket reliably, without hardcoding a specific weekday.
    later = (date.today() + timedelta(days=7)).isoformat()
    database.schedule_life_skill(skill_id, later)
    database.close()

    at = _open_home(monkeypatch, db_path)
    text = " ".join(c.value for c in at.caption)
    assert "+1 skill(s) later" in text
    # Not due yet -- shouldn't show as a direct "assigned since/today" link.
    labels = [pl.label for pl in at.get("page_link")]
    assert not any("Read a map" in label for label in labels)


def test_a_life_skill_assigned_this_week_shows_on_the_student_board(monkeypatch, tmp_path):
    """His Home Board (the read-only sprint board that replaced the old week
    grid) surfaces a life skill a parent scheduled for a day this week, as a
    board card in that day's column -- same board_for_week the parent's own
    Board reads, just interactive=False."""
    from compass import weekly

    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    skill_id = database.add_life_skill(s["id"], "Change a tire", "Vehicle")
    # This week's Monday, not date.today(): guarantees a tracked weekday
    # column regardless of what day the suite runs on (a weekend date would
    # land in the Backlog, which the student board deliberately never shows).
    database.schedule_life_skill(skill_id, weekly.week_start().isoformat())
    database.close()

    at = _open_home(monkeypatch, db_path)
    board_button = [b for b in at.button if "Board" in (b.label or "")][0]
    board_button.click().run()
    assert not at.exception, [e.message for e in at.exception]
    assert any("Change a tire" in (e.label or "") for e in at.expander)


# --- completing a life skill credits occupational-education hours ------------
# Reported: "occupations edu shows 0 but he has completed 2 or 3 life skills."
# The bare `set_life_skill_done` only stamps `completed_on`; Compliance sums
# per-subject hours from logged activities, so a completed-but-unlogged skill
# showed nothing. `complete_life_skill` closes that gap.


def test_completing_a_skill_logs_occupational_education_hours(db, student, skill):
    db.complete_life_skill(skill["id"])

    done = next(s for s in db.list_life_skills(student["id"]) if s["id"] == skill["id"])
    assert done["completed_on"]  # still marks it done

    activities = db.list_activities(student["id"])
    occ = [a for a in activities if a["credits"].get("occupational_education")]
    assert len(occ) == 1
    assert occ[0]["credits"]["occupational_education"] == config.LIFE_SKILL_DEFAULT_MINUTES
    assert occ[0]["source"] == "life_skills"


def test_completing_a_skill_is_idempotent(db, student, skill):
    db.complete_life_skill(skill["id"])
    db.complete_life_skill(skill["id"])  # re-click must not double-count

    activities = db.list_activities(student["id"])
    occ = [a for a in activities if a["credits"].get("occupational_education")]
    assert len(occ) == 1


def test_completing_honours_an_explicit_minutes_override(db, student, skill):
    db.complete_life_skill(skill["id"], minutes=90)

    activities = db.list_activities(student["id"])
    occ = [a for a in activities if a["credits"].get("occupational_education")]
    assert occ[0]["credits"]["occupational_education"] == 90


def test_completing_credits_the_skills_own_subject(db, student):
    skill_id = db.add_life_skill(
        student["id"], "Balance a budget", category="Money",
        credit_subject="mathematics",
    )
    db.complete_life_skill(skill_id)

    activities = db.list_activities(student["id"])
    credited = [a for a in activities if a["credits"].get("mathematics")]
    assert len(credited) == 1
    assert credited[0]["credits"]["mathematics"] == config.LIFE_SKILL_DEFAULT_MINUTES


def test_the_log_time_form_path_does_not_double_count(db, student, skill):
    """The 'Log time on a life skill' form logs its own hours and then marks the
    skill done via the bare setter. If a parent later hits the quick 'mark
    complete' button on that already-done skill, no extra hours are added."""
    db.log_activity(
        student_id=student["id"], title=skill["title"],
        tier=config.TIER_LIFE_SKILLS, primary_subject="occupational_education",
        minutes=60, subject_credits={"occupational_education": 60},
        source="life_skills",
    )
    db.set_life_skill_done(skill["id"], True)

    db.complete_life_skill(skill["id"])  # already done -> no second credit

    activities = db.list_activities(student["id"])
    occ = [a for a in activities if a["credits"].get("occupational_education")]
    assert len(occ) == 1
    assert occ[0]["credits"]["occupational_education"] == 60


# --- backfilling occupational-education hours for older completions ----------
# Reported repeatedly: "occupational education 0 but we've done ~3 life skills."
# complete_life_skill logs hours going forward, but skills marked done before
# that never got them. _backfill_life_skill_credits (run in migrate) fixes it.


def test_backfill_credits_a_skill_marked_done_before_hours_were_logged(db, student, skill):
    # Simulate a pre-fix completion: done, but no activity ever logged.
    db.set_life_skill_done(skill["id"], True)
    assert not [a for a in db.list_activities(student["id"]) if a["credits"]]

    db._backfill_life_skill_credits()

    occ = [a for a in db.list_activities(student["id"]) if a["credits"].get("occupational_education")]
    assert len(occ) == 1
    assert occ[0]["credits"]["occupational_education"] == config.LIFE_SKILL_DEFAULT_MINUTES
    # credited on the day it was actually completed, not today
    assert occ[0]["occurred_on"] == db.list_life_skills(student["id"])[0]["completed_on"]


def test_backfill_is_idempotent(db, student, skill):
    db.set_life_skill_done(skill["id"], True)
    db._backfill_life_skill_credits()
    db._backfill_life_skill_credits()  # a second app open must not re-credit
    occ = [a for a in db.list_activities(student["id"]) if a["credits"].get("occupational_education")]
    assert len(occ) == 1


def test_backfill_skips_a_skill_that_already_logged_real_hours(db, student, skill):
    # The "Log time" form logged 60 real minutes and marked it done.
    db.log_activity(
        student_id=student["id"], title=skill["title"], tier=config.TIER_LIFE_SKILLS,
        primary_subject="occupational_education", minutes=60,
        subject_credits={"occupational_education": 60}, source="life_skills",
    )
    db.set_life_skill_done(skill["id"], True)

    db._backfill_life_skill_credits()  # must not add a second, default block

    occ = [a for a in db.list_activities(student["id"]) if a["credits"].get("occupational_education")]
    assert len(occ) == 1
    assert occ[0]["credits"]["occupational_education"] == 60


def test_backfill_leaves_an_uncompleted_skill_alone(db, student, skill):
    db._backfill_life_skill_credits()  # skill is not completed
    assert not [a for a in db.list_activities(student["id"]) if a["credits"]]


# --- the submit -> approve gate ---------------------------------------------------
# Reported: "landon accidentally completed two he did not do but i cant figure
# out how to uncheck them. these should also need parent approval upon
# completion and can be sent back for more work."


def _reload(db, student_id, skill_id):
    return next(s for s in db.list_life_skills(student_id) if s["id"] == skill_id)


def test_marking_done_submits_and_logs_nothing_until_approved(db, student, skill):
    db.submit_life_skill(skill["id"])
    row = _reload(db, student["id"], skill["id"])
    assert row["status"] == config.LIFE_SKILL_SUBMITTED
    assert not row["completed_on"]  # not earned yet
    # Nothing counts toward Occupational Education until a parent approves.
    assert not [a for a in db.list_activities(student["id"]) if a["credits"]]


def test_approving_a_submitted_skill_earns_it_and_logs_hours(db, student, skill):
    db.submit_life_skill(skill["id"])
    db.complete_life_skill(skill["id"])  # the parent's Approve
    row = _reload(db, student["id"], skill["id"])
    assert row["status"] == config.LIFE_SKILL_APPROVED
    assert row["completed_on"]
    assert row["logged_activity_id"]  # the hours row is tracked for a clean undo
    occ = [a for a in db.list_activities(student["id"]) if a["credits"].get("occupational_education")]
    assert len(occ) == 1


def test_sending_a_skill_back_records_feedback_and_no_hours(db, student, skill):
    db.submit_life_skill(skill["id"])
    db.send_life_skill_back(skill["id"], "Do the torque step again, in a star pattern.")
    row = _reload(db, student["id"], skill["id"])
    assert row["status"] == config.LIFE_SKILL_NEEDS_REVISION
    assert row["feedback"] == "Do the torque step again, in a star pattern."
    assert not row["completed_on"]
    assert not [a for a in db.list_activities(student["id"]) if a["credits"]]


def test_turning_it_in_again_clears_the_send_back_note(db, student, skill):
    db.submit_life_skill(skill["id"])
    db.send_life_skill_back(skill["id"], "Redo the torque step.")
    db.submit_life_skill(skill["id"])  # he answers it
    row = _reload(db, student["id"], skill["id"])
    assert row["status"] == config.LIFE_SKILL_SUBMITTED
    assert not row["feedback"]


def test_undo_clears_the_badge_and_takes_back_the_hours(db, student, skill):
    db.complete_life_skill(skill["id"])  # earned + hours
    assert [a for a in db.list_activities(student["id"]) if a["credits"]]

    db.reopen_life_skill(skill["id"])
    row = _reload(db, student["id"], skill["id"])
    assert not row["completed_on"]
    assert row["status"] == config.LIFE_SKILL_ASSIGNED
    # The hours approval logged are gone -- Compliance no longer overcounts.
    assert not [a for a in db.list_activities(student["id"]) if a["credits"]]


def test_undo_removes_hours_for_a_legacy_completion_with_no_tracked_row(db, student, skill):
    """A skill finished before the gate existed has no logged_activity_id, but
    undo still takes back its single life-skills hours row."""
    db.set_life_skill_done(skill["id"], True)   # legacy stamp, no tracked id
    db._backfill_life_skill_credits()           # the block of hours it earned
    assert [a for a in db.list_activities(student["id"]) if a["credits"]]

    db.reopen_life_skill(skill["id"])
    assert not [a for a in db.list_activities(student["id"]) if a["credits"]]
    assert not _reload(db, student["id"], skill["id"])["completed_on"]


def test_undo_leaves_ambiguous_hours_alone(db, student, skill):
    """Two separately logged blocks for the same skill can't be told apart
    without a tracked id, so undo clears the badge but never guesses which hours
    to strip -- a parent's real logged time is not swept away by an accident undo."""
    for _ in range(2):
        db.log_activity(
            student_id=student["id"], title=skill["title"], tier=config.TIER_LIFE_SKILLS,
            primary_subject="occupational_education", minutes=60,
            subject_credits={"occupational_education": 60}, source="life_skills",
        )
    db.set_life_skill_done(skill["id"], True)

    db.reopen_life_skill(skill["id"])
    row = _reload(db, student["id"], skill["id"])
    assert not row["completed_on"]  # badge cleared
    # Both real blocks are still there -- untouched.
    occ = [a for a in db.list_activities(student["id"]) if a["credits"].get("occupational_education")]
    assert len(occ) == 2


def test_an_old_completed_skill_migrates_to_approved(tmp_path):
    """A family whose skills were finished before the status column existed:
    the migration normalizes them to 'approved' so they don't reappear as
    unstarted, and stay untouched by the new gate."""
    db_path = tmp_path / "old.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    sid = database.add_life_skill(s["id"], "Change a tire", "Vehicle")
    # Simulate a pre-gate completion by writing completed_on with the status
    # left at the column default a fresh migration would leave it.
    database.conn.execute(
        "UPDATE life_skills SET completed_on = '2026-01-02', status = 'assigned' WHERE id = ?",
        (sid,),
    )
    database.conn.commit()
    database.close()

    reopened = Database(db_path)  # triggers migrate() again
    row = next(x for x in reopened.list_life_skills(s["id"]) if x["id"] == sid)
    reopened.close()
    assert row["status"] == config.LIFE_SKILL_APPROVED


# --- the gate, end to end through the Life Skills page ----------------------------

LIFE_SKILLS_PATH = str(REPO_ROOT / "pages" / "6_Life_Skills.py")


def _open_life_skills(monkeypatch, db_path, *, as_parent):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    if as_parent:
        at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(LIFE_SKILLS_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_student_mark_done_submits_rather_than_completing(monkeypatch, tmp_path):
    """His "Mark done" no longer counts the skill outright -- it turns it in for
    a parent to approve, so an accidental tick never silently counts."""
    db_path = tmp_path / "ls.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    skill_id = database.add_life_skill(s["id"], "Change a tire", "Vehicle")
    database.close()

    at = _open_life_skills(monkeypatch, db_path, as_parent=False)
    [b for b in at.button if b.key == f"ls_done_{skill_id}"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    row = next(x for x in database.list_life_skills(s["id"]) if x["id"] == skill_id)
    database.close()
    assert row["status"] == config.LIFE_SKILL_SUBMITTED
    assert not row["completed_on"]


def test_parent_master_list_approves_a_submitted_skill(monkeypatch, tmp_path):
    db_path = tmp_path / "ls.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    skill_id = database.add_life_skill(s["id"], "Change a tire", "Vehicle")
    database.submit_life_skill(skill_id)
    database.close()

    at = _open_life_skills(monkeypatch, db_path, as_parent=True)
    [b for b in at.button if b.label == "✅ Approve"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    row = next(x for x in database.list_life_skills(s["id"]) if x["id"] == skill_id)
    occ = [a for a in database.list_activities(s["id"]) if a["credits"].get("occupational_education")]
    database.close()
    assert row["completed_on"]
    assert row["status"] == config.LIFE_SKILL_APPROVED
    assert len(occ) == 1  # approval logged the hours


def test_submitted_life_skills_lists_only_ones_awaiting_approval(db, student):
    a = db.add_life_skill(student["id"], "Change a tire", "Vehicle")
    db.add_life_skill(student["id"], "Bake bread", "Cooking")  # stays assigned
    db.submit_life_skill(a)
    assert [s["id"] for s in db.submitted_life_skills(student["id"])] == [a]
    db.complete_life_skill(a)  # approved -> no longer waiting
    assert db.submitted_life_skills(student["id"]) == []


def test_home_due_today_shows_a_lesson_submission_count(monkeypatch, tmp_path):
    """A compact 'N of M submitted' for today's core-subject lessons, where M
    is however many are actually relevant today."""
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    today = date.today().isoformat()
    # Math: turned in -> counts toward "submitted".
    m = database.save_lesson(
        student_id=s["id"], agent="math", subject="math", topic="t",
        title="Math", payload={"title": "Math", "activities": []},
        metadata={"planned_for": today},
    )
    database.submit_lesson(m)
    # English: due today, not turned in yet.
    database.save_lesson(
        student_id=s["id"], agent="english", subject="english", topic="t",
        title="Eng", payload={"title": "Eng", "activities": []},
        metadata={"planned_for": today},
    )
    database.close()

    at = _open_home(monkeypatch, db_path)
    text = " ".join(m.value for m in at.markdown)
    assert "Lessons — 1 of 2 submitted" in text


def test_home_due_today_shows_a_scheduled_travel_entry(monkeypatch, tmp_path):
    """A travel journal entry assigned for today shows in Due today, so anything
    scheduled for a day is trackable there."""
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    entry_id = database.add_travel_entry(
        s["id"], "Wyoming", date.today().isoformat(), title="Yellowstone", status="planned"
    )
    database.schedule_travel_entry(entry_id, date.today().isoformat())
    database.close()

    at = _open_home(monkeypatch, db_path)
    text = " ".join(m.value for m in at.markdown)
    assert "Travel journal (1) to write" in text
    labels = [pl.label for pl in at.get("page_link")]
    assert any("Yellowstone" in label for label in labels)


def test_home_words_tile_greens_once_he_is_done_for_the_day(monkeypatch, tmp_path):
    """The words tile shows a green check when he's marked words done for the
    day, even if some were still technically due."""
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    database.add_vocabulary(s["id"], "prudent", "careful")  # a due word exists
    database.mark_vocab_reviewed(s["id"], date.today().isoformat())
    database.close()

    at = _open_home(monkeypatch, db_path)
    text = " ".join(m.value for m in at.markdown)
    assert "Words — done for today" in text


def test_home_life_skill_tile_greens_when_handed_in_for_approval(monkeypatch, tmp_path):
    """A skill he's marked done reads as his part finished (green, waiting on a
    parent) rather than still nagging him as due."""
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    skill_id = database.add_life_skill(s["id"], "Change a tire", "Vehicle")
    database.schedule_life_skill(skill_id, date.today().isoformat())
    database.submit_life_skill(skill_id)
    database.close()

    at = _open_home(monkeypatch, db_path)
    text = " ".join(m.value for m in at.markdown)
    blob = text + " ".join(c.value for c in at.caption)
    assert "Life Skills — done for today ✅" in text  # his part is done
    assert "waiting on your parent" in blob            # and it's pending approval
    assert "Life Skills (1) due" not in text           # not nagged as still to do


def test_parent_master_list_undo_unchecks_a_completed_skill(monkeypatch, tmp_path):
    """The reported fix, through the UI: a parent can uncheck a skill that was
    marked done, and the hours it logged come back off."""
    db_path = tmp_path / "ls.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    skill_id = database.add_life_skill(s["id"], "Change a tire", "Vehicle")
    database.complete_life_skill(skill_id)  # earned + hours logged
    database.close()

    at = _open_life_skills(monkeypatch, db_path, as_parent=True)
    [b for b in at.button if b.key == f"ls_undo_{skill_id}"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    row = next(x for x in database.list_life_skills(s["id"]) if x["id"] == skill_id)
    credited = [a for a in database.list_activities(s["id"]) if a["credits"]]
    database.close()
    assert not row["completed_on"]
    assert row["status"] == config.LIFE_SKILL_ASSIGNED
    assert credited == []  # the accidental hours are gone
