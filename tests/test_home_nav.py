"""Home's own nav: three big buttons (Today / Board / Grades) standing in for
what used to be small `st.tabs()`, chosen because a plain button row is the
only way to put shared header content (greeting, streak, fun fact) *between*
the nav row and whichever view's body is showing -- see Home.py's own comment
on why `st.tabs()` can't do that. The old This Week + Upcoming Week views are
now one Board with its own This-week / Next-week toggle, matching the parent.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")


def _open_home(monkeypatch, db_path):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def _seed(tmp_path):
    db_path = tmp_path / "nav.db"
    db = Database(db_path)
    db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.close()
    return db_path


def _nav_button(at, label_substring):
    return [b for b in at.button if label_substring in (b.label or "")][0]


def test_the_sidebar_has_a_single_courses_entry_not_a_dropdown(monkeypatch, tmp_path):
    """The sidebar has one "Courses" entry (a link to the Courses hub page),
    not a dropdown of the four subjects -- reported: "absolutely not with the
    drop down button on the side bar ... button should be Courses and then in
    the Courses page, there should be 4 buttons." Big Projects / Life Skills /
    Check In / Quizzes stay their own entries below it."""
    at = _open_home(monkeypatch, _seed(tmp_path))
    labels = [pl.label for pl in at.get("page_link")]
    assert "Courses" in labels, "the sidebar must have a Courses entry"
    assert not any((e.label or "") == "📚 Courses" for e in at.expander), "no dropdown"
    for entry in ("Big Projects", "Life Skills", "Check In", "Quizzes"):
        assert entry in labels, f"{entry} must be its own nav entry"


def test_the_courses_page_has_a_button_per_core_subject(monkeypatch, tmp_path):
    """The Courses hub page is just four buttons -- one per core subject."""
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", _seed(tmp_path))
    at = AppTest.from_file(HOME_PATH)  # entrypoint, so nav page-links resolve
    at.run(timeout=30)
    at.switch_page(str(REPO_ROOT / "pages" / "17_Courses.py"))
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    button_labels = [b.label or "" for b in at.button]
    for subject in ("Math", "Science", "English", "History"):
        assert any(subject in label for label in button_labels), f"no {subject} button"


def test_a_subject_page_offers_a_way_back_to_courses(monkeypatch, tmp_path):
    """The subjects are reached from the Courses hub now, not the sidebar, so
    each subject page offers a "Back to Courses" button rather than being a
    dead end."""
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", _seed(tmp_path))
    at = AppTest.from_file(HOME_PATH)  # entrypoint, so nav page-links resolve
    at.run(timeout=30)
    at.switch_page(str(REPO_ROOT / "pages" / "1_Math.py"))
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    assert any((b.key or "") == "back_to_courses" for b in at.button), "no back button"


def test_mission_control_is_a_parent_only_nav_entry(monkeypatch, tmp_path):
    """Mission Control is the one parent-only entry in the nav -- hidden from
    the student, shown once the parent view is unlocked."""
    db_path = _seed(tmp_path)

    student_at = _open_home(monkeypatch, db_path)
    assert "Mission Control" not in [pl.label for pl in student_at.get("page_link")]

    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    parent_at = AppTest.from_file(HOME_PATH)
    parent_at.session_state["parent_unlocked"] = True
    parent_at.run(timeout=30)
    assert not parent_at.exception, [e.message for e in parent_at.exception]
    assert "Mission Control" in [pl.label for pl in parent_at.get("page_link")]


def test_today_is_the_default_view(monkeypatch, tmp_path):
    at = _open_home(monkeypatch, _seed(tmp_path))
    assert _nav_button(at, "Today").proto.type == "primary"
    assert _nav_button(at, "Board").proto.type == "secondary"
    assert _nav_button(at, "Grades").proto.type == "secondary"
    text = " ".join(m.value for m in at.markdown)
    assert "Lessons (" in text


def test_clicking_a_second_view_after_a_first_does_not_leave_the_first_looking_pressed(
    monkeypatch, tmp_path
):
    """Regression: the buttons render in one left-to-right pass, so a button
    rendered *before* the one just clicked used to still compute its own
    primary/secondary look from the stale session_state value -- one click
    behind. Clicking Board, then Grades, used to leave Board looking pressed
    instead of Grades."""
    at = _open_home(monkeypatch, _seed(tmp_path))

    _nav_button(at, "Board").click().run()
    assert _nav_button(at, "Board").proto.type == "primary"
    assert _nav_button(at, "Today").proto.type == "secondary"

    _nav_button(at, "Grades").click().run()
    assert _nav_button(at, "Grades").proto.type == "primary"
    assert _nav_button(at, "Board").proto.type == "secondary"
    assert _nav_button(at, "Today").proto.type == "secondary"
    text = " ".join(c.value for c in at.caption)
    assert "Nothing here is based on how long you worked" in text


def test_board_pages_forward_several_weeks(monkeypatch, tmp_path):
    """The old This Week + Upcoming Week nav buttons are now one Board view
    with a forward week-pager (◀ Earlier / This week / Later ▶) -- so he can
    look not just at next week but several weeks out, matching the fact that
    a parent can plan that far ahead now."""
    at = _open_home(monkeypatch, _seed(tmp_path))
    _nav_button(at, "Board").click().run()
    assert _nav_button(at, "Board").proto.type == "primary"

    # Defaults to this week; "Earlier" is disabled at the near edge.
    prev_button = [b for b in at.button if b.key == "student_board_prev"][0]
    assert prev_button.disabled is True

    later = [b for b in at.button if b.key == "student_board_next"][0]
    later.click().run()
    text = " ".join(c.value for c in at.caption)
    assert "next week" in text

    later = [b for b in at.button if b.key == "student_board_next"][0]
    later.click().run()
    text = " ".join(c.value for c in at.caption)
    assert "2 weeks out" in text

    # And "This week" jumps straight back to the near edge.
    this_button = [b for b in at.button if b.key == "student_board_this"][0]
    this_button.click().run()
    prev_button = [b for b in at.button if b.key == "student_board_prev"][0]
    assert prev_button.disabled is True


def test_the_student_board_is_read_only_no_move_controls(monkeypatch, tmp_path):
    """render_board_days(interactive=False): a student's own Board must never
    offer the parent-only reschedule/backlog move control -- planning is a
    parent's to do, he just sees what's set."""
    db_path = tmp_path / "nav.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    from compass import weekly

    monday = weekly.week_start()
    db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="On the Board This Week",
        payload={"title": "On the Board This Week", "activities": []},
        metadata={"planned_for": monday.isoformat(), "week_start": monday.isoformat()},
    )
    db.close()

    at = _open_home(monkeypatch, db_path)
    _nav_button(at, "Board").click().run()
    assert not at.exception, [e.message for e in at.exception]
    move_keys = [
        b.key for b in at.button
        if b.key and (b.key.startswith("move_board_") or b.key.startswith("board_view_lesson_"))
    ]
    # No move control at all; the View-full-lesson dialog stays available.
    assert not any(k.startswith("move_board_") for k in move_keys)


def test_today_shows_the_daily_delights(monkeypatch, tmp_path):
    """The little fun touches on his Today view: a rotating greeting, a Brain
    Break card (riddle + word + history), and a week progress gauge once
    there's a plan for the week."""
    db_path = tmp_path / "nav.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    from compass import daily, weekly

    monday = weekly.week_start().isoformat()
    db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="This Week's Math",
        payload={"title": "This Week's Math", "activities": []},
        metadata={"planned_for": monday, "week_start": monday},
    )
    db.close()

    at = _open_home(monkeypatch, db_path)
    assert not at.exception, [e.message for e in at.exception]
    text = " ".join(m.value for m in at.markdown)
    caption_text = " ".join(c.value for c in at.caption)
    # Rotating greeting under his name.
    assert daily.greeting_of_the_day() in caption_text
    # Brain Break card content -- the fun fact now lives here too.
    assert "Brain Break" in text
    assert "Fun fact" in text
    assert "Word of the day" in text
    assert "History flashback" in text
    # His level bar + the week progress gauge both render.
    progress_text = " ".join(p.proto.text for p in at.get("progress"))
    assert "Level 1" in text  # the XP level card heading
    assert "0 of 1 lessons done this week" in progress_text


def test_travel_passport_shows_stamps_for_completed_trips(monkeypatch, tmp_path):
    """The collectible: a completed trip earns its state + park a stamp on his
    Travel Passport; an assigned-but-unwritten trip shows as still waiting."""
    db_path = tmp_path / "nav.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    sid = student["id"]
    # A finished trip -> a stamp.
    db.add_travel_entry(sid, "Maine", "2026-06-01", title="Acadia", park_key="acadia")
    # (add_travel_entry defaults to completed for a written-up trip.)
    # An assigned trip with nothing written yet -> still waiting.
    db.add_travel_entry(sid, "Utah", "2026-07-01", title="", status="planned")
    db.close()

    at = _open_home(monkeypatch, db_path)
    assert not at.exception, [e.message for e in at.exception]
    text = " ".join(m.value for m in at.markdown)
    caption_text = " ".join(c.value for c in at.caption)
    assert "Travel Passport" in text
    assert "1 of 50 states explored" in text
    assert "Acadia" in text  # the park's stamp
    assert "Maine" in caption_text
    assert "waiting to be written up" in caption_text


def test_the_student_board_dialog_has_a_writing_box_and_upload(monkeypatch, tmp_path):
    """Reported directly: a writing activity on his board "should be a text
    input box for that writing assignment and upload file." Opening a lesson's
    View-full-lesson dialog from his board must render the real response box and
    Word-doc uploader, not just instructions to write on paper."""
    db_path = tmp_path / "nav.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    from compass import weekly

    monday = weekly.week_start()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Coordinate Plane",
        payload={
            "title": "Coordinate Plane",
            "activities": [{
                "title": "What Does the Point Actually Mean?",
                "kind": "writing", "minutes": 8,
                "instructions": "Write 60-90 words explaining a point in Quadrant III.",
            }],
        },
        metadata={"planned_for": monday.isoformat(), "week_start": monday.isoformat()},
    )
    db.close()

    at = _open_home(monkeypatch, db_path)
    _nav_button(at, "Board").click().run()
    at.button(key=f"board_view_lesson_{lesson_id}").click().run()
    assert not at.exception, [e.message for e in at.exception]
    text_keys = [t.key for t in at.text_area]
    assert any((k or "").startswith(f"writing_draft_{lesson_id}_") for k in text_keys), (
        "the writing response box must render for him in the board dialog"
    )
    upload_keys = [u.key for u in at.get("file_uploader")]
    assert any((k or "").startswith(f"writing_upload_{lesson_id}_") for k in upload_keys), (
        "the Word-doc uploader must render alongside the box"
    )


def test_the_student_board_shows_a_backlog_with_view_full_lesson(monkeypatch, tmp_path):
    """Reported directly: from his board he should "view full lesson for
    anything thats in view there. backlog or assigned a date." A parked lesson
    shows in a read-only backlog section with its own View-full-lesson button
    and no move control."""
    db_path = tmp_path / "nav.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    from compass import weekly

    monday = weekly.week_start()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="science", subject="science", topic="t",
        title="Parked Science Lesson",
        payload={"title": "Parked Science Lesson", "activities": []},
        metadata={
            "planned_for": monday.isoformat(),
            "week_start": monday.isoformat(),
            "held_back": True,  # parked -> lives in the backlog
        },
    )
    db.close()

    at = _open_home(monkeypatch, db_path)
    _nav_button(at, "Board").click().run()
    assert not at.exception, [e.message for e in at.exception]
    text = " ".join(m.value for m in at.markdown)
    assert "Not scheduled yet" in text
    assert any(b.key == f"board_view_lesson_{lesson_id}" for b in at.button), (
        "a backlogged lesson on his board must still offer View full lesson"
    )
    # ...but no parent move control on it.
    assert not any((b.key or "").startswith("move_board_") for b in at.button)


def test_the_student_board_shows_life_skill_and_step_detail(monkeypatch, tmp_path):
    """Reported directly against his board: "life skill and big project arent
    loading in the board correctly with the lesson or steps." On the read-only
    student board (interactive=False) the parent-only move control and estimate
    editor are stripped, but the card must still carry what the skill/step
    actually *is* (its description) AND an "Open it" link so he can go do it --
    reported: "the card on the board doesnt have link/view assignment. should
    see something." """
    db_path = tmp_path / "nav.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    from compass import weekly

    monday = weekly.week_start().isoformat()

    skill_id = db.add_life_skill(
        student["id"], "Do the laundry", category="Home",
        description="Sort lights from darks, then run a full cycle.",
        materials="Detergent",
    )
    db.set_life_skill_active(skill_id, True)
    db.schedule_life_skill(skill_id, monday)

    project_id = db.add_big_project(student["id"], "Stop-motion film", "a film")
    step_id = db.add_project_step(
        project_id, "Storyboard the opening",
        description="Sketch the first ten shots before touching the camera.",
        active=True,
    )
    db.schedule_project_step(step_id, monday)
    db.close()

    at = _open_home(monkeypatch, db_path)
    _nav_button(at, "Board").click().run()
    assert not at.exception, [e.message for e in at.exception]
    body = " ".join(m.value for m in at.markdown)
    assert "Sort lights from darks" in body, "the life-skill detail must render on his board"
    assert "Sketch the first ten shots" in body, "the project-step detail must render on his board"
    # He now gets an "Open it" deep link on non-lesson cards too, not just lessons,
    # so there's always a way off the board into the actual assignment.
    open_links = [pl for pl in at.get("page_link") if pl.label == "Open it"]
    assert len(open_links) >= 2, "each non-lesson board card needs an 'Open it' link"
    targets = {pl.page for pl in open_links}
    assert any("Life_Skills" in t for t in targets)
    assert any("Big_Projects" in t for t in targets)
    # ...but the parent-only time-estimate editor never appears on his board.
    est_inputs = [n for n in at.number_input if (n.key or "").startswith("board_est_")]
    assert not est_inputs, "the estimate editor is parent-only, never on the student board"


def test_the_student_board_full_lesson_hides_the_answer_key(monkeypatch, tmp_path):
    """Reported directly: "on landons board, his stories hold the answer
    keys?" The board's "View full lesson" dialog used to force
    render_lesson(for_parent=True) and offered a whole-lesson PDF, so a
    student opening one of his own board lessons saw the quiz answer key and
    the assessment mastery criteria -- both parent-only everywhere else. On
    his own board the dialog must fall back to is_parent() (PIN set, not
    unlocked -> student), hiding the key. He still gets a Print to PDF button,
    but it's his redacted cut (parent=False, no answer key) -- so the rendered
    dialog carries none of the parent-only text."""
    db_path = tmp_path / "nav.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    from compass import weekly

    monday = weekly.week_start()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Fractions Face-Off",
        payload={
            "title": "Fractions Face-Off",
            "activities": [],
            "assessment": {
                "kind": "oral check",
                "description": "Ask him to halve a recipe.",
                "mastery_criteria": "Explains why 1/2 of 3/4 is 3/8.",
            },
            "quiz": [
                {
                    "question": "What is 1/2 + 1/4?",
                    "choices": ["3/4", "2/6", "1/6"],
                    "correct_index": 0,
                    "explanation": "Common denominator of 4.",
                }
            ],
        },
        metadata={"planned_for": monday.isoformat(), "week_start": monday.isoformat()},
    )
    db.close()

    at = _open_home(monkeypatch, db_path)
    _nav_button(at, "Board").click().run()
    view = [b for b in at.button if b.key == f"board_view_lesson_{lesson_id}"][0]
    view.click().run()
    assert not at.exception, [e.message for e in at.exception]

    # The dialog opened (the student view uses the comic layout, so the title
    # renders as markdown, not a subheader)...
    body = " ".join(m.value for m in at.markdown)
    assert "Fractions Face-Off" in body
    # ...but with none of the parent-only material.
    expander_labels = " ".join(e.label for e in at.expander)
    assert "Quiz answer key" not in expander_labels
    assert "Counts as mastered when" not in body
    assert "3/8" not in body  # the assessment answer must not leak either
    # He still gets a Print to PDF button -- but it's his redacted cut (no
    # answer key, no assessment), produced with parent=False. The redaction of
    # the PDF's own content is pinned in test_export.py; here it's enough that
    # the button is offered from his side at all.
    pdf = [d for d in at.get("download_button") if d.key == f"board_pdf_{lesson_id}"]
    assert pdf, "the student board should still offer a (redacted) Print to PDF"


def test_switching_views_and_back_to_today_still_shows_the_roster(monkeypatch, tmp_path):
    at = _open_home(monkeypatch, _seed(tmp_path))
    _nav_button(at, "Grades").click().run()
    _nav_button(at, "Today").click().run()
    assert _nav_button(at, "Today").proto.type == "primary"
    text = " ".join(m.value for m in at.markdown)
    assert "Lessons (" in text


def test_student_link_offers_no_parent_unlock(monkeypatch, tmp_path):
    """The plain URL is Landon's: with a PIN set it starts in student view and
    shows no way to unlock the parent view (nothing to type a PIN into)."""
    at = _open_home(monkeypatch, _seed(tmp_path))
    assert not any(t.key == "pin_unlock" for t in at.text_input)


def test_parent_link_shows_the_unlock(monkeypatch, tmp_path):
    """The parent entry point (`?view=parent`) is the one place the PIN unlock
    appears, so only the parent can cross into the parent view."""
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", _seed(tmp_path))
    at = AppTest.from_file(HOME_PATH)
    at.query_params["view"] = "parent"
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    assert any(t.key == "pin_unlock" for t in at.text_input)


def test_a_board_assigned_project_step_shows_under_lessons(monkeypatch, tmp_path):
    """A Big Project step a parent assigned to today shows on his main page in
    the Lessons list, as a card linking out to Big Projects -- reported: "the
    projects assigned on the board need to show on his main page under
    lessons.\""""
    import datetime
    db_path = tmp_path / "proj.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    today = datetime.date.today().isoformat()
    pid = db.add_big_project(student_id=student["id"], title="Lego Movie", vision="film it")
    step = db.add_project_step(pid, "Storyboard the opening", active=True)
    db.schedule_project_step(step, today)
    auth.set_pin(db, "1234")
    db.close()

    at = _open_home(monkeypatch, db_path)
    # The step is counted in the Lessons header and marked as a project step.
    markdown = " ".join(m.value for m in at.markdown)
    captions = " ".join(c.value for c in at.caption)
    assert "Lessons (1)" in markdown
    assert "project step" in captions


def test_a_submitted_project_step_shows_waiting_on_home(monkeypatch, tmp_path):
    """A project step he's turned in shows on Home marked 📤 (waiting on a
    parent), the same four-state gate a lesson uses."""
    import datetime
    db_path = tmp_path / "proj.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    today = datetime.date.today().isoformat()
    pid = db.add_big_project(student_id=student["id"], title="Toy Photography", vision="v")
    step = db.add_project_step(pid, "Pick your toy and your theme", active=True)
    db.schedule_project_step(step, today)
    db.submit_project_step(step)
    auth.set_pin(db, "1234")
    db.close()

    at = _open_home(monkeypatch, db_path)
    captions = " ".join(c.value for c in at.caption)
    assert "waiting on a parent" in captions
