"""The Courses hub: one button per core subject.

Reported: "button should be Courses and then in the Courses page, there
should be 4 buttons each subject." The four core subjects used to be four
separate sidebar entries; they're one "Courses" entry now (see
compass.ui._render_nav), and this is where it lands -- a plain four-button
launcher into Math, Science, English, and History. Student-facing: these
are his daily-work pages, not a parent surface, so there's no PIN gate.
"""

from __future__ import annotations

import streamlit as st

from compass.ui import page_setup

db, student = page_setup("Courses", icon="📚")

st.title("📚 Courses")
st.caption("Your four core subjects — pick one to jump in.")

_SUBJECTS = [
    ("🔢 Math", "pages/1_Math.py"),
    ("🔬 Science", "pages/2_Science.py"),
    ("📖 English", "pages/3_English.py"),
    ("🏛️ History", "pages/4_History.py"),
]

# One row, all four buttons spread evenly across it.
columns = st.columns(len(_SUBJECTS))
for column, (label, target) in zip(columns, _SUBJECTS):
    if column.button(label, width="stretch", key=f"course_{target}"):
        st.switch_page(target)
