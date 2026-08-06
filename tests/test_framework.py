"""The shared framework, especially its policing of subject-credit claims.

The compliance dashboard reads `subject_credits` straight from agent output, so
the normalization step is the last line of defence against an over-credited hour.
"""

from __future__ import annotations

import pytest

from compass.agents import get_agent
from compass.agents.framework import StudentContext, TopicProposal
from compass.storage.db import Database
from compass.subjects import SUBJECT_KEYS


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


def normalize(agent, payload, db, student, **inputs):
    ctx = ctx_for(db, student, **inputs)
    proposal = TopicProposal(topic="t", rationale="r", strategy="s")
    return agent._normalize(payload, proposal, ctx), payload


def test_all_four_agents_are_registered():
    from compass.agents import all_agents

    assert set(all_agents()) == {"math", "science", "english", "history"}


def test_agents_declare_distinct_strategies():
    from compass.agents import all_agents

    strategies = {key: agent.spec.next_topic for key, agent in all_agents().items()}
    assert len(set(strategies.values())) == 4, "each agent needs its own next-topic logic"


def test_out_of_scope_credit_is_dropped(db, student):
    """A math lesson may not quietly bill itself as art appreciation."""
    agent = get_agent("math")
    payload = {
        "activities": [{"minutes": 60}],
        "estimated_minutes": 60,
        "subject_credits": [
            {"subject": "math", "minutes": 60, "justification": ""},
            {"subject": "art_and_music", "minutes": 30, "justification": "we drew a graph"},
        ],
    }
    warnings, payload = normalize(agent, payload, db, student)
    credited = {c["subject"] for c in payload["subject_credits"]}
    assert credited == {"math"}
    assert any("outside this agent's scope" in w for w in warnings)


def test_in_scope_secondary_credit_is_kept(db, student):
    agent = get_agent("science")
    payload = {
        "activities": [{"minutes": 75}],
        "estimated_minutes": 75,
        "subject_credits": [
            {"subject": "science", "minutes": 75, "justification": ""},
            {"subject": "writing", "minutes": 25, "justification": "field journal entry"},
            {"subject": "art_and_music", "minutes": 15, "justification": "specimen sketch"},
        ],
    }
    warnings, payload = normalize(agent, payload, db, student)
    credited = {c["subject"]: c["minutes"] for c in payload["subject_credits"]}
    assert credited == {"science": 75, "writing": 25, "art_and_music": 15}


def test_credit_is_capped_at_the_lesson_length(db, student):
    agent = get_agent("science")
    payload = {
        "activities": [{"minutes": 60}],
        "estimated_minutes": 60,
        "subject_credits": [{"subject": "science", "minutes": 500, "justification": ""}],
    }
    warnings, payload = normalize(agent, payload, db, student)
    assert payload["subject_credits"][0]["minutes"] == 60
    assert any("Capped" in w for w in warnings)


def test_missing_primary_credit_is_added(db, student):
    agent = get_agent("science")
    payload = {
        "activities": [{"minutes": 60}],
        "estimated_minutes": 60,
        "subject_credits": [{"subject": "writing", "minutes": 20, "justification": ""}],
    }
    warnings, payload = normalize(agent, payload, db, student)
    credited = {c["subject"] for c in payload["subject_credits"]}
    assert "science" in credited
    assert any("primary" in w for w in warnings)


def test_unknown_subject_is_dropped(db, student):
    agent = get_agent("science")
    payload = {
        "activities": [{"minutes": 60}],
        "estimated_minutes": 60,
        "subject_credits": [
            {"subject": "science", "minutes": 60, "justification": ""},
            {"subject": "underwater_basket_weaving", "minutes": 30, "justification": ""},
        ],
    }
    warnings, payload = normalize(agent, payload, db, student)
    assert {c["subject"] for c in payload["subject_credits"]} == {"science"}
    assert any("unknown subject" in w for w in warnings)


def test_duplicate_credit_is_merged(db, student):
    agent = get_agent("science")
    payload = {
        "activities": [{"minutes": 60}],
        "estimated_minutes": 60,
        "subject_credits": [
            {"subject": "science", "minutes": 60, "justification": ""},
            {"subject": "science", "minutes": 30, "justification": ""},
        ],
    }
    warnings, payload = normalize(agent, payload, db, student)
    assert len(payload["subject_credits"]) == 1
    assert any("duplicate" in w for w in warnings)


def test_total_minutes_are_reconciled_to_the_activities(db, student):
    agent = get_agent("science")
    payload = {
        "activities": [{"minutes": 30}, {"minutes": 45}],
        "estimated_minutes": 120,
        "subject_credits": [{"subject": "science", "minutes": 75, "justification": ""}],
    }
    warnings, payload = normalize(agent, payload, db, student)
    assert payload["estimated_minutes"] == 75
    assert any("Adjusted total time" in w for w in warnings)


def test_math_cannot_claim_language_credit(db, student):
    """Restating a definition precisely is math instruction, not language.

    Observed in live testing: the Math agent billed 5 minutes of language for
    'restating the definition in his own words'. That's the primary instruction
    described in another subject's vocabulary.
    """
    agent = get_agent("math")
    assert "language" not in agent.allowed_subjects

    payload = {
        "activities": [{"minutes": 60}],
        "estimated_minutes": 60,
        "subject_credits": [
            {"subject": "math", "minutes": 60, "justification": ""},
            {
                "subject": "language",
                "minutes": 5,
                "justification": "restating the definition in his own words",
            },
        ],
    }
    warnings, payload = normalize(agent, payload, db, student)
    assert {c["subject"] for c in payload["subject_credits"]} == {"math"}
    assert any("outside this agent's scope" in w for w in warnings)


def test_credit_rules_demand_a_named_artifact(db, student):
    agent = get_agent("math")
    prompt = agent.build_system_prompt(ctx_for(db, student))
    assert "artifact" in prompt
    assert "not language instruction" in prompt
    assert "it is not occupational education" in prompt


def test_every_agent_only_allows_valid_wa_subjects():
    from compass.agents import all_agents

    for agent in all_agents().values():
        for subject in agent.allowed_subjects:
            assert subject in SUBJECT_KEYS, f"{agent.key} allows non-WA subject {subject}"


def test_system_prompt_names_the_allowed_credit_subjects(db, student):
    agent = get_agent("math")
    prompt = agent.build_system_prompt(ctx_for(db, student))
    assert "1,000 instructional hours" in prompt
    assert "Art & Music" not in prompt.split("You may additionally credit any of:")[1].split("\n")[0]
