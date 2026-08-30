"""The coding-module build-guide planner (compass.agents.coding).

Same shape as test_life_skills.py's own planner coverage -- credit policing
and persistence mirror that module almost exactly, since both share
compass.agents.credits.normalize_credits. The one real difference: a
life-skill plan is written to the parent (they run the session); a coding
build guide is written to the student (he builds it himself), so unlike
life skills' own "plans do not reach the student's home page" guarantee,
this one has to actually reach him -- see test_the_build_guide_shows_up_on_
his_own_checklist_card below.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from compass.agents import coding
from compass.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


@pytest.fixture()
def module(db, student):
    module_id = db.add_coding_module(
        student["id"],
        "Build a choose-your-own-adventure text game",
        category="Games You Can Actually Play",
        description="The player picks an option and the story branches.",
        credit_subject="occupational_education",
    )
    return next(m for m in db.list_coding_modules(student["id"]) if m["id"] == module_id)


def a_plan(**overrides):
    payload = {
        "title": "Choose-your-own-adventure text game",
        "overview": "A loop that prints a scene, reads a choice, and branches.",
        "concepts": [
            {"name": "Functions", "explanation": "A named block of code you can call by name."},
            {"name": "Dictionaries", "explanation": "Look up a value by a key instead of a position."},
        ],
        "steps": [
            {
                "title": "Print the first scene and read a choice",
                "minutes": 20,
                "instructions": "Print the opening scene, then read what he types.",
                "example": "choice = input('> ')",
            },
            {
                "title": "Branch on the choice",
                "minutes": 40,
                "instructions": "Use an if/elif chain to print a different next scene per choice.",
                "example": "if choice == 'left':\n    print('You went left.')",
            },
        ],
        "common_mistakes": ["Forgetting .lower() so 'Left' and 'left' are treated differently."],
        "done_looks_like": "Running it prints a scene, takes input, and shows a different scene next.",
        "stretch_goals": ["Track an inventory dict across scenes."],
        "parent_note": "Nothing.",
        "subject_credits": [
            {"subject": "occupational_education", "minutes": 60, "justification": "The build itself."}
        ],
        "estimated_minutes": 60,
        "_usage": {"input_tokens": 10, "output_tokens": 20},
    }
    payload.update(overrides)
    return payload


def generate(db, student, module, payload, **kwargs):
    with patch("compass.agents.coding.generate_lesson", return_value=payload) as call:
        plan = coding.generate_plan(db, student, module, minutes=60, **kwargs)
    return plan, call


# --- the boundary --------------------------------------------------------------


def test_the_planner_is_not_a_registered_agent():
    """It has no next-topic strategy because it never chooses a module."""
    from compass.agents import all_agents

    assert coding.AGENT_KEY not in all_agents()


def test_the_prompt_forbids_proposing_a_different_module(db, student, module):
    _, call = generate(db, student, module, a_plan())
    system = call.call_args.kwargs["system"]
    assert "propose a different module" in system
    user = call.call_args.kwargs["user_prompt"]
    assert "choose-your-own-adventure text game" in user


def test_web_search_is_always_off(db, student, module):
    """Unlike life_skills, there's no 'look things up first' option here --
    a build guide doesn't need current facts the way a permit fee might."""
    _, call = generate(db, student, module, a_plan())
    assert call.call_args.kwargs["use_web_search"] is False


# --- credits ---------------------------------------------------------------------


def test_secondary_credits_cannot_exceed_the_session(db, student, module):
    payload = a_plan(
        subject_credits=[
            {"subject": "occupational_education", "minutes": 60, "justification": "swap"},
            {"subject": "math", "minutes": 40, "justification": "score tracking"},
            {"subject": "art_and_music", "minutes": 40, "justification": "layout"},
        ]
    )
    plan, _ = generate(db, student, module, payload)
    secondary = sum(m for s, m in plan.credits.items() if s != "occupational_education")
    assert secondary <= plan.total_minutes
    assert any("scaled down to fit" in w for w in plan.warnings)


def test_the_parents_chosen_subject_is_always_credited(db, student, module):
    payload = a_plan(
        subject_credits=[{"subject": "math", "minutes": 30, "justification": "score"}]
    )
    plan, _ = generate(db, student, module, payload)
    assert plan.credits["occupational_education"] == 60


def test_total_time_is_reconciled_against_the_steps(db, student, module):
    plan, _ = generate(db, student, module, a_plan(estimated_minutes=200))
    assert plan.total_minutes == 60, "60 minutes of steps is 60 minutes, whatever it claimed"


def test_the_parents_subject_wins_even_outside_the_narrow_list(db, student, module):
    db.conn.execute(
        "UPDATE coding_modules SET credit_subject = 'reading' WHERE id = ?", (module["id"],)
    )
    db.conn.commit()
    reloaded = next(m for m in db.list_coding_modules(student["id"]) if m["id"] == module["id"])

    assert coding.allowed_credits(reloaded)[0] == "reading"
    plan, call = generate(db, student, reloaded, a_plan())
    assert plan.credits["reading"] == 60
    enum = call.call_args.kwargs["schema"]["properties"]["subject_credits"]["items"][
        "properties"
    ]["subject"]["enum"]
    assert enum[0] == "reading", "the schema has to offer it, or the model can't return it"


def test_a_nonsense_credit_subject_falls_back(db, student, module):
    db.conn.execute(
        "UPDATE coding_modules SET credit_subject = 'underwater_basketry' WHERE id = ?",
        (module["id"],),
    )
    db.conn.commit()
    reloaded = next(m for m in db.list_coding_modules(student["id"]) if m["id"] == module["id"])
    assert coding.allowed_credits(reloaded)[0] == coding.DEFAULT_PRIMARY


# --- persistence -------------------------------------------------------------------


def test_a_plan_is_stored_against_its_module_and_costed(db, student, module):
    plan, _ = generate(db, student, module, a_plan())

    found = db.latest_coding_plan(student["id"], module["id"])
    assert found["id"] == plan.lesson_id
    assert found["metadata"]["coding_module_id"] == module["id"]

    start, end = db.school_year_bounds()
    usage = db.lesson_usage_between(student["id"], start, end)
    assert [u["agent"] for u in usage] == [coding.AGENT_KEY], "plans must show on the bill"


def test_the_newest_plan_wins(db, student, module):
    generate(db, student, module, a_plan(title="first attempt"))
    plan, _ = generate(db, student, module, a_plan(title="second attempt"))
    found = db.latest_coding_plan(student["id"], module["id"])
    assert found["id"] == plan.lesson_id
    assert found["payload"]["title"] == "second attempt"


def test_renaming_a_module_does_not_orphan_its_plan(db, student, module):
    generate(db, student, module, a_plan())
    db.conn.execute(
        "UPDATE coding_modules SET title = 'Renamed module' WHERE id = ?", (module["id"],)
    )
    db.conn.commit()
    assert db.latest_coding_plan(student["id"], module["id"]) is not None


def test_the_build_guide_shows_up_on_his_own_checklist_card(monkeypatch, db, student, module):
    """The whole point: unlike a life-skill plan (parent-only), this one has
    to reach him -- it's the actual "how to do this" content the checklist
    used to be missing. render_coding_module_cards renders it inline once a
    plan exists, gated on nothing but the plan existing at all -- this is
    the student view (is_parent() patched False), same pattern
    test_auth.py's own redaction tests use."""
    import compass.ui as ui

    generate(db, student, module, a_plan())
    db.set_coding_module_active(module["id"], True)
    modules = db.list_coding_modules(student["id"])

    written: list[str] = []

    class Recorder:
        def __getattr__(self, _name):
            def record(*args, **kwargs):
                for arg in args:
                    if isinstance(arg, str):
                        written.append(arg)
                return Recorder()
            return record

        def __getitem__(self, _index):
            return Recorder()

        def __iter__(self):
            return iter([Recorder(), Recorder()])

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(ui, "st", Recorder())
    monkeypatch.setattr(ui, "is_parent", lambda: False)
    ui.render_coding_module_cards(db, modules, can_edit=False)

    page = "\n".join(written)
    assert "How to build this" in page
    assert "choice = input" in page
