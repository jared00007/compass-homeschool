"""Streamlit helpers shared across pages.

Kept out of `compass/` core modules on purpose — the agents, storage, and
compliance layers know nothing about Streamlit, so they stay testable and
reusable if the UI is ever replaced.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from functools import partial
from typing import Any

import streamlit as st

from compass import auth, config, subjects, theme as theming
from compass.backup import auto_snapshot
from compass.agents import (
    GeneratedLesson,
    LessonAgent,
    LessonGenerationError,
    StudentContext,
)
from compass.agents.quiz import grade, passed as quiz_passes
from compass.compliance import declaration_status
from compass.export import lesson_to_docx, suggested_filename
from compass.school_calendar import next_annual_date
from compass.storage.db import Database


@st.cache_resource
def get_db() -> Database:
    db = Database()
    # One snapshot per calendar day, taken on first open. Cheap on every
    # subsequent open, and it means the compliance record survives the laptop.
    try:
        auto_snapshot(db.conn, db.path)
    except (OSError, sqlite3.Error):
        # A backup problem must never stop the family using the app; the
        # Compliance page surfaces the real state of the backups.
        pass
    return db


def page_setup(title: str, icon: str = "🧭") -> tuple[Database, dict[str, Any]]:
    st.set_page_config(page_title=f"Compass — {title}", page_icon=icon, layout="wide")
    db = get_db()
    student = db.ensure_default_student()
    # Before anything renders, so the page never flashes the wrong colours.
    st.markdown(theming.css(current_theme(db)), unsafe_allow_html=True)
    _sidebar(db, student)
    return db, student


# --- theme -------------------------------------------------------------------


def _theme_key(db: Database) -> str:
    """Which settings key holds the theme for whoever is looking."""
    return theming.PARENT_KEY if is_parent() else theming.STUDENT_KEY


def current_theme(db: Database) -> theming.Theme:
    return theming.get(db.get_setting(_theme_key(db), theming.DEFAULT_THEME))


def _theme_control(db: Database) -> None:
    """Theme picker. Deliberately not tucked inside an expander — the whole
    point is that he finds it and changes it himself."""
    keys = list(theming.THEMES)
    active = db.get_setting(_theme_key(db), theming.DEFAULT_THEME)

    chosen = st.selectbox(
        "🎨 Look",
        keys,
        index=keys.index(active) if active in keys else 0,
        format_func=lambda k: theming.THEMES[k].name,
        key="theme_choice",
        help="Changes how Compass looks. Your parent's view keeps its own setting."
        if not is_parent()
        else "Changes how Compass looks for you. His view keeps its own setting.",
    )
    st.caption(theming.THEMES[chosen].tagline)
    if chosen != active:
        db.set_setting(_theme_key(db), chosen)
        st.rerun()


# --- parent / student mode ---------------------------------------------------
#
# When a PIN is set, every new browser session starts in student mode. That's the
# right default: he opens the app far more often than you do, and the failure that
# matters is the answer key being visible when nobody meant it to be.


def is_parent() -> bool:
    """True when parent-only content should be shown."""
    db = get_db()
    if not auth.pin_is_set(db):
        return True  # No PIN configured — the app behaves as it always has.
    return bool(st.session_state.get("parent_unlocked", False))


def _sidebar(db: Database, student: dict[str, Any]) -> None:
    with st.sidebar:
        st.markdown(f"### 🧭 Compass\n**{student['name']}** · Grade {student['grade']}")
        start, end = db.school_year_bounds()
        st.caption(f"School year {start} → {end}")
        _profile_control(db, student)
        st.divider()
        _mode_control(db)
        _theme_control(db)


def _profile_control(db: Database, student: dict[str, Any]) -> None:
    """Edit the student's name, grade, age, and interests.

    Parent-only: `interests` feeds every agent's system prompt, so this is
    configuration, not a preference — the same reasoning that keeps Tier 1
    strategy choices out of student hands.
    """
    if not is_parent():
        return
    with st.expander("✏️ Edit his profile"):
        with st.form("edit_profile"):
            name = st.text_input("Name", value=student["name"])
            columns = st.columns(2)
            grade = columns[0].text_input("Grade", value=student["grade"])
            age = columns[1].number_input(
                "Age", min_value=5, max_value=19, value=int(student["age"] or 13)
            )
            interests = st.text_area(
                "Interests he's told us about",
                value=student.get("interests") or "",
                height=70,
                help="Read by every agent when it writes a lesson.",
            )
            if st.form_submit_button("Save", type="primary"):
                db.update_student(
                    student["id"],
                    name=name.strip() or "Student",
                    grade=grade.strip() or "8",
                    age=int(age),
                    interests=interests.strip(),
                )
                st.success("Saved.")
                st.rerun()


def _mode_control(db: Database) -> None:
    if not auth.pin_is_set(db):
        st.caption("**Parent view** — everything visible.")
        with st.expander("Set a parent PIN"):
            st.caption(
                "Hides answer keys, mastery criteria, and parent notes from the student "
                "view, and keeps lesson generation and the records behind a PIN."
            )
            pin = st.text_input("New PIN", type="password", key="pin_new")
            again = st.text_input("Confirm", type="password", key="pin_again")
            if st.button("Turn on student view"):
                if pin != again:
                    st.error("Those don't match.")
                else:
                    try:
                        auth.set_pin(db, pin)
                    except auth.PinError as exc:
                        st.error(str(exc))
                    else:
                        st.session_state["parent_unlocked"] = True
                        st.success("Student view is on. Write the PIN down somewhere.")
                        st.rerun()
        return

    if is_parent():
        st.caption("🔓 **Parent view**")
        if st.button("Switch to student view", use_container_width=True):
            st.session_state["parent_unlocked"] = False
            st.rerun()
        with st.expander("Change or remove the PIN"):
            current = st.text_input("Current PIN", type="password", key="pin_cur")
            replacement = st.text_input("New PIN (blank to remove)", type="password", key="pin_rep")
            if st.button("Save"):
                if not auth.verify(db, current):
                    st.error("That PIN is not right.")
                elif replacement.strip() == "":
                    auth.clear_pin(db)
                    st.success("PIN removed — everything is visible again.")
                    st.rerun()
                else:
                    try:
                        auth.set_pin(db, replacement)
                    except auth.PinError as exc:
                        st.error(str(exc))
                    else:
                        st.success("PIN changed.")
                        st.rerun()
        return

    st.caption("🎒 **Student view**")
    with st.expander("Parent unlock"):
        pin = st.text_input("PIN", type="password", key="pin_unlock")
        if st.button("Unlock", use_container_width=True):
            if auth.verify(db, pin):
                st.session_state["parent_unlocked"] = True
                st.rerun()
            else:
                st.error("Not right. Try again.")


def parent_only(message: str = "") -> bool:
    """Guard for a whole page. Returns True when the parent view is active."""
    if is_parent():
        return True
    st.info(
        message
        or "This part is for your parent. Use **Parent unlock** in the sidebar if that's you."
    )
    return False


def context_for(
    db: Database, student: dict[str, Any], **inputs: Any
) -> StudentContext:
    return StudentContext(
        db=db, student_id=student["id"], student=student, inputs=inputs
    )


# --- the generate → review → log loop ----------------------------------------


def generate_and_log(
    db: Database,
    student: dict[str, Any],
    agent: LessonAgent,
    ctx: StudentContext,
    proposal,
    *,
    primary_subject: str,
    spinner: str,
    api_ok: bool,
    location: str = "",
    after_render: str = "",
) -> None:
    """The whole Tier 1 loop: generate, surface warnings, render, offer to log.

    All four agent pages ran a near-identical copy of this. Keeping one copy
    matters beyond tidiness: the redaction in `render_lesson` and the warnings
    from credit/video normalization are the two things that must never be
    skipped on any page, and four hand-maintained copies is four chances to
    forget one.

    The generated lesson is held in session state under the agent's own key, so
    a rerun (logging hours, changing a widget) doesn't lose an expensive lesson.
    """
    state_key = f"{agent.key}_lesson"

    if st.button("Generate lesson", type="primary", disabled=not api_ok or proposal.blocked):
        with st.spinner(spinner):
            try:
                st.session_state[state_key] = agent.generate(ctx, proposal)
            except LessonGenerationError as exc:
                st.error(str(exc))

    generated = st.session_state.get(state_key)
    if not generated:
        return

    st.divider()
    for warning in generated.warnings:
        st.caption(f"⚠️ {warning}")
    render_lesson(generated.payload)
    st.download_button(
        "📄 Download as Word doc",
        data=partial(lesson_to_docx, generated.payload),
        file_name=suggested_filename(generated.payload),
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key=f"{agent.key}_docx_download",
    )
    if after_render:
        st.caption(after_render)
    st.divider()
    log_lesson_form(
        db,
        student,
        generated,
        source=agent.key,
        primary_subject=primary_subject,
        location=location,
        key_prefix=agent.key,
    )


# --- lesson rendering --------------------------------------------------------


def render_proposal(agent: LessonAgent, proposal) -> None:
    if proposal.blocked:
        st.warning(f"**{agent.name} can't plan a lesson yet.**\n\n{proposal.blocked_reason}")
        return
    st.info(f"**Next up: {proposal.topic}**\n\n{proposal.rationale}")
    if proposal.context_lines:
        with st.expander("What the agent knows going in"):
            for line in proposal.context_lines:
                st.markdown(f"- {line}")


def render_lesson(lesson: dict[str, Any], for_parent: bool | None = None) -> None:
    """Render a lesson. In student view the answer key never reaches the page.

    The redaction happens here rather than in a CSS class or an expander, because
    anything sent to the browser can be read out of it. What a student must not
    see is simply not written.
    """
    parent = is_parent() if for_parent is None else for_parent

    st.subheader(lesson.get("title", "Lesson"))
    if lesson.get("overview"):
        st.write(lesson["overview"])

    objectives = lesson.get("learning_objectives") or []
    if objectives:
        st.markdown("**Learning objectives**")
        for objective in objectives:
            st.markdown(f"- {objective}")

    activities = lesson.get("activities") or []
    if activities:
        st.markdown("**Activities**")
        for index, activity in enumerate(activities, start=1):
            header = (
                f"{index}. {activity.get('title', 'Activity')} · "
                f"{activity.get('kind', '')} · {activity.get('minutes', 0)} min"
            )
            with st.expander(header, expanded=index == 1):
                st.write(activity.get("instructions", ""))

    columns = st.columns(2)
    with columns[0]:
        materials = lesson.get("materials") or []
        if materials:
            st.markdown("**Materials**")
            for item in materials:
                st.markdown(f"- {item}")
    with columns[1]:
        assessment = lesson.get("assessment") or {}
        if assessment and parent:
            st.markdown("**Assessment**")
            st.markdown(f"*{assessment.get('kind', '')}* — {assessment.get('description', '')}")
            if assessment.get("mastery_criteria"):
                st.markdown(f"**Mastery:** {assessment['mastery_criteria']}")
        elif assessment:
            st.markdown("**Assessment**")
            st.caption(
                "There's a check at the end of this lesson — your parent has it."
            )

    # Shown to both views. Verified against a real search result and restricted
    # to YouTube (see compass/agents/video.py) before it ever gets this far, so
    # there's nothing here for the student's version to redact.
    video = lesson.get("video") or {}
    if video.get("found") and video.get("url"):
        with st.expander(f"▶️ Suggested video — {video.get('title') or 'watch'}"):
            st.markdown(f"**[{video.get('title', 'Watch')}]({video['url']})**")
            if video.get("channel"):
                st.caption(video["channel"])
            if video.get("why"):
                st.write(video["why"])
            if parent:
                st.caption(
                    "Checked against a real search result and restricted to YouTube, "
                    "but Compass doesn't control what YouTube recommends once the "
                    "video ends."
                )

    if parent:
        if lesson.get("parent_notes"):
            with st.expander("Notes for the parent"):
                st.write(lesson["parent_notes"])

        credits = lesson.get("subject_credits") or []
        if credits:
            st.markdown("**Subject credit (feeds the WA compliance dashboard)**")
            for credit in credits:
                st.markdown(
                    f"- **{subjects.label(credit['subject'])}** — {credit['minutes']} min · "
                    f"{credit.get('justification', '')}"
                )

        branches = lesson.get("branches") or []
        if branches:
            with st.expander(f"Branches this opens up ({len(branches)})"):
                for branch in branches:
                    st.markdown(f"- **{branch.get('topic')}** — {branch.get('rationale', '')}")

        quiz = lesson.get("quiz") or []
        if quiz:
            with st.expander(f"Quiz answer key ({len(quiz)} questions)"):
                for index, item in enumerate(quiz, start=1):
                    st.markdown(f"**{index}. {item['question']}**")
                    for choice_index, choice in enumerate(item["choices"]):
                        marker = "✅" if choice_index == item["correct_index"] else "—"
                        st.markdown(f"{marker} {choice}")
                    if item.get("explanation"):
                        st.caption(item["explanation"])


def render_life_skill_plan(plan: dict[str, Any]) -> None:
    """Render a life-skill teaching plan. Parent-facing throughout.

    Unlike a Tier 1 lesson there's no student view of this and no redaction to
    do: a life skill is something the parent runs standing next to him, so the
    plan is addressed to them. Guard the call site, not the fields.
    """
    st.subheader(plan.get("title", "Session plan"))
    if plan.get("overview"):
        st.write(plan["overview"])

    columns = st.columns(2)
    with columns[0]:
        prep = (plan.get("prep") or "").strip()
        if prep and prep.lower().rstrip(".") != "nothing":
            st.markdown("**Before you start**")
            st.write(prep)
    with columns[1]:
        materials = plan.get("materials") or []
        if materials:
            st.markdown("**What you need**")
            for item in materials:
                st.markdown(f"- {item}")

    steps = plan.get("steps") or []
    if steps:
        st.markdown("**How to run it**")
        for index, step in enumerate(steps, start=1):
            header = f"{index}. {step.get('title', 'Step')} · {step.get('minutes', 0)} min"
            with st.expander(header, expanded=index == 1):
                st.markdown("**He does**")
                st.write(step.get("what_he_does", ""))
                st.markdown("**You do**")
                st.write(step.get("what_you_do", ""))

    if plan.get("done_looks_like"):
        st.success(f"**Done looks like:** {plan['done_looks_like']}")

    watch_for = plan.get("watch_for") or []
    if watch_for:
        with st.expander(f"Where this goes wrong ({len(watch_for)})"):
            for item in watch_for:
                st.markdown(f"- {item}")

    follow_ups = plan.get("follow_ups") or []
    if follow_ups:
        with st.expander("Making it stick"):
            for item in follow_ups:
                st.markdown(f"- {item}")

    credits = plan.get("subject_credits") or []
    if credits:
        st.markdown("**Subject credit (feeds the WA compliance dashboard)**")
        for credit in credits:
            st.markdown(
                f"- **{subjects.label(credit['subject'])}** — {credit['minutes']} min · "
                f"{credit.get('justification', '')}"
            )


def log_lesson_form(
    db: Database,
    student: dict[str, Any],
    generated: GeneratedLesson,
    source: str,
    primary_subject: str,
    location: str = "",
    key_prefix: str = "log",
    tier: str = config.TIER_CORE,
) -> None:
    """Let the parent confirm and log the hours this lesson actually took."""
    lesson = generated.payload
    st.markdown("### Log this as completed")
    st.caption(
        "Edit the minutes to what it actually took. Total minutes count toward the "
        "1,000-hour floor; the per-subject numbers are the multi-subject credit."
    )

    with st.form(f"{key_prefix}_form_{generated.lesson_id}"):
        columns = st.columns(3)
        with columns[0]:
            occurred_on = st.date_input("Date", value=date.today())
        with columns[1]:
            minutes = st.number_input(
                "Total minutes",
                min_value=5,
                max_value=600,
                value=int(lesson.get("estimated_minutes") or 60),
                step=5,
            )
        with columns[2]:
            where = st.text_input("Location", value=location)

        st.markdown("**Subject credit**")
        credits: dict[str, int] = {}
        for credit in lesson.get("subject_credits") or []:
            credits[credit["subject"]] = st.number_input(
                subjects.label(credit["subject"]),
                min_value=0,
                max_value=600,
                value=int(credit["minutes"]),
                step=5,
                key=f"{key_prefix}_credit_{generated.lesson_id}_{credit['subject']}",
            )

        submitted = st.form_submit_button("Log hours", type="primary")

    if submitted:
        db.log_activity(
            student_id=student["id"],
            title=lesson.get("title", "Lesson"),
            tier=tier,
            primary_subject=primary_subject,
            minutes=int(minutes),
            subject_credits={k: v for k, v in credits.items() if v > 0},
            occurred_on=occurred_on.isoformat(),
            description=lesson.get("overview", ""),
            source=source,
            location=where,
            lesson_id=generated.lesson_id,
        )
        st.success("Logged. The compliance dashboard is updated.")
        st.balloons()


def render_quiz(
    db: Database,
    student: dict[str, Any],
    lesson_id: int,
    metadata: dict[str, Any],
    quiz: list[dict[str, Any]],
) -> None:
    """The student's self-graded check on this lesson's content.

    The only thing standing between him and the answer key is that this
    function never writes a `correct_index` anywhere onto the page until after
    he submits. No CSS trick is needed for that part: Streamlit reruns this
    whole function on every interaction, so as long as the ungraded branch
    below never puts `correct_index` into a widget or a string, it never
    reaches the browser either — the answer simply isn't there to find, the
    same reasoning `render_lesson`'s redaction relies on.

    The `user-select: none` below is a separate, much weaker measure against
    copying the question text out to search for it — real friction, like the
    PIN, not a lock that can't be picked.
    """
    if not quiz:
        return

    state_key = f"quiz_result_{lesson_id}"
    result = st.session_state.get(state_key)

    st.divider()
    st.markdown("### 📝 Check your understanding")

    with st.container(key=f"quiz_nocopy_{lesson_id}"):
        st.markdown(
            f"<style>.st-key-quiz_nocopy_{lesson_id} "
            "{ -webkit-user-select: none; user-select: none; }</style>",
            unsafe_allow_html=True,
        )

        if result is None:
            picks: list[int | None] = []
            with st.form(f"quiz_form_{lesson_id}"):
                for index, item in enumerate(quiz):
                    st.markdown(f"**{index + 1}. {item['question']}**")
                    pick = st.radio(
                        "choices",
                        options=list(range(len(item["choices"]))),
                        format_func=lambda i, choices=item["choices"]: choices[i],
                        index=None,
                        label_visibility="collapsed",
                        key=f"quiz_pick_{lesson_id}_{index}",
                    )
                    picks.append(pick)
                submitted = st.form_submit_button("Submit quiz", type="primary")

            if not submitted:
                return
            if any(pick is None for pick in picks):
                st.warning("Answer every question before submitting.")
                return

            correct, total = grade(quiz, picks)
            threshold = db.get_int_setting("quiz_pass_percent")
            did_pass = quiz_passes(correct, total, threshold)
            st.session_state[state_key] = {"picks": picks, "correct": correct}
            db.record_quiz_result(lesson_id, correct, total, did_pass)

            skill_id = metadata.get("skill_id")
            if did_pass and skill_id:
                db.set_mastery(
                    student["id"],
                    skill_id,
                    "mastered",
                    score=100 * correct / total,
                    notes="Auto-graded from the in-app quiz.",
                )
            st.rerun()
            return

        picks = result["picks"]
        correct, total = result["correct"], len(quiz)
        threshold = db.get_int_setting("quiz_pass_percent")
        did_pass = quiz_passes(correct, total, threshold)
        pct = round(100 * correct / total)
        if did_pass:
            st.success(f"**{correct} / {total} correct ({pct}%)** — nice work.")
            if metadata.get("skill_id"):
                st.caption("Counted toward mastery of this skill.")
        else:
            st.warning(
                f"**{correct} / {total} correct ({pct}%)** — under the "
                f"{threshold}% needed to pass. Ask your parent about another go."
            )

        for index, item in enumerate(quiz):
            pick = picks[index]
            right = pick == item["correct_index"]
            marker = "✅" if right else "❌"
            with st.expander(f"{marker} {index + 1}. {item['question']}", expanded=not right):
                for choice_index, choice in enumerate(item["choices"]):
                    tag = ""
                    if choice_index == item["correct_index"]:
                        tag = " — correct answer"
                    elif choice_index == pick:
                        tag = " — your answer"
                    st.markdown(f"- {choice}{tag}")
                if item.get("explanation"):
                    st.caption(item["explanation"])

        if st.button("Try again", key=f"quiz_retry_{lesson_id}"):
            del st.session_state[state_key]
            st.rerun()


def student_lesson_view(
    db: Database, student: dict[str, Any], agent_key: str, subject_label: str
) -> None:
    """What the student sees on a subject page: his work, and nothing else.

    "Done" here is his own signal (`metadata.student_done_on`), not the
    parent's `status` -- logging hours is a separate act the parent still
    controls. Marking a lesson done just moves it from "current" to a
    "Past lessons" list he can still reopen; it never touches hours, credits,
    or the compliance record.
    """
    lessons = db.list_lessons(student["id"], agent=agent_key, limit=10)
    todo = [
        l for l in lessons
        if l["status"] != "skipped" and not (l.get("metadata") or {}).get("student_done_on")
    ]
    done = [l for l in lessons if (l.get("metadata") or {}).get("student_done_on")]
    current = todo[0] if todo else None

    if current is None:
        if done:
            st.success("Nothing left to do for now — nice work. Look back below if you want.")
        else:
            st.info(
                f"No {subject_label} lesson has been set up yet. Ask your parent to plan one."
            )
    else:
        if current["status"] == "completed":
            st.caption("This one's already marked done — here it is again.")
        render_lesson(current["payload"], for_parent=False)
        render_quiz(
            db,
            student,
            current["id"],
            current.get("metadata") or {},
            current["payload"].get("quiz") or [],
        )
        if st.button("✅ I'm done for today", key=f"student_done_{current['id']}", type="primary"):
            db.mark_student_done(current["id"])
            st.rerun()

    if done:
        st.divider()
        st.subheader("Past lessons")
        labels = [f"{l['created_at'][:10]} — {l['title']}" for l in done]
        choice = st.selectbox(
            "Look back at a finished lesson",
            labels,
            index=None,
            placeholder="Pick one to reopen",
            key=f"past_lesson_pick_{agent_key}",
        )
        if choice is not None:
            selected = done[labels.index(choice)]
            render_lesson(selected["payload"], for_parent=False)
            render_quiz(
                db,
                student,
                selected["id"],
                selected.get("metadata") or {},
                selected["payload"].get("quiz") or [],
            )


SUBJECT_ICONS = {"math": "📐", "science": "🔬", "english": "📖", "history": "🏛️"}


def render_today_checklist(db: Database, student: dict[str, Any]) -> bool:
    """His own "what I did today" list -- a fun accomplishment checklist, not
    a compliance record. Built entirely from his own signals (student_done_on,
    a quiz result graded today, a life skill either of you checked off today)
    so it never depends on the parent having logged anything yet -- that gap
    was the exact thing that made "current lesson" confusing before.

    Returns whether anything was actually shown, so a caller can fall back to
    something else when the day hasn't started yet.
    """
    today = date.today().isoformat()

    done_today = [
        lesson
        for lesson in db.list_lessons(student["id"], limit=25)
        if (lesson.get("metadata") or {}).get("student_done_on") == today
    ]
    skills_today = [
        skill
        for skill in db.list_life_skills(student["id"])
        if skill["completed_on"] == today
    ]

    if not done_today and not skills_today:
        return False

    st.subheader(f"✅ Today ({len(done_today) + len(skills_today)})")
    st.caption("Nice work — here's what you've knocked out today.")

    for lesson in done_today:
        icon = SUBJECT_ICONS.get(lesson["agent"], "📘")
        quiz_result = (lesson.get("metadata") or {}).get("quiz_result") or {}
        extra = ""
        if quiz_result.get("graded_on") == today and quiz_result.get("total"):
            pct = round(100 * quiz_result["correct"] / quiz_result["total"])
            trophy = " 🎯" if quiz_result.get("passed") else ""
            extra = f" — quiz {quiz_result['correct']}/{quiz_result['total']} ({pct}%){trophy}"
        st.markdown(f"- {icon} **{lesson['title']}**{extra}")

    for skill in skills_today:
        st.markdown(f"- 🛠️ **{skill['title']}**")

    return True


def api_status_banner() -> bool:
    from compass.agents import api_available

    ok, message = api_available()
    if not ok:
        st.error(
            f"**Lesson generation is unavailable.** {message}\n\n"
            "Everything else in Compass — the compliance dashboard, the activity log, "
            "choice topics, and life skills — works without it."
        )
    return ok


# --- school-year and Declaration of Intent countdowns -------------------------


def render_school_start_countdown(db: Database) -> None:
    """Shown to both parent and student -- there's nothing here to redact."""
    next_start = next_annual_date(db.get_setting("school_year_start") or "09-01")
    remaining = (next_start - date.today()).days
    when = f"{next_start.strftime('%B')} {next_start.day}"
    if remaining <= 0:
        st.caption(f"🎉 Today's the first day of school ({when}).")
    else:
        plural = "s" if remaining != 1 else ""
        st.caption(f"🗓️ {remaining} day{plural} until the first day of school ({when}).")


def render_declaration_banner(db: Database, student: dict[str, Any]) -> None:
    """Parent-only: filing paperwork with the district, not a lesson matter.

    Washington's Declaration of Intent (RCW 28A.200.010) has nothing to do
    with hours or subject coverage, which is why it's tracked here rather than
    folded into the compliance report -- a family perfectly on pace for 1,000
    hours can still be about to miss this deadline.
    """
    ds = declaration_status(db, student["id"])
    when = f"{ds.due_on.strftime('%B')} {ds.due_on.day}, {ds.due_on.year}"

    if ds.filed:
        st.success(f"✅ Declaration of Intent filed on {ds.filed_on} for the {when} deadline.")
        return

    if ds.overdue:
        st.error(
            f"📌 **Declaration of Intent was due {when}** — file with your school "
            "district as soon as possible (WA RCW 28A.200.010)."
        )
    else:
        message = (
            f"📌 **Declaration of Intent due in {ds.days_remaining} days** — file with "
            f"your school district by {when} (WA RCW 28A.200.010)."
        )
        (st.warning if ds.days_remaining <= 14 else st.info)(message)

    columns = st.columns([3, 1])
    with columns[0]:
        if ds.url:
            st.caption(f"[Your district's filing page]({ds.url})")
        else:
            st.caption("Add your district's filing link in Compliance → Year settings.")
    with columns[1]:
        if st.button("Mark as filed", key="mark_declaration_filed"):
            db.mark_declaration_filed(student["id"], ds.due_on.isoformat())
            st.rerun()
