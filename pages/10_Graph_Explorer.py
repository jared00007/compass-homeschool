"""The Slope & Intercept Explorer -- a hands-on grapher for linear relationships.

A standing math manipulative, not a lesson: Landon (or a parent sitting with
him) moves the sliders and watches the line, the table, and the equation move
together. Built for the exact thing he was stuck on -- graphing proportional
relationships and reading intercepts -- but it works for any y = mx + b. Zero
model calls: it's pure browser math, so he can play as long as he likes.
"""

from __future__ import annotations

import streamlit as st

from compass.agents import api_available
from compass.ui import (
    is_parent,
    page_setup,
    render_graph_explorer,
    render_graphing_diagnostic,
    render_graphing_ladder_builder,
    render_graphing_missions_card,
)

db, student = page_setup("Graphing", icon="📈")

st.title("📈 Slope & Intercept Explorer")
st.caption(
    "Move the two sliders and watch everything move together — the line, the "
    "table, and the equation are all the **same** relationship."
)

if is_parent():
    with st.expander("How to use this with him"):
        st.markdown(
            "- **Steep slider = the slope = the unit rate.** Drag it and watch the "
            "line tip, the equation's number grow, and the table's jumps get bigger — "
            "they're one number shown three ways.\n"
            "- **Start slider = the y-intercept.** Slide it and the whole line moves "
            "up or down. When it's **0**, the line goes through the corner (0,0) — "
            "that's the fingerprint of a *proportional* relationship.\n"
            "- Work the **Missions** in order, then the **Mystery Line Challenge** — "
            "that's him reading a graph *backwards* into an equation, in two steps: "
            "①  where it starts (the gray dot on the y-axis), then ② how steep (right "
            "1, count up/down). **💡 Hint** walks him through both; the feedback tells "
            "him which way to move.\n"
            "- Good talking track: *“What has to be true for the line to go through the "
            "corner?”* and *“Same steepness — what changed when it started at 5?”*"
        )

render_graph_explorer()

st.divider()

# Find the gap — a quick check that pinpoints the shaky rung. Open to everyone:
# Landon answers it, and the readout steers both of you to the right spot.
render_graphing_diagnostic(db, student)

# Parent actions (assigning work / building lessons) are gated to the parent view.
if is_parent():
    st.divider()
    render_graphing_missions_card(db, student)
    st.divider()
    render_graphing_ladder_builder(db, student, api_ok=api_available())

