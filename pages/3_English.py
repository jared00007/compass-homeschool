"""English / Language Arts Agent — tied to the book he's actually reading."""

from __future__ import annotations

import streamlit as st

from compass.agents import get_agent
from compass.agents.strategies import ELA_FOCUS_ROTATION
from compass.ui import (
    api_status_banner,
    context_for,
    generate_and_log,
    is_parent,
    page_setup,
    render_proposal,
    render_vocab_match,
    render_vocab_review,
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
    mode = st.radio(
        "How do you want to review?",
        ["Flashcards", "Trading Cards"],
        horizontal=True,
        key="vocab_review_mode",
    )
    if mode == "Flashcards":
        render_vocab_review(db, student)
    else:
        render_vocab_match(db, student)
    st.stop()

plan_tab, books_tab, vocab_tab = st.tabs(["Plan a lesson", "Books", "Vocabulary"])

# --- plan --------------------------------------------------------------------

with plan_tab:
    api_ok = api_status_banner()
    book = db.current_book(student["id"])

    if not book:
        st.warning(
            "No book is marked as currently being read. Add one on the **Books** tab — "
            "this agent deliberately refuses to fall back to generic passages."
        )
    else:
        columns = st.columns([2, 1, 1])
        with columns[0]:
            focus_labels = {key: text for key, text in ELA_FOCUS_ROTATION}
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

        parent_note = st.text_input("Note for this lesson (optional)")

        ctx = context_for(
            db,
            student,
            minutes=minutes,
            parent_note=parent_note,
            focus="" if focus_choice == "Let the agent rotate" else focus_choice,
        )
        proposal = agent.propose_topic(ctx)
        render_proposal(agent, proposal)

        generate_and_log(
            db,
            student,
            agent,
            ctx,
            proposal,
            primary_subject="reading",
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
        if st.form_submit_button("Add book", type="primary") and title.strip():
            db.add_book(
                student["id"],
                title.strip(),
                author.strip(),
                level.strip(),
                int(pages) or None,
                notes.strip(),
            )
            st.rerun()

    for book in db.list_books(student["id"]):
        with st.container(border=True):
            columns = st.columns([4, 1, 1])
            byline = f" — {book['author']}" if book["author"] else ""
            columns[0].markdown(f"**{book['title']}**{byline}  \n*{book['status']}*")
            if book["total_pages"]:
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
            elif columns[1].button("Resume", key=f"resume_{book['id']}"):
                db.update_book(book["id"], status="reading")
                st.rerun()

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
