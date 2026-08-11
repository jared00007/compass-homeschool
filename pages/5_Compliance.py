"""Washington DOI compliance dashboard."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from compass import config
from compass.backup import (
    KEEP_DAILY_DAYS,
    list_snapshots,
)
from compass.backup import restore as restore_snapshot
from compass.backup import snapshot as take_snapshot
from compass.compliance import build_report, declaration_status
from compass.costs import WEB_SEARCH_COST_PER_QUERY, build_cost_report
from compass.ui import page_setup, parent_only, render_declaration_banner

db, student = page_setup("Compliance", icon="📋")

if not parent_only("The hours record and settings are for your parent."):
    st.stop()

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
st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

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
            "Tier": config.tier_label(tier, student["name"]),
            "Hours": round(report.minutes_by_tier.get(tier, 0) / 60, 1),
            "Share": (
                f"{round(100 * report.minutes_by_tier.get(tier, 0) / report.total_minutes)}%"
                if report.total_minutes
                else "—"
            ),
        }
        for tier in config.TIERS
    ]
    st.dataframe(pd.DataFrame(tier_rows), width="stretch", hide_index=True)

with right:
    st.subheader(config.tier_label(config.TIER_CHOICE, student["name"]))
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

st.subheader("What the agents cost to run")

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
        "Computed from the token counts each generation actually reported, not an "
        "estimate. Web search is billed per query at an assumed "
        f"${WEB_SEARCH_COST_PER_QUERY:.3f} — the one rate worth checking against the "
        "pricing page. Rates live in `compass/costs.py`."
    )

st.divider()

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

st.divider()

# --- Declaration of Intent ----------------------------------------------------

st.subheader("Declaration of Intent")
st.caption(
    "Washington requires filing this annually with your local school district — separate "
    "from hours and subjects, and not something logging a lesson satisfies."
)
render_declaration_banner(db, student)

with st.expander("Filing details and how Compass tracks this"):
    st.markdown(
        """
Every family electing to homeschool in Washington files a signed Declaration of Intent
with the superintendent of their local school district — by **September 15th**, or
within two weeks of starting home-based instruction if that's later in the year
(RCW 28A.200.010). There's no single statewide form or portal: each district runs its
own process, so Compass can't link you to yours automatically — paste it below once
you know it.
        """
    )
    due_columns = st.columns(2)
    with due_columns[0]:
        due_setting = st.text_input(
            "Filing deadline (MM-DD)", value=db.get_setting("declaration_due") or "09-15"
        )
        if due_setting != db.get_setting("declaration_due"):
            db.set_setting("declaration_due", due_setting)
            st.rerun()
    with due_columns[1]:
        url_setting = st.text_input(
            "Your district's filing page (optional)",
            value=db.get_setting("declaration_url") or "",
            placeholder="https://your-district.example/homeschool",
        )
        if url_setting != db.get_setting("declaration_url"):
            db.set_setting("declaration_url", url_setting.strip())
            st.rerun()

    ds = declaration_status(db, student["id"])
    if ds.filed and st.button("Undo — not actually filed"):
        db.clear_declaration_filed(student["id"], ds.due_on.isoformat())
        st.rerun()

st.divider()

# --- resources -----------------------------------------------------------------

st.subheader("Resources")
st.caption(
    "Official Washington state references — not maintained by Compass, so open "
    "them directly for anything that needs to be current."
)
resource_columns = st.columns(2)
with resource_columns[0]:
    st.link_button(
        "📕 OSPI Pink Book",
        "https://ospi.k12.wa.us/sites/default/files/2023-08/pinkbook.pdf",
        width="stretch",
    )
    st.caption(
        "\"Washington State's Laws Regulating Home-Based Instruction\" — OSPI's own "
        "guide to homeschool law: declaring intent, recordkeeping, and the annual "
        "assessment requirement."
    )
with resource_columns[1]:
    st.link_button(
        "📋 SBE Home-Based Instruction FAQs",
        "https://sbe.wa.gov/faqs/211",
        width="stretch",
    )
    st.caption(
        "State Board of Education FAQ on the annual assessment requirement "
        "specifically — a standardized test or a certificated person's written "
        "evaluation."
    )

st.divider()

# --- backups -----------------------------------------------------------------

st.subheader("Backups")
st.caption(
    "This year's logged hours are your documentation of instruction, and they live "
    "in a single file on this computer. Compass snapshots it once a day automatically."
)

snapshots = list_snapshots(db.path)
latest = snapshots[0] if snapshots else None
age_days = (date.today() - latest.taken_at.date()).days if latest else None

if latest:
    freshness = {0: "Today", 1: "Yesterday"}.get(age_days, f"{age_days} days ago")
else:
    freshness = "Never"

backup_columns = st.columns([1, 1, 2])
backup_columns[0].metric("Snapshots kept", len(snapshots))
backup_columns[1].metric(
    "Last backed up",
    freshness,
    help=f"Taken {latest.label}" if latest else "No snapshot has been taken yet.",
)
with backup_columns[2]:
    if st.button("Back up now", type="primary"):
        try:
            path = take_snapshot(db.conn, db.path, reason="manual")
            st.success(f"Saved {path.name}")
            st.rerun()
        except (OSError, sqlite3.Error) as exc:
            st.error(f"Backup failed: {exc}")

if latest is None:
    st.warning(
        "No snapshot exists yet. One is taken automatically the first time Compass "
        "opens each day, or press **Back up now**."
    )
elif age_days > 2:
    st.warning(
        f"The most recent snapshot is {age_days} days old. If Compass hasn't been "
        "opened in a while that's expected — press **Back up now** to be current."
    )

st.caption(
    f"Every snapshot from the last {KEEP_DAILY_DAYS} days is kept, then the first of "
    f"each month indefinitely. They live in `{db.path.parent / 'backups'}` — copy that "
    "folder to a cloud drive or a USB stick and the year survives losing this laptop."
)

if snapshots:
    with st.expander(f"All snapshots ({len(snapshots)})"):
        for snap in snapshots[:40]:
            snap_columns = st.columns([3, 1, 1])
            snap_columns[0].markdown(
                f"**{snap.label}** · {snap.reason} · {snap.size_kb:,} KB"
            )
            try:
                snap_columns[1].download_button(
                    "Download",
                    snap.path.read_bytes(),
                    file_name=snap.path.name,
                    mime="application/octet-stream",
                    key=f"dl_{snap.path.name}",
                )
            except OSError:
                snap_columns[1].caption("unreadable")
            if snap_columns[2].button("Restore", key=f"restore_{snap.path.name}"):
                st.session_state["pending_restore"] = str(snap.path)
                st.rerun()

pending = st.session_state.get("pending_restore")
if pending:
    st.error(
        f"**Restore from {Path(pending).name}?** This replaces everything currently "
        "in Compass — activities, lessons, mastery, books — with the contents of that "
        "snapshot. The current state is saved as its own snapshot first, so this can "
        "be undone."
    )
    confirm_columns = st.columns([1, 1, 4])
    if confirm_columns[0].button("Yes, restore", type="primary"):
        try:
            safety = restore_snapshot(db.conn, db.path, pending)
            st.session_state.pop("pending_restore", None)
            st.success(
                f"Restored. The previous state was saved as {safety.name} if you need "
                "it back."
            )
            st.cache_resource.clear()
            st.rerun()
        except (OSError, sqlite3.Error, FileNotFoundError) as exc:
            st.error(f"Restore failed, nothing was changed: {exc}")
    if confirm_columns[1].button("Cancel"):
        st.session_state.pop("pending_restore", None)
        st.rerun()

st.divider()
st.subheader("Export")

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
