"""Courses -- grades 6-12 credit documentation for Sumner-Bonney Lake's
diploma requirements.

A district packet requirement, separate from the K-8 "1,000 annual hours"
declaration this app was built around first: to count a course toward the
diploma, the district wants a description, goals/objectives, an outline, a
log of instructional time (150 hours = 1 credit), completed assignments and
assessments, a description of how performance is assessed, and documentation
of progress plus a final grade (converted to Pass/Fail on the transcript).

A course here is a container a parent points at a slice of already-logged
activities (matched by subject + date range, hand-adjustable) rather than a
separate place to re-enter lesson content -- the activities and their
generated lessons already carry the assignment and assessment detail this
packet needs. Parent-only throughout: this is compliance paperwork, not
something to hand him.
"""

from __future__ import annotations

from datetime import date
from functools import partial

import streamlit as st

from compass import config
from compass.export import course_filename, course_to_docx
from compass.subjects import SUBJECT_KEYS, label
from compass.ui import md, page_setup, parent_only

db, student = page_setup("Courses", icon="🎓")

st.title("🎓 Courses")
st.caption(
    "Grades 6-12 course documentation, one packet per course: description, "
    "goals and objectives, outline, a 150-hour-per-credit instructional time "
    "log, completed assignments and assessments, how performance is "
    "assessed, and a final grade (recorded as Pass/Fail on the transcript)."
)

if not parent_only("Course records are for your parent."):
    st.stop()

courses = db.list_courses(student["id"])
list_tab, add_tab = st.tabs(["Courses", "Add a course"])

with list_tab:
    if not courses:
        st.info("No courses yet — add one in the **Add a course** tab.")
    for course in courses:
        minutes = db.course_minutes(course["id"])
        hours = round(minutes / 60, 1)
        target_hours = round(config.CREDIT_HOURS_PER_UNIT * course["credit_value"], 1)
        progress = min(hours / target_hours, 1.0) if target_hours else 0.0

        pass_fail_badge = {"pass": " · ✅ Pass", "fail": " · ❌ Fail"}.get(course["pass_fail"], "")

        # A real st.expander resets to collapsed on every rerun -- fine for a
        # card nobody interacts with, but this one has checkboxes and forms
        # inside it, each of which reruns the page. A plain expander would
        # snap shut after every single checkbox click. Session-state-backed
        # open/close (same pattern Big Projects uses) survives those reruns;
        # it only starts collapsed on a fresh app launch.
        open_key = f"course_open_{course['id']}"
        if open_key not in st.session_state:
            st.session_state[open_key] = False
        with st.container(border=True):
            header_columns = st.columns([20, 3])
            with header_columns[0]:
                st.markdown(
                    f"**{md(course['title'])}** — {label(course['credit_subject'])} · "
                    f"{course['credit_value']:g} credit · {hours:g}/{target_hours:g} hrs"
                    f"{pass_fail_badge}"
                )
            with header_columns[1]:
                if st.button(
                    "Hide" if st.session_state[open_key] else "Show",
                    key=f"toggle_course_{course['id']}",
                    width="stretch",
                ):
                    st.session_state[open_key] = not st.session_state[open_key]
                    st.rerun()

            if not st.session_state[open_key]:
                continue

            st.progress(progress, text=f"{hours:g} of {target_hours:g} hours")
            st.caption(
                f"Grade {course['grade_level'] or '—'} · "
                f"{course['start_date']} through {course['end_date']}"
            )

            with st.form(f"edit_course_{course['id']}"):
                description = st.text_area(
                    "Course description", value=course["description"], height=80
                )
                goals = st.text_area(
                    "Course goals and objectives", value=course["goals"], height=80
                )
                outline = st.text_area(
                    "Course outline of the program", value=course["outline"], height=100
                )
                if st.form_submit_button("Save details"):
                    db.update_course(
                        course["id"],
                        description=description.strip(),
                        goals=goals.strip(),
                        outline=outline.strip(),
                    )
                    st.rerun()

            st.markdown("**Activities counted toward this course**")
            candidates = db.candidate_activities_for_course(
                student["id"],
                course["credit_subject"],
                course["start_date"],
                course["end_date"],
                course["id"],
            )
            if not candidates:
                st.caption(
                    f"No {label(course['credit_subject'])} activities logged yet in this "
                    "date range."
                )
            else:
                st.caption("Matched by subject and date range — uncheck anything that doesn't belong.")
                for activity in candidates:
                    checked = st.checkbox(
                        f"{activity['occurred_on']} — {md(activity['title'])} "
                        f"({activity['minutes']} min)",
                        value=activity["course_id"] == course["id"],
                        key=f"course_activity_{course['id']}_{activity['id']}",
                    )
                    already_in = activity["course_id"] == course["id"]
                    if checked and not already_in:
                        db.set_activity_course(activity["id"], course["id"])
                        st.rerun()
                    elif not checked and already_in:
                        db.set_activity_course(activity["id"], None)
                        st.rerun()

            st.markdown("**Progress and final grade**")
            grade_columns = st.columns(2)
            with grade_columns[0]:
                final_grade = st.text_input(
                    "Final grade (your own record)",
                    value=course["final_grade"],
                    key=f"grade_{course['id']}",
                    placeholder="e.g. A, 92%, Meets expectations",
                )
            with grade_columns[1]:
                pf_options = ["Not yet decided", "Pass", "Fail"]
                current_pf = {"pass": "Pass", "fail": "Fail"}.get(
                    course["pass_fail"], "Not yet decided"
                )
                picked_pf = st.selectbox(
                    "Transcript record",
                    pf_options,
                    index=pf_options.index(current_pf),
                    key=f"pf_{course['id']}",
                )
            if st.button("Save grade", key=f"save_grade_{course['id']}"):
                db.update_course(
                    course["id"],
                    final_grade=final_grade.strip(),
                    pass_fail={"Pass": "pass", "Fail": "fail"}.get(picked_pf),
                )
                st.rerun()

            st.divider()
            activities = db.course_activities(course["id"])
            action_columns = st.columns(2)
            with action_columns[0]:
                st.download_button(
                    "📄 Download course documentation packet",
                    data=partial(course_to_docx, course, activities, student["name"]),
                    file_name=course_filename(course),
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"course_download_{course['id']}",
                )
            with action_columns[1]:
                if st.button("Delete this course", key=f"delete_course_{course['id']}"):
                    db.delete_course(course["id"])
                    st.rerun()

with add_tab:
    st.markdown("#### Add a course")
    default_start, default_end = db.school_year_bounds()
    with st.form("add_course", clear_on_submit=True):
        title = st.text_input("Course title", placeholder="e.g. Washington State History")
        columns = st.columns(3)
        credit_subject = columns[0].selectbox("Subject", SUBJECT_KEYS, format_func=label)
        grade_level = columns[1].text_input("Grade level", value=student["grade"])
        credit_value = columns[2].number_input(
            "Credit value", min_value=0.25, max_value=2.0, value=1.0, step=0.25
        )
        date_columns = st.columns(2)
        start = date_columns[0].date_input(
            "Start date", value=date.fromisoformat(default_start)
        )
        end = date_columns[1].date_input("End date", value=date.fromisoformat(default_end))
        description = st.text_area("Course description", height=80)
        goals = st.text_area("Course goals and objectives", height=80)
        outline = st.text_area("Course outline of the program", height=100)
        if st.form_submit_button("Add course", type="primary") and title.strip():
            db.create_course(
                student["id"],
                title.strip(),
                credit_subject,
                start.isoformat(),
                end.isoformat(),
                grade_level=grade_level.strip(),
                description=description.strip(),
                goals=goals.strip(),
                outline=outline.strip(),
                credit_value=float(credit_value),
            )
            st.rerun()
