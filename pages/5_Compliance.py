"""Washington DOI compliance dashboard."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from compass import config
from compass.compliance import build_report
from compass.ui import page_setup

db, student = page_setup("Compliance", icon="📋")

st.title("📋 WA Compliance")
st.caption(
    "Washington requires instruction across eleven subjects and 1,000 instructional "
    "hours per year. Every agent logs into this one dashboard."
)

year_start, year_end = db.school_year_bounds()
columns = st.columns([1, 1, 2])
with columns[0]:
    start = st.date_input("From", value=date.fromisoformat(year_start))
with columns[1]:
    end = st.date_input("To", value=date.fromisoformat(year_end))

report = build_report(db, student["id"], start.isoformat(), end.isoformat())
pace = report.pace()

# --- headline ----------------------------------------------------------------

metrics = st.columns(4)
metrics[0].metric("Instructional hours", f"{report.total_hours:g} / {report.hour_target}")
metrics[1].metric("Days of instruction", f"{report.instructional_days} / {report.day_target}")
metrics[2].metric("Subjects with instruction", f"{report.subjects_covered} / 11")
metrics[3].metric(
    "Pace",
    f"{pace['ahead_by']:+g} hrs",
    help=f"Against an even pace you'd be at {pace['expected_hours_by_now']:g} hours by today.",
)

st.progress(report.hour_progress, text=f"Hours — {report.total_hours:g} of {report.hour_target}")
st.progress(
    report.day_progress, text=f"Days — {report.instructional_days} of {report.day_target}"
)

if report.hours_remaining and pace["remaining_days"] > 0:
    if pace["achievable"]:
        st.caption(
            f"{report.hours_remaining:g} hours remaining · about "
            f"{pace['hours_per_week_needed']:g} hours/week over the "
            f"{pace['remaining_days']} days left."
        )
    else:
        st.caption(
            f"{report.hours_remaining:g} hours remaining with only "
            f"{pace['remaining_days']} days left — that would take "
            f"{pace['hours_per_week_needed']:g} hours/week, which isn't a realistic plan. "
            "If hours were taught but not logged, backfill them in the Activity Log; "
            "otherwise adjust the year's dates or target below."
        )

if report.activity_count == 0:
    # Don't let a parent stare at a red 0/1000 when the real cause is the date range.
    all_time = db.list_activities(student["id"], limit=1)
    if all_time:
        st.info(
            f"Nothing is logged between {start} and {end}, but there is activity outside "
            f"this range — the most recent is {all_time[0]['occurred_on']}. Widen the "
            "dates above, or check the school-year start date at the bottom of this page."
        )
    else:
        st.info("Nothing logged yet. Generate a lesson or log an activity to start the record.")

for warning in report.warnings:
    st.warning(warning)
if report.all_subjects_covered and report.total_hours >= report.hour_target:
    st.success("All eleven subjects covered and the hour floor is met for this period.")

st.divider()

# --- the counting rule -------------------------------------------------------

with st.expander("How these numbers are counted", expanded=False):
    credited_total = sum(s.minutes for s in report.subjects)
    st.markdown(
        f"""
**Total hours** come from the logged length of each activity: **{report.total_minutes} minutes**
across {report.activity_count} activities. That is what counts toward the 1,000-hour floor.

**Per-subject hours** come from multi-subject credit and total **{credited_total} minutes** —
more than the elapsed time, on purpose. One 60-minute waterfall lesson can legitimately
credit science, writing, and art at once; that's Tier 2 folding, and it's how eleven
subjects get covered without running eleven subjects.

The two figures are **not** meant to reconcile. Summing the per-subject credits to get a
year total would inflate this year by about
{round(100 * (credited_total / report.total_minutes - 1)) if report.total_minutes else 0}%.
        """
    )

# --- the eleven subjects -----------------------------------------------------

st.subheader("The eleven required subjects")
rows = [
    {
        "Subject": s.label,
        "Hours": s.hours,
        "Activities": s.activity_count,
        "Last taught": s.last_taught or "—",
        "Status": "✅ covered" if s.has_instruction else "⬜ no instruction logged",
    }
    for s in report.subjects
]
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

chart = pd.DataFrame(
    {"Subject": [s.label for s in report.subjects], "Hours": [s.hours for s in report.subjects]}
).set_index("Subject")
st.bar_chart(chart, height=320)

st.divider()

# --- tiers -------------------------------------------------------------------

left, right = st.columns(2)

with left:
    st.subheader("Hours by tier")
    tier_rows = [
        {
            "Tier": config.TIER_LABELS[tier],
            "Hours": round(report.minutes_by_tier.get(tier, 0) / 60, 1),
            "Share": (
                f"{round(100 * report.minutes_by_tier.get(tier, 0) / report.total_minutes)}%"
                if report.total_minutes
                else "—"
            ),
        }
        for tier in config.TIERS
    ]
    st.dataframe(pd.DataFrame(tier_rows), use_container_width=True, hide_index=True)

with right:
    st.subheader("Tier 3 — his choice")
    st.metric(
        "Share of logged hours",
        f"{report.tier3_percent:g}%",
        delta=f"guideline {report.tier3_cap_percent}%",
        delta_color="inverse" if report.tier3_over_cap else "off",
    )
    st.caption(
        "Washington mandates no split between structured and elective hours, so this is a "
        "family policy guideline, not a compliance rule. Tier 3 hours always count in full."
    )
    new_cap = st.slider(
        "Tier 3 guideline (%)", 0, 100, report.tier3_cap_percent, step=5
    )
    if new_cap != report.tier3_cap_percent:
        db.set_setting("tier3_cap_percent", str(new_cap))
        st.rerun()

st.divider()

# --- settings + export -------------------------------------------------------

st.subheader("Year settings and export")
columns = st.columns(3)
with columns[0]:
    hours = st.number_input(
        "Annual hour target",
        min_value=config.WA_ANNUAL_HOURS,
        max_value=2000,
        value=report.hour_target,
        step=25,
        help="Cannot be set below Washington's 1,000-hour floor.",
    )
    if hours != report.hour_target:
        db.set_setting("annual_hour_target", str(int(hours)))
        st.rerun()
with columns[1]:
    days = st.number_input(
        "Annual day target", min_value=1, max_value=365, value=report.day_target, step=5
    )
    if days != report.day_target:
        db.set_setting("annual_day_target", str(int(days)))
        st.rerun()
with columns[2]:
    year_start_setting = st.text_input(
        "School year starts (MM-DD)", value=db.get_setting("school_year_start") or "09-01"
    )
    if year_start_setting != db.get_setting("school_year_start"):
        db.set_setting("school_year_start", year_start_setting)
        st.rerun()

activities = db.list_activities(student["id"], start=start.isoformat(), end=end.isoformat())
if activities:
    export_rows = []
    for activity in activities:
        row = {
            "date": activity["occurred_on"],
            "title": activity["title"],
            "tier": activity["tier"],
            "primary_subject": activity["primary_subject"],
            "minutes": activity["minutes"],
            "source": activity["source"],
            "location": activity["location"],
        }
        row.update({f"credit_{k}": v for k, v in activity["credits"].items()})
        export_rows.append(row)
    csv = pd.DataFrame(export_rows).to_csv(index=False).encode()
    st.download_button(
        "Download the instructional record (CSV)",
        csv,
        file_name=f"compass-record-{start}-to-{end}.csv",
        mime="text/csv",
    )
