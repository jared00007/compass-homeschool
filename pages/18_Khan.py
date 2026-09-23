"""Khan Academy — where Landon's Khan cards live.

A Khan card is a unit or exercise his parent assigned on Khan Academy: he does
it there, logs his score, and takes a quick auto-graded quiz. Every Khan card,
whatever subject it credits, shares this one page (they all use the `khan`
agent), so it's the single place he finds "my Khan assignments." Parents add
them from Mission Control → Plan a lesson → Add a Khan Academy card.
"""

from __future__ import annotations

import streamlit as st

from compass.ui import (
    is_parent,
    page_setup,
    render_khan_mastery_boost,
    render_past_lessons,
    student_lesson_view,
)

db, student = page_setup("Khan Academy", icon="🅰️")

st.title("🅰️ Khan Academy")
st.caption(
    "Units and exercises to do on Khan Academy. Open the link, do the skill there, "
    "log how you did, and take the quick quiz."
)

# Student view: his current Khan card, its quiz, and the ones he's finished.
if not is_parent():
    student_lesson_view(db, student, "khan", "Khan Academy")
    render_khan_mastery_boost(db, student)
    render_past_lessons(db, student, "khan", "Khan Academy")
    st.stop()

# Parent view: this page is Landon's. Cards are created and reviewed elsewhere.
st.info(
    "Add Khan cards from **Mission Control → Plan a lesson → Add a Khan Academy "
    "card**. Review and approve them (logging hours) from **Mission Control → "
    "Review**, like any lesson."
)
render_past_lessons(db, student, "khan", "Khan Academy")
