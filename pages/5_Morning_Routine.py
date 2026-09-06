"""Morning Routine -- a short, parent-curated menu of stretches, breathing,
and mindfulness routines to start the day with, before any schoolwork.

It's a whole page rather than an inline block on Home so the Due-today list
can link straight to it (kept tight there -- one tile, one link) instead of
unrolling the full picker at the top of Home. The routine widget itself
(compass.ui.render_morning_routine) is unchanged; this page just hosts it and
logs its Health credit on the first completion each day.
"""

from __future__ import annotations

import streamlit as st

from compass.ui import page_setup, render_morning_routine

db, student = page_setup("Morning Routine", icon="🧘")

# render_morning_routine draws its own "🧘 Morning Routine" heading, so no
# separate st.title here -- one heading, not two of the same.
render_morning_routine(db, student)

st.divider()
st.page_link("Home.py", label="Back to Home", icon="🏠")
