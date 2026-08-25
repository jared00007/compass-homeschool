"""Quiz history -- every graded attempt, not just the most recent one.

The in-app quiz (compass/agents/quiz.py, compass.ui.render_quiz) used to keep
which questions he missed only in the browser's own session state -- gone
the moment that tab closed, and a second attempt at the same lesson simply
overwrote the first score with no record either attempt had happened.
Database.record_quiz_result now also inserts a row into quiz_attempts, one
per graded attempt, with the full per-question detail; this page is where
that history actually surfaces.
"""

from __future__ import annotations

import streamlit as st

from compass.subjects import label
from compass.ui import SUBJECT_ICONS, format_duration, md, page_setup, parent_only

db, student = page_setup("Quizzes", icon="📝")

if not parent_only("Quiz history is for your parent."):
    st.stop()

st.title("📝 Quizzes")
st.caption(
    "Every graded attempt, not just the latest — how many tries, each score, "
    "and exactly which questions he missed on each one."
)

attempts = db.list_quiz_attempts(student["id"])

if not attempts:
    st.info("No quizzes taken yet.")
    st.stop()

passed_count = sum(1 for a in attempts if a["passed"])
distinct_lessons = len({a["lesson_id"] for a in attempts})

metrics = st.columns(3)
metrics[0].metric("Quizzes taken", len(attempts))
metrics[1].metric("Passed", f"{passed_count}/{len(attempts)}")
metrics[2].metric("Lessons quizzed", distinct_lessons)

st.divider()

# Grouped by lesson so retakes read as one story (a score trend across
# tries) instead of scattered, unrelated rows -- each group sorted oldest
# attempt first so that trend reads left-to-right the way it happened.
by_lesson: dict[int, list[dict]] = {}
for attempt in attempts:
    by_lesson.setdefault(attempt["lesson_id"], []).append(attempt)
for group in by_lesson.values():
    group.sort(key=lambda a: (a["created_at"], a["id"]))

lesson_order = sorted(
    by_lesson, key=lambda lid: by_lesson[lid][-1]["created_at"], reverse=True
)

subjects_present = sorted({a["subject"] for a in attempts})
subject_filter = st.multiselect(
    "Filter by subject", subjects_present, format_func=label
)

for lesson_id in lesson_order:
    group = by_lesson[lesson_id]
    latest = group[-1]
    if subject_filter and latest["subject"] not in subject_filter:
        continue

    icon = SUBJECT_ICONS.get(latest["agent"], "📘")
    latest_pct = round(100 * latest["correct"] / latest["total"]) if latest["total"] else 0
    trophy = " 🎯" if latest["passed"] else ""
    attempt_word = "attempt" if len(group) == 1 else "attempts"

    with st.container(border=True):
        st.markdown(f"**{icon} {md(latest['lesson_title'])}**")
        st.caption(
            f"{label(latest['subject'])} · {len(group)} {attempt_word} · "
            f"latest {latest['correct']}/{latest['total']} ({latest_pct}%){trophy}"
        )
        if len(group) > 1:
            trend = " → ".join(f"{a['correct']}/{a['total']}" for a in group)
            st.caption(f"Score over tries: {trend}")

        for attempt in reversed(group):
            pct = round(100 * attempt["correct"] / attempt["total"]) if attempt["total"] else 0
            verdict = "✅ passed" if attempt["passed"] else "❌ did not pass"
            duration = attempt.get("duration_seconds")
            took = f" — took {format_duration(duration)}" if duration is not None else ""
            with st.expander(
                f"{attempt['attempted_on']} — {attempt['correct']}/{attempt['total']} "
                f"({pct}%) — {verdict}{took}"
            ):
                if not attempt["detail"]:
                    st.caption("No per-question detail was saved for this attempt.")
                    continue
                for index, item in enumerate(attempt["detail"], start=1):
                    right = item.get("pick") == item.get("correct_index")
                    marker = "✅" if right else "❌"
                    st.markdown(f"{marker} **{index}. {md(item['question'])}**")
                    for choice_index, choice in enumerate(item.get("choices") or []):
                        tag = ""
                        if choice_index == item.get("correct_index"):
                            tag = " — correct answer"
                        elif choice_index == item.get("pick"):
                            tag = " — his answer"
                        st.markdown(f"- {md(choice)}{tag}")
                    if item.get("explanation"):
                        st.caption(md(item["explanation"]))
