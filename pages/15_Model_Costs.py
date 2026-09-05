"""What lesson generation actually costs -- separate from WA compliance
because it answers a different question (what are we spending?) for a
different reason (nothing here is a state requirement)."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from compass import config
from compass.costs import WEB_SEARCH_COST_PER_QUERY, build_cost_report
from compass.ui import page_setup, parent_only

db, student = page_setup("Model Costs", icon="💵")

if not parent_only("Spend on lesson generation is for your parent."):
    st.stop()

# Reached by a button on Mission Control now (not its own sidebar entry), so
# offer the trip back rather than leaving a folded page as a dead end.
if st.button("← Back to Mission Control", key="costs_back_to_mc"):
    st.switch_page("pages/14_Mission_Control.py")

st.title("💵 Model Costs")
st.caption(
    "What generating this student's lessons actually costs, computed from the "
    "token counts each generation reported -- not an estimate."
)

year_start, year_end = db.school_year_bounds()
columns = st.columns([1, 1, 2])
with columns[0]:
    start = st.date_input("From", value=date.fromisoformat(year_start))
with columns[1]:
    end = st.date_input("To", value=date.fromisoformat(year_end))

cost = build_cost_report(db, student["id"], start.isoformat(), end.isoformat())

if cost.total_lessons == 0:
    st.caption("No lessons generated in this range yet, so nothing has been billed.")
else:
    cost_columns = st.columns(4)
    cost_columns[0].metric("Spend in this range", f"${cost.total_cost:,.2f}")
    cost_columns[1].metric("Lessons generated", cost.total_lessons)
    cost_columns[2].metric("Average per lesson", f"${cost.per_lesson:.3f}")
    projected = cost.projected_year_cost()
    cost_columns[3].metric(
        "Projected for the year",
        f"${projected:,.0f}" if projected else "—",
        help="Straight-line from spend so far. Hidden until at least 5 lessons exist.",
    )

    if cost.by_agent:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Agent": entry.agent.title(),
                        "Lessons": entry.lessons,
                        "Cost": f"${entry.cost:.2f}",
                        "Per lesson": f"${entry.per_lesson:.3f}",
                        "Input tokens": f"{entry.input_tokens:,}",
                        "Output tokens": f"{entry.output_tokens:,}",
                        "Web searches": entry.web_searches,
                    }
                    for entry in cost.by_agent
                ]
            ),
            width="stretch",
            hide_index=True,
        )

    if cost.unmeasured_lessons:
        st.caption(
            f"{cost.unmeasured_lessons} lesson(s) in this range have no usage recorded "
            "and are excluded from the totals above."
        )

    st.caption(
        "Web search is billed per query at an assumed "
        f"${WEB_SEARCH_COST_PER_QUERY:.3f} — the one rate worth checking against the "
        "pricing page. Rates live in `compass/costs.py`."
    )

st.divider()

st.subheader("Model effort")
st.caption(
    "How much the model reasons before writing each lesson -- the single "
    "biggest lever on generation cost. High is the default, and what every "
    "lesson has used so far. Medium cuts cost meaningfully with some quality "
    "tradeoff; switch here only if cost ever needs to come down."
)

current_effort = db.get_setting("effort_level") or config.DEFAULT_EFFORT
if current_effort not in config.EFFORT_LEVELS:
    current_effort = config.DEFAULT_EFFORT
effort_choice = st.selectbox(
    "Family default",
    config.EFFORT_LEVELS,
    index=config.EFFORT_LEVELS.index(current_effort),
    format_func=config.effort_label,
    key="effort_level_select",
)
if effort_choice != current_effort:
    db.set_setting("effort_level", effort_choice)
    st.rerun()
