"""Backfilling the self-check gate onto existing lessons: the AI suggester
that reads an assignment's parts out of its own instructions, and the db
edit that writes a confirmed list onto an already-generated lesson."""

from __future__ import annotations

from compass.agents import checklist_suggest
from compass.storage.db import Database


def test_suggest_checklist_returns_cleaned_items(monkeypatch):
    monkeypatch.setattr(
        checklist_suggest,
        "generate_lesson",
        lambda **kwargs: {"checklist": ["  Answer all three  ", "", "Give an example"]},
    )
    assert checklist_suggest.suggest_checklist("Answer a, b, c and give an example.") == [
        "Answer all three",
        "Give an example",
    ]


def test_suggest_checklist_skips_the_model_for_blank_instructions(monkeypatch):
    calls = {"n": 0}

    def _fake(**kwargs):
        calls["n"] += 1
        return {"checklist": []}

    monkeypatch.setattr(checklist_suggest, "generate_lesson", _fake)
    assert checklist_suggest.suggest_checklist("   ") == []
    assert calls["n"] == 0, "no model call for empty instructions"


def test_set_activity_checklist_items_edits_payload_and_clears_stale_ticks(tmp_path):
    db = Database(tmp_path / "a.db")
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t", title="E",
        payload={"activities": [
            {"title": "Respond", "kind": "writing", "instructions": "x", "checklist": []}
        ]},
    )
    db.set_activity_checklist(lesson_id, 0, [True, True])  # ticks from an earlier list
    db.set_activity_checklist_items(lesson_id, 0, ["Part A", "Part B", "Part C"])
    lesson = db.get_lesson(lesson_id)
    db.close()

    assert lesson["payload"]["activities"][0]["checklist"] == ["Part A", "Part B", "Part C"]
    # Editing the list starts the ticks fresh rather than carrying stale ones.
    assert lesson["metadata"]["checklist_checked"] == {}
