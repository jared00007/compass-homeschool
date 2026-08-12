"""Turn a lesson payload into a printable Word document.

This is a parent-only export: it includes everything `render_lesson`'s parent
view shows, assessment and quiz answer key included. It exists because reading
an assessment off a laptop screen while scoring a kid's paper worksheet is
awkward — a printed page isn't. Callers must not offer this from a student-view
context; nothing here re-checks who's asking.
"""

from __future__ import annotations

import io
import re
from datetime import date
from typing import Any

from docx import Document
from docx.shared import Pt

from compass import subjects


def suggested_filename(lesson: dict[str, Any]) -> str:
    """A readable .docx filename: the lesson title, slugged, plus today's date."""
    title = lesson.get("title") or "lesson"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "lesson"
    return f"{slug}-{date.today().isoformat()}.docx"


def _add_bullets(document: Document, items: list[str]) -> None:
    for item in items:
        document.add_paragraph(str(item), style="List Bullet")


def lesson_to_docx(lesson: dict[str, Any]) -> bytes:
    """Render a lesson payload to a .docx file, returned as bytes."""
    document = Document()
    style = document.styles["Normal"]
    style.font.size = Pt(11)

    document.add_heading(lesson.get("title") or "Lesson", level=1)
    if lesson.get("overview"):
        document.add_paragraph(lesson["overview"])

    objectives = lesson.get("learning_objectives") or []
    if objectives:
        document.add_heading("Learning objectives", level=2)
        _add_bullets(document, objectives)

    materials = lesson.get("materials") or []
    if materials:
        document.add_heading("Materials", level=2)
        _add_bullets(document, materials)

    activities = lesson.get("activities") or []
    if activities:
        document.add_heading("Activities", level=2)
        for index, activity in enumerate(activities, start=1):
            heading = (
                f"{index}. {activity.get('title', 'Activity')} "
                f"({activity.get('kind', '')}, {activity.get('minutes', 0)} min)"
            )
            document.add_heading(heading, level=3)
            video = activity.get("video") or {}
            if video.get("found") and video.get("url"):
                watch = document.add_paragraph()
                watch.add_run(f"Video: {video.get('title') or 'Watch'}").bold = True
                document.add_paragraph(video["url"])
                if video.get("why"):
                    document.add_paragraph(video["why"]).runs[0].italic = True
            if activity.get("example"):
                worked = document.add_paragraph()
                worked.add_run("Here's how: ").bold = True
                worked.add_run(activity["example"])
            if activity.get("instructions"):
                document.add_paragraph(activity["instructions"])

    assessment = lesson.get("assessment") or {}
    if assessment:
        document.add_heading("Assessment", level=2)
        if assessment.get("kind"):
            document.add_paragraph(assessment["kind"]).runs[0].bold = True
        if assessment.get("description"):
            document.add_paragraph(assessment["description"])
        if assessment.get("mastery_criteria"):
            criteria = document.add_paragraph()
            criteria.add_run("Mastery: ").bold = True
            criteria.add_run(assessment["mastery_criteria"])

    quiz = lesson.get("quiz") or []
    if quiz:
        document.add_heading("Quiz answer key", level=2)
        for index, item in enumerate(quiz, start=1):
            document.add_paragraph(f"{index}. {item.get('question', '')}").runs[0].bold = True
            correct_index = item.get("correct_index")
            for choice_index, choice in enumerate(item.get("choices") or []):
                marker = " (correct)" if choice_index == correct_index else ""
                document.add_paragraph(f"{choice}{marker}", style="List Bullet")
            if item.get("explanation"):
                explanation = document.add_paragraph()
                explanation.add_run(item["explanation"]).italic = True

    if lesson.get("parent_notes"):
        document.add_heading("Notes for the parent", level=2)
        document.add_paragraph(lesson["parent_notes"])

    credits = lesson.get("subject_credits") or []
    if credits:
        document.add_heading("Subject credit", level=2)
        table = document.add_table(rows=1, cols=3)
        table.style = "Light Grid Accent 1"
        header = table.rows[0].cells
        header[0].text, header[1].text, header[2].text = "Subject", "Minutes", "Why"
        for credit in credits:
            row = table.add_row().cells
            row[0].text = subjects.label(credit.get("subject", ""))
            row[1].text = str(credit.get("minutes", ""))
            row[2].text = credit.get("justification", "")

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
