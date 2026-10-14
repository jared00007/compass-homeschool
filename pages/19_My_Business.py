"""My Business -- Landon's "start a little business" homeschool project.

He enters his business details (name, what he offers and for how much, a line
about himself, how to reach him) and the app turns it into a printable flyer he
can hand to neighbors. Deliberately concrete and bite-size for a 13-year-old:
the real-world skills (naming, pricing, a short pitch) ride along inside a few
small fields rather than a paper-heavy business plan. The builder widget lives
in compass.ui.render_business_builder; this page just hosts it.
"""

from __future__ import annotations

import streamlit as st

from compass.ui import (
    page_setup,
    render_business_builder,
    render_business_houses,
    render_business_log,
    render_business_summary,
    render_business_supplies,
)

db, student = page_setup("My Business", icon="🍂")

# Once he's actually named his business, mirror it onto his Big Projects board
# as a step-by-step plan (idempotent -- only ever one). Nothing appears there
# until he's started, so an empty page never clutters the board.
if (db.get_business_profile(student["id"]).get("name") or "").strip():
    db.ensure_business_project(student["id"])

st.title("🍂 My Business")
render_business_builder(db, student)

st.divider()
render_business_supplies(db, student)

st.divider()
render_business_houses(db, student)

st.divider()
render_business_log(db, student)

st.divider()
render_business_summary(db, student)

st.divider()
st.page_link("Home.py", label="Back to Home", icon="🏠")
