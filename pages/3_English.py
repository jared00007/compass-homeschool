"""English / Language Arts Agent — tied to the book he's actually reading,
with two deliberate exceptions: an occasional nonfiction piece for genre
variety, and a standalone grammar/writing fallback when no book is set at
all (see ELA_FOCUS_ROTATION / STANDALONE_FOCUS_ROTATION in
compass/agents/strategies.py)."""

from __future__ import annotations

from datetime import date

import streamlit as st

from compass.agents import LessonGenerationError, book_summary, get_agent
from compass.agents.strategies import ELA_FOCUS_ROTATION, STANDALONE_FOCUS_ROTATION
from compass.ui import (
    api_status_banner,
    context_for,
    difficulty_override_control,
    generate_and_log,
    is_parent,
    md,
    page_setup,
    render_past_lessons,
    render_proposal,
    render_vocab_quiz,
    student_lesson_view,
)

db, student = page_setup("English", icon="📖")
agent = get_agent("english")

st.title("📖 English & Language Arts Agent")
st.caption(
    "Reading level, vocabulary, and writing all come off the book he is currently "
    "reading — not a generic passage list."
)

# Student view: his lesson, without the answer key or the admin surface.
# Bug fixed here: this used to st.stop() before the tabs below were even built,
# so the "Review them" link on his home page (Words to review) sent him to a
# page with nothing on it -- there was no student-facing vocabulary review at
# all, only the parent-facing tab further down, which he never reached.
if not is_parent():
    student_lesson_view(db, student, "english", "English")
    st.divider()
    st.subheader("🔤 Words to review")
    render_vocab_quiz(db, student)
    render_past_lessons(db, student, "english")
    st.stop()

plan_tab, books_tab, vocab_tab = st.tabs(["Plan a lesson", "Books", "Vocabulary"])

# --- plan --------------------------------------------------------------------

with plan_tab:
    api_ok = api_status_banner()
    book = db.current_book(student["id"])

    if not book:
        st.info(
            "No book is marked as currently being read, so this will be a standalone "
            "grammar/writing lesson instead -- add one on the **Books** tab for "
            "lessons tied to what he's actually reading."
        )
        focus_rotation = STANDALONE_FOCUS_ROTATION
    else:
        focus_rotation = ELA_FOCUS_ROTATION

    columns = st.columns([2, 1, 1])
    with columns[0]:
        focus_labels = {key: text for key, text in focus_rotation}
        focus_choice = st.selectbox(
            "Focus",
            ["Let the agent rotate"] + list(focus_labels),
            format_func=lambda k: k if k == "Let the agent rotate" else focus_labels[k],
        )
    with columns[1]:
        minutes = st.number_input("Minutes", min_value=15, max_value=180, value=60, step=5)
    with columns[2]:
        due = db.vocabulary_due(student["id"])
        st.metric("Words due", len(due))

    if book:
        page = st.number_input(
            "Current page",
            min_value=0,
            max_value=int(book["total_pages"] or 5000),
            value=int(book["current_page"] or 0),
            help="The agent will not reference anything past this page.",
        )
        if page != book["current_page"]:
            db.update_book(book["id"], current_page=int(page))
            book["current_page"] = int(page)

    seed_topic = st.text_input(
        "Or point this lesson at something specific (optional)",
        placeholder="e.g. the courtroom scene in chapter 12" if book else "e.g. writing a thank-you note",
        help="Overrides the Focus pick above with exactly this.",
    )
    parent_note = st.text_input("Note for this lesson (optional)")
    difficulty = difficulty_override_control(db, key="english_difficulty")

    ctx = context_for(
        db,
        student,
        minutes=minutes,
        parent_note=parent_note,
        focus="" if focus_choice == "Let the agent rotate" else focus_choice,
        seed_topic=seed_topic,
        difficulty=difficulty,
    )
    proposal = agent.propose_topic(ctx)
    render_proposal(agent, proposal)

    generate_and_log(
        db,
        student,
        agent,
        ctx,
        proposal,
        # A standalone lesson (no book) is grammar/writing practice, not
        # reading comprehension -- this is only the fallback tag used if the
        # model's own subject_credits ever comes back empty, but it should
        # still describe the lesson accurately when it is used.
        primary_subject="reading" if book else "writing",
        spinner="The English Agent is writing the lesson…",
        api_ok=api_ok,
        after_render=(
            "Any `VOCAB:` lines in the materials were added to his "
            "spaced-repetition deck."
        ),
    )

# --- books -------------------------------------------------------------------

with books_tab:
    st.subheader(f"What's {student['name']} reading?")
    st.caption(
        "Running two books this year, one per half? Tag each with **When is "
        "this for?** below when you add it -- the second-half book waits as "
        "*upcoming* until you switch to it, so the agent never reads from "
        "the wrong one."
    )

    upcoming = db.upcoming_book(student["id"])
    if upcoming:
        current = db.current_book(student["id"])
        midpoint = db.school_year_midpoint()
        with st.container(border=True):
            if date.today() >= midpoint:
                st.markdown(
                    f"📅 Past this year's midpoint ({midpoint.strftime('%b %-d')}) -- "
                    f"ready to switch to **{md(upcoming['title'])}** for the second half?"
                )
            else:
                switch_from = f"**{md(current['title'])}**" if current else "the first-half book"
                st.markdown(
                    f"**{md(upcoming['title'])}** is queued for the second half of the "
                    f"year (around {midpoint.strftime('%b %-d')}). Finished {switch_from} "
                    "early? You don't have to wait for that date."
                )
            if st.button(f"Switch to {upcoming['title']} now", key=f"promote_{upcoming['id']}"):
                db.promote_upcoming_book(student["id"], upcoming["id"])
                st.rerun()

    with st.form("add_book", clear_on_submit=True):
        columns = st.columns([2, 2, 1, 1])
        title = columns[0].text_input("Title")
        author = columns[1].text_input("Author")
        level = columns[2].text_input(
            "Reading level",
            placeholder="e.g. 8.4",
            help=(
                "Grade.month, the same scale AR/ATOS book levels use -- 8.4 means "
                "8th grade, 4th month. Optional, but a precise value here helps the "
                "agent calibrate vocabulary better than a wide grade range would."
            ),
        )
        pages = columns[3].number_input("Pages", min_value=0, max_value=5000, value=0)
        notes = st.text_input("Notes for the agent (optional)")
        term_choice = st.selectbox(
            "When is this for?",
            [
                "No specific term -- start reading now",
                "First half of the year -- start reading now",
                "Second half of the year -- queue it for later",
            ],
            help=(
                "Tagging both halves' books up front lets you set the whole year's "
                "reading up in one sitting; the second-half pick sits as upcoming "
                "until you (or the midpoint nudge above) switch to it."
            ),
        )
        if st.form_submit_button("Add book", type="primary") and title.strip():
            term = None
            status = "reading"
            if term_choice.startswith("First half"):
                term = "first_half"
            elif term_choice.startswith("Second half"):
                term = "second_half"
                status = "upcoming"
            db.add_book(
                student["id"],
                title.strip(),
                author.strip(),
                level.strip(),
                int(pages) or None,
                notes.strip(),
                term=term,
                status=status,
            )
            st.rerun()

    term_badges = {"first_half": " · 1st half", "second_half": " · 2nd half"}
    for book in db.list_books(student["id"]):
        with st.container(border=True):
            columns = st.columns([4, 1, 1])
            byline = f" — {book['author']}" if book["author"] else ""
            badge = term_badges.get(book["term"], "")
            columns[0].markdown(f"**{book['title']}**{byline}  \n*{book['status']}{badge}*")
            if book["total_pages"] and book["status"] == "reading":
                columns[0].progress(
                    min((book["current_page"] or 0) / book["total_pages"], 1.0),
                    text=f"page {book['current_page']} of {book['total_pages']}",
                )
            if book["status"] == "reading":
                if columns[1].button("Finished", key=f"finish_{book['id']}"):
                    db.update_book(book["id"], status="finished")
                    st.rerun()
                if columns[2].button("Set aside", key=f"drop_{book['id']}"):
                    db.update_book(book["id"], status="abandoned")
                    st.rerun()
            elif book["status"] == "upcoming":
                if columns[1].button("Start now", key=f"start_{book['id']}"):
                    db.promote_upcoming_book(student["id"], book["id"])
                    st.rerun()
            elif columns[1].button("Resume", key=f"resume_{book['id']}"):
                db.update_book(book["id"], status="reading")
                st.rerun()

            if book["ai_summary"]:
                st.caption(md(book["ai_summary"]))
            summary_label = "✨ Regenerate summary" if book["ai_summary"] else "✨ Draft a summary with AI"
            if st.button(summary_label, key=f"summarize_{book['id']}", disabled=not api_ok):
                with st.spinner("Drafting a summary…"):
                    try:
                        book_summary.generate_book_summary(db, student, book)
                        st.rerun()
                    except LessonGenerationError as exc:
                        st.error(str(exc))

# --- vocabulary --------------------------------------------------------------

with vocab_tab:
    st.subheader("Spaced repetition")
    st.caption(
        "Leitner boxes: a word he gets right moves up a box and comes back later; a "
        "word he misses drops to box 1 and comes back tomorrow."
    )

    due = db.vocabulary_due(student["id"], limit=25)
    if due:
        st.markdown(f"**{len(due)} due today**")
        for entry in due:
            with st.container(border=True):
                columns = st.columns([3, 1, 1])
                columns[0].markdown(f"**{entry['word']}** — {entry['definition']}")
                columns[0].caption(
                    f"box {entry['box']} · {entry['times_correct']} right / "
                    f"{entry['times_missed']} missed"
                )
                if columns[1].button("Knew it", key=f"ok_{entry['id']}"):
                    db.record_vocabulary_review(entry["id"], correct=True)
                    st.rerun()
                if columns[2].button("Missed", key=f"miss_{entry['id']}"):
                    db.record_vocabulary_review(entry["id"], correct=False)
                    st.rerun()
    else:
        st.success("Nothing due for review today.")

    with st.form("add_vocab", clear_on_submit=True):
        columns = st.columns([1, 3])
        word = columns[0].text_input("Word")
        definition = columns[1].text_input("Definition")
        if st.form_submit_button("Add word") and word.strip():
            db.add_vocabulary(student["id"], word.strip(), definition.strip())
            st.rerun()

    all_words = db.list_vocabulary(student["id"])
    if all_words:
        with st.expander(f"Full deck ({len(all_words)} words)"):
            for entry in all_words:
                st.markdown(
                    f"- **{entry['word']}** (box {entry['box']}, next {entry['next_review_on']}) "
                    f"— {entry['definition']}"
                )
