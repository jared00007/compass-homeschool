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

from compass.export import course_filename, course_to_docx, lesson_to_docx, suggested_filename


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
                "example": "Worked model: solve 5x + 3 = 18 step by step.",
                "video": {"found": False, "title": "", "url": "", "channel": "", "why": ""},
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
    lesson = a_lesson(quiz=[])
    lesson["activities"][0]["video"] = {"found": False}
    text = text_of(lesson_to_docx(lesson))
    assert "Solving Two-Step Equations" not in text
    assert "Quiz answer key" not in text


def test_handles_a_found_video():
    lesson = a_lesson()
    lesson["activities"][0]["video"] = {
        "found": True,
        "title": "Solving Two-Step Equations",
        "url": "https://www.youtube.com/watch?v=abc123",
        "channel": "Khan Academy",
        "why": "Shows the undo steps worked in real time.",
    }
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


# --- course_to_docx: the grades 6-12 district documentation packet -----------


def a_course(**overrides):
    course = {
        "id": 1,
        "title": "Washington State History",
        "credit_subject": "history",
        "grade_level": "8",
        "description": "A survey of Washington state history.",
        "goals": "Understand tribal, territorial, and statehood eras.",
        "outline": "Unit 1: Indigenous peoples. Unit 2: Territorial era.",
        "credit_value": 1.0,
        "start_date": "2025-09-01",
        "end_date": "2026-08-31",
        "final_grade": "",
        "pass_fail": None,
    }
    course.update(overrides)
    return course


def an_activity_with_lesson(**overrides):
    activity = {
        "id": 1,
        "occurred_on": "2025-10-01",
        "title": "Indigenous Peoples of the Puget Sound",
        "description": "",
        "minutes": 60,
        "lesson_id": 1,
        "lesson": {
            "payload": {
                "learning_objectives": ["Identify three tribes native to the Puget Sound region"],
                "assessment": {
                    "kind": "Oral check",
                    "description": "Name three tribes and one cultural practice each.",
                    "mastery_criteria": "3 of 3 correct",
                },
            },
            "metadata": {"quiz_result": {"correct": 9, "total": 10, "passed": True}},
        },
    }
    activity.update(overrides)
    return activity


def test_course_packet_covers_all_seven_required_sections():
    docx_bytes = course_to_docx(a_course(), [an_activity_with_lesson()], "Landon")
    text = text_of(docx_bytes)
    assert "Course description" in text
    assert "A survey of Washington state history." in text
    assert "Course goals and objectives" in text
    assert "Understand tribal, territorial, and statehood eras." in text
    assert "Course outline of the program" in text
    assert "Learning activities and instructional time log" in text
    assert "Completed assignments and assessments" in text
    assert "Identify three tribes native to the Puget Sound region" in text
    assert "Quiz: 9/10" in text
    assert "How student performance is assessed" in text
    assert "Name three tribes and one cultural practice each." in text
    assert "Student progress and final grade" in text


def test_hours_log_totals_and_shows_progress_toward_the_150_hour_credit():
    docx_bytes = course_to_docx(a_course(), [an_activity_with_lesson()], "Landon")
    text = text_of(docx_bytes)
    assert "1 of 150 hours logged" in text
    assert "2025-10-01" in text and "60" in text


def test_half_credit_course_targets_75_hours():
    docx_bytes = course_to_docx(a_course(credit_value=0.5), [], "Landon")
    text = text_of(docx_bytes)
    assert "75" in text


def test_final_grade_and_pass_fail_appear_when_set():
    docx_bytes = course_to_docx(
        a_course(final_grade="A", pass_fail="pass"), [an_activity_with_lesson()], "Landon"
    )
    text = text_of(docx_bytes)
    assert "Final grade: A" in text
    assert "Transcript record: PASS" in text


def test_not_yet_graded_says_so_rather_than_omitting_the_line():
    docx_bytes = course_to_docx(a_course(), [], "Landon")
    text = text_of(docx_bytes)
    assert "in progress" in text.lower()


def test_handles_a_course_with_no_activities_yet():
    """A freshly created course, before anything's tagged to it, must still
    produce a valid packet rather than crashing on an empty list."""
    docx_bytes = course_to_docx(a_course(), [], "Landon")
    text = text_of(docx_bytes)
    assert "Washington State History" in text
    assert "No instructional time logged" in text
    assert "Nothing completed toward this course yet." in text


def test_handles_an_activity_with_no_lesson_behind_it():
    """A manually logged activity (no `lesson_id`) has `lesson: None` --
    the packet must fall back to the activity's own description rather than
    assuming lesson content always exists."""
    activity = an_activity_with_lesson(lesson_id=None, lesson=None, description="Field trip notes.")
    docx_bytes = course_to_docx(a_course(), [activity], "Landon")
    text = text_of(docx_bytes)
    assert "Field trip notes." in text
    assert (
        "Performance assessed through direct parent observation" in text
    )


@pytest.mark.parametrize(
    "title,expected_prefix",
    [
        ("Washington State History", "washington-state-history-documentation-"),
        ("Algebra 1!", "algebra-1-documentation-"),
        ("", "course-documentation-"),
    ],
)
def test_course_filename_is_slugged_and_dated(title, expected_prefix):
    name = course_filename({"title": title})
    assert name.startswith(expected_prefix)
    assert name.endswith(".docx")
    assert " " not in name
