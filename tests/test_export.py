"""Rendering a lesson to a printable Word doc.

This is a parent-only export -- callers gate access, not this module -- so the
thing worth pinning is simpler: does it actually produce a valid .docx with the
content that's on screen, including the assessment and quiz answer key, and
does it survive lessons where optional sections (video, quiz, credits) are
empty rather than crashing on a missing key.
"""

from __future__ import annotations

import io

import pytest
from docx import Document

from compass.export import lesson_to_docx, suggested_filename


def a_lesson(**overrides):
    payload = {
        "title": "Two-Step Equations",
        "overview": "Undo the addition, then the multiplication.",
        "learning_objectives": ["Solve for x"],
        "activities": [
            {
                "title": "Practice",
                "kind": "practice",
                "minutes": 60,
                "instructions": "Solve problems 1-10.",
            }
        ],
        "materials": ["Pencil"],
        "assessment": {
            "kind": "Worksheet check",
            "description": "Ten items, mixed procedural and applied.",
            "mastery_criteria": "8 of 10 correct, including 2 of 3 applied problems.",
        },
        "subject_credits": [
            {"subject": "math", "minutes": 60, "justification": "All of it."}
        ],
        "estimated_minutes": 60,
        "parent_notes": "Watch for sign errors.",
        "branches": [],
        "video": {"found": False, "title": "", "url": "", "channel": "", "why": ""},
        "quiz": [
            {
                "question": "What do you do first to solve 2x + 3 = 11?",
                "choices": ["Subtract 3", "Divide by 2", "Add 3", "Multiply by 2"],
                "correct_index": 0,
                "explanation": "Undo addition before multiplication.",
            }
        ],
    }
    payload.update(overrides)
    return payload


def text_of(docx_bytes: bytes) -> str:
    document = Document(io.BytesIO(docx_bytes))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    return "\n".join(parts)


def test_produces_a_valid_docx():
    docx_bytes = lesson_to_docx(a_lesson())
    assert docx_bytes[:2] == b"PK"  # docx is a zip container
    Document(io.BytesIO(docx_bytes))  # raises if not a well-formed document


def test_includes_the_content_on_screen():
    text = text_of(lesson_to_docx(a_lesson()))
    assert "Two-Step Equations" in text
    assert "Undo the addition, then the multiplication." in text
    assert "Solve for x" in text
    assert "Solve problems 1-10." in text
    assert "Pencil" in text


def test_includes_the_parent_only_assessment_and_answer_key():
    """The whole point of this export: the answer key travels with it."""
    text = text_of(lesson_to_docx(a_lesson()))
    assert "Ten items, mixed procedural and applied." in text
    assert "8 of 10 correct, including 2 of 3 applied problems." in text
    assert "What do you do first to solve 2x + 3 = 11?" in text
    assert "Subtract 3 (correct)" in text
    assert "Undo addition before multiplication." in text


def test_includes_subject_credit_table():
    text = text_of(lesson_to_docx(a_lesson()))
    assert "Math" in text
    assert "All of it." in text


def test_handles_a_missing_video_and_empty_quiz_without_crashing():
    lesson = a_lesson(video={"found": False}, quiz=[])
    text = text_of(lesson_to_docx(lesson))
    assert "Suggested video" not in text
    assert "Quiz answer key" not in text


def test_handles_a_found_video():
    lesson = a_lesson(
        video={
            "found": True,
            "title": "Solving Two-Step Equations",
            "url": "https://www.youtube.com/watch?v=abc123",
            "channel": "Khan Academy",
            "why": "Shows the undo steps worked in real time.",
        }
    )
    text = text_of(lesson_to_docx(lesson))
    assert "Solving Two-Step Equations" in text
    assert "https://www.youtube.com/watch?v=abc123" in text


def test_handles_a_minimal_lesson_with_only_required_looking_fields():
    """Nothing here should assume every optional key is present."""
    docx_bytes = lesson_to_docx({"title": "Bare Lesson"})
    text = text_of(docx_bytes)
    assert "Bare Lesson" in text


@pytest.mark.parametrize(
    "title,expected_prefix",
    [
        ("Two-Step Equations", "two-step-equations-"),
        ("Nurse Log Field Study!", "nurse-log-field-study-"),
        ("", "lesson-"),
    ],
)
def test_suggested_filename_is_slugged_and_dated(title, expected_prefix):
    name = suggested_filename({"title": title})
    assert name.startswith(expected_prefix)
    assert name.endswith(".docx")
    assert " " not in name
