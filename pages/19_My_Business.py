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

from compass.ui import page_setup, render_business_builder

db, student = page_setup("My Business", icon="🍂")

st.title("🍂 My Business")
render_business_builder(db, student)

st.divider()
st.page_link("Home.py", label="Back to Home", icon="🏠")
