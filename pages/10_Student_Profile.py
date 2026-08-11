"""Student Profile -- name, grade, age, and interests. Parent-only: every
agent's system prompt reads `interests` directly (compass.storage.db's
`interests_text`), so getting it right isn't a preference, it's
configuration the model actually leans on for examples and numbers.
"""

from __future__ import annotations

import html

import streamlit as st

from compass.ui import page_setup, parent_only

db, student = page_setup("Student Profile", icon="🧑‍🎓")

if not parent_only("This page is for your parent."):
    st.stop()

st.title("🧑‍🎓 Student Profile")
st.caption("Everything the agents read before writing a lesson.")

with st.form("student_profile_basics"):
    columns = st.columns([2, 1, 1])
    name = columns[0].text_input("Name", value=student["name"])
    grade = columns[1].text_input("Grade", value=student["grade"])
    age = columns[2].number_input(
        "Age", min_value=5, max_value=19, value=int(student["age"] or 13)
    )
    if st.form_submit_button("Save", type="primary"):
        db.update_student(
            student["id"],
            name=name.strip() or "Student",
            grade=grade.strip() or "8",
            age=int(age),
        )
        st.success("Saved.")
        st.rerun()

st.divider()

st.subheader("Interests he's told us about")
st.caption(
    "Read by every agent when it writes a lesson -- a math example about "
    "Minecraft lands better than a generic one."
)

_CHIP_CSS = """
<style>
div[class*="st-key-interest_chip_"] {
  border: 1px solid var(--c-border) !important;
  border-radius: 999px !important;
  background: var(--c-panel) !important;
  padding: 2px 4px 2px 14px !important;
  margin-bottom: 10px;
}
div[class*="st-key-interest_chip_"] p { font-size: 13.5px; font-weight: 600; }
div[class*="st-key-interest_chip_"] button {
  border-radius: 50% !important;
  width: 26px; height: 26px; padding: 0 !important;
  min-height: 26px;
}
</style>
"""

INTERESTS_PER_ROW = 3

interests = db.list_interests(student["id"])
if not interests:
    st.caption("Nothing added yet -- add the first one below.")
else:
    st.markdown(_CHIP_CSS, unsafe_allow_html=True)
    for row_start in range(0, len(interests), INTERESTS_PER_ROW):
        row = interests[row_start : row_start + INTERESTS_PER_ROW]
        row_columns = st.columns(INTERESTS_PER_ROW)
        for column, interest in zip(row_columns, row):
            with column, st.container(key=f"interest_chip_{interest['id']}"):
                text_col, remove_col = st.columns([5, 1], vertical_alignment="center")
                text_col.markdown(html.escape(interest["text"]))
                if remove_col.button("✕", key=f"remove_interest_{interest['id']}"):
                    db.delete_interest(interest["id"])
                    st.rerun()

with st.form("add_interest", clear_on_submit=True):
    add_columns = st.columns([4, 1])
    new_interest = add_columns[0].text_input(
        "Add an interest", placeholder="e.g. Legos, Minecraft, filmmaking", label_visibility="collapsed"
    )
    if add_columns[1].form_submit_button("Add", type="primary") and new_interest.strip():
        db.add_interest(student["id"], new_interest.strip())
        st.rerun()
