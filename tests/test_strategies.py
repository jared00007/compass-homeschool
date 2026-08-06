"""The four next-topic strategies. All offline — no model call involved."""

from __future__ import annotations

import pytest

from compass.agents import get_agent
from compass.agents.framework import StudentContext
from compass.agents.strategies import ERAS
from compass.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def ctx_for(db, student, **inputs) -> StudentContext:
    return StudentContext(db=db, student_id=student["id"], student=student, inputs=inputs)


# --- Math: graph walk --------------------------------------------------------


def test_graph_walk_starts_at_a_root_skill(db, student):
    proposal = get_agent("math").propose_topic(ctx_for(db, student))
    assert not proposal.blocked
    assert proposal.metadata["skill_id"] in ("integer-operations", "fraction-operations")
    assert proposal.metadata["prerequisites"] == []


def test_graph_walk_will_not_unlock_a_skill_with_missing_prerequisites(db, student):
    db.set_mastery(student["id"], "integer-operations", "mastered")
    proposal = get_agent("math").propose_topic(ctx_for(db, student))
    skill_id = proposal.metadata["skill_id"]
    mastered = db.mastered_skills(student["id"])
    from compass.curriculum import math_graph

    assert not math_graph.missing_prerequisites(skill_id, mastered)


def test_graph_walk_blocks_a_forced_locked_skill_and_shows_the_path(db, student):
    proposal = get_agent("math").propose_topic(
        ctx_for(db, student, skill_id="pythagorean-theorem")
    )
    assert proposal.blocked
    assert "locked" in proposal.blocked_reason.lower()
    assert "Teaching order" in proposal.blocked_reason


def test_graph_walk_finishes_in_progress_work_before_unlocking_more(db, student):
    db.set_mastery(student["id"], "integer-operations", "mastered")
    db.set_mastery(student["id"], "fraction-operations", "in_progress", notes="signs are shaky")
    proposal = get_agent("math").propose_topic(ctx_for(db, student))
    assert proposal.metadata["skill_id"] == "fraction-operations"
    assert "in progress" in proposal.rationale.lower()
    assert any("signs are shaky" in line for line in proposal.context_lines)


def test_graph_walk_blocks_when_the_whole_graph_is_mastered(db, student):
    from compass.curriculum import math_graph

    for skill in math_graph.MATH_SKILLS:
        db.set_mastery(student["id"], skill.id, "mastered")
    proposal = get_agent("math").propose_topic(ctx_for(db, student))
    assert proposal.blocked
    assert "Algebra I" in proposal.blocked_reason


# --- Science: spiderweb ------------------------------------------------------


def test_spiderweb_seeds_a_new_thread_when_the_web_is_empty(db, student):
    proposal = get_agent("science").propose_topic(
        ctx_for(db, student, location="Mount Rainier")
    )
    assert proposal.strategy == "spiderweb_seed"
    assert proposal.metadata["seeding"] is True
    assert any("Mount Rainier" in line for line in proposal.context_lines)


def test_spiderweb_draws_from_open_branches_before_seeding(db, student):
    db.add_web_node(student["id"], "science", "glacial till and soil formation", depth=1)
    proposal = get_agent("science").propose_topic(ctx_for(db, student))
    assert proposal.strategy == "spiderweb"
    assert proposal.topic == "glacial till and soil formation"
    assert proposal.metadata["node_id"]


def test_spiderweb_prefers_a_branch_matching_the_current_location(db, student):
    db.add_web_node(student["id"], "science", "desert hydrology", location="Moab", depth=1)
    db.add_web_node(student["id"], "science", "temperate rainforest canopy", location="Hoh", depth=1)
    proposal = get_agent("science").propose_topic(ctx_for(db, student, location="Hoh"))
    assert proposal.topic == "temperate rainforest canopy"


def test_recording_a_result_marks_explored_and_grafts_branches(db, student):
    from compass.agents.strategies import record_spiderweb_result

    ctx = ctx_for(db, student, location="Hoh")
    proposal = get_agent("science").propose_topic(ctx)
    payload = {
        "topic": "nurse logs and seedling succession",
        "branches": [
            {"topic": "mycorrhizal networks", "rationale": "how the seedlings get fed"},
            {"topic": "decomposition rates by species", "rationale": "why some logs persist"},
        ],
    }
    record_spiderweb_result(ctx, proposal, payload, agent_key="science")

    explored = db.explored_topics(student["id"], "science")
    assert explored == ["nurse logs and seedling succession"]
    open_topics = {n["topic"] for n in db.unexplored_web_nodes(student["id"], "science")}
    assert open_topics == {"mycorrhizal networks", "decomposition rates by species"}


def test_spiderweb_does_not_duplicate_an_existing_branch(db, student):
    from compass.agents.strategies import record_spiderweb_result

    db.add_web_node(student["id"], "science", "mycorrhizal networks")
    ctx = ctx_for(db, student)
    proposal = get_agent("science").propose_topic(ctx)
    record_spiderweb_result(
        ctx,
        proposal,
        {"topic": "root", "branches": [{"topic": "Mycorrhizal Networks", "rationale": "dup"}]},
        agent_key="science",
    )
    topics = [n["topic"] for n in db.web_nodes(student["id"], "science")]
    assert sum(1 for t in topics if t.lower() == "mycorrhizal networks") == 1


# --- English: reading-tied ---------------------------------------------------


def test_english_blocks_without_a_current_book(db, student):
    proposal = get_agent("english").propose_topic(ctx_for(db, student))
    assert proposal.blocked
    assert "No book" in proposal.blocked_reason


def test_english_anchors_on_the_current_book(db, student):
    db.add_book(student["id"], "The Hobbit", "J.R.R. Tolkien", "6.6", 310)
    proposal = get_agent("english").propose_topic(ctx_for(db, student))
    assert not proposal.blocked
    assert proposal.metadata["book_title"] == "The Hobbit"
    assert any("The Hobbit" in line for line in proposal.context_lines)


def test_english_surfaces_vocabulary_that_is_due(db, student):
    db.add_book(student["id"], "The Hobbit")
    db.add_vocabulary(student["id"], "confusticate", "to confuse or bother")
    # Force it due by resetting the review date.
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now', '-1 day')")
    db.conn.commit()

    proposal = get_agent("english").propose_topic(ctx_for(db, student))
    assert "confusticate" in proposal.metadata["vocab_due"]
    assert any("confusticate" in line for line in proposal.context_lines)


def test_english_rotates_focus_areas(db, student):
    db.add_book(student["id"], "The Hobbit")
    first = get_agent("english").propose_topic(ctx_for(db, student))
    db.save_lesson(
        student["id"],
        "english",
        "reading",
        "t",
        "t",
        payload={},
        metadata={"focus": first.metadata["focus"]},
    )
    second = get_agent("english").propose_topic(ctx_for(db, student))
    assert second.metadata["focus"] != first.metadata["focus"]


def test_english_harvests_vocab_lines_into_the_deck(db, student):
    from compass.agents.strategies import record_english_result

    db.add_book(student["id"], "The Hobbit")
    ctx = ctx_for(db, student)
    proposal = get_agent("english").propose_topic(ctx)
    record_english_result(
        ctx,
        proposal,
        {
            "materials": [
                "A notebook",
                "VOCAB: burgle — to break in and steal",
                "VOCAB: prudent — careful and sensible",
            ]
        },
    )
    words = {v["word"] for v in db.list_vocabulary(student["id"])}
    assert words == {"burgle", "prudent"}


# --- History: timeline -------------------------------------------------------


def test_timeline_starts_at_the_first_uncovered_era(db, student):
    proposal = get_agent("history").propose_topic(ctx_for(db, student))
    assert proposal.metadata["era"] == ERAS[0][0]


def test_timeline_advances_past_covered_eras(db, student):
    db.save_lesson(
        student["id"],
        "history",
        "history",
        "t",
        "t",
        payload={},
        metadata={"era": ERAS[0][0]},
    )
    proposal = get_agent("history").propose_topic(ctx_for(db, student))
    assert proposal.metadata["era"] == ERAS[1][0]


def test_timeline_lets_location_override_the_sequence(db, student):
    proposal = get_agent("history").propose_topic(
        ctx_for(db, student, location="Whitman Mission, Walla Walla WA")
    )
    assert "Whitman Mission" in proposal.topic or "Whitman Mission" in proposal.rationale
    assert any("Whitman Mission" in line for line in proposal.context_lines)


# --- branch selection and pruning --------------------------------------------


def test_parent_can_pick_a_specific_branch(db, student):
    db.add_web_node(student["id"], "science", "first in queue", depth=1)
    wanted = db.add_web_node(student["id"], "science", "the one I actually want", depth=3)

    default = get_agent("science").propose_topic(ctx_for(db, student))
    assert default.topic == "first in queue"

    chosen = get_agent("science").propose_topic(ctx_for(db, student, node_id=wanted))
    assert chosen.topic == "the one I actually want"
    assert chosen.metadata["node_id"] == wanted


def test_picking_an_already_explored_branch_falls_back(db, student):
    node = db.add_web_node(student["id"], "science", "already done", depth=1)
    db.mark_web_node_explored(node)
    db.add_web_node(student["id"], "science", "still open", depth=1)

    proposal = get_agent("science").propose_topic(ctx_for(db, student, node_id=node))
    assert proposal.topic == "still open"


def test_history_can_follow_a_chosen_thread(db, student):
    wanted = db.add_web_node(student["id"], "history", "Celilo Falls and the dam", depth=1)
    proposal = get_agent("history").propose_topic(ctx_for(db, student, node_id=wanted))
    assert proposal.topic == "Celilo Falls and the dam"
    assert proposal.metadata["node_id"] == wanted


def test_a_new_seed_leaves_existing_branches_alone(db, student):
    """Starting something different must not silently discard the web."""
    db.add_web_node(student["id"], "science", "branch A", depth=1)
    db.add_web_node(student["id"], "science", "branch B", depth=1)

    proposal = get_agent("science").propose_topic(
        ctx_for(db, student, seed_topic="something completely different")
    )
    assert proposal.topic == "something completely different"

    still_open = {n["topic"] for n in db.unexplored_web_nodes(student["id"], "science")}
    assert still_open == {"branch A", "branch B"}


def test_dismissing_a_branch_keeps_its_children(db, student):
    parent = db.add_web_node(student["id"], "science", "parent branch", depth=1)
    child = db.add_web_node(student["id"], "science", "child branch", parent_id=parent, depth=2)

    db.delete_web_node(parent)

    remaining = {n["topic"] for n in db.unexplored_web_nodes(student["id"], "science")}
    assert remaining == {"child branch"}, "a grandchild topic is still a good lesson"
    assert db.get_web_node(child)["parent_id"] is None
