"""Grading and review -- the digital assessment card (Activity Log's review
flow): quiz review, per-activity grade pickers, writing-review controls, the
final-grade decision, and logging hours against a graded lesson.

Split out of compass.ui. Only st/date/is_parent go through `_ui`.
"""
from __future__ import annotations

import html
from typing import Any

import compass.ui as _ui
from compass import config, subjects
from compass.agents import LessonGenerationError, checklist_suggest
from compass.storage.db import Database
from compass.ui import (
    _activity_grades_recorded,
    _comic_phase_pill_html,
    _feedback_history,
    _gradeable_activities,
    _has_answer_key,
    _needs_written_response,
    _render_activity_body,
    _render_learn_section,
    _stored_ai_review,
    md,
)


def _hours_inputs(payload: dict[str, Any], key_prefix: str) -> tuple[int, str, dict[str, int]]:
    """The minutes/location/subject-credit inputs shared by every place that
    finishes a lesson -- the same fields `log_lesson_form` collects for a
    Life Skills lesson, reused here so approving a graded-subject lesson
    can log its hours in the same click rather than a second form.

    Must be called inside an open `st.form`.
    """
    columns = _ui.st.columns(2)
    with columns[0]:
        minutes = _ui.st.number_input(
            "Total minutes",
            min_value=5,
            max_value=600,
            value=int(payload.get("estimated_minutes") or 60),
            step=5,
            key=f"{key_prefix}_minutes",
        )
    with columns[1]:
        where = _ui.st.text_input("Location", key=f"{key_prefix}_location")
    credits: dict[str, int] = {}
    subject_credits = payload.get("subject_credits") or []
    if subject_credits:
        _ui.st.caption("Subject credit")
        credit_columns = _ui.st.columns(len(subject_credits))
        for column, credit in zip(credit_columns, subject_credits):
            with column:
                credits[credit["subject"]] = _ui.st.number_input(
                    subjects.label(credit["subject"]),
                    min_value=0,
                    max_value=600,
                    value=int(credit["minutes"]),
                    step=5,
                    key=f"{key_prefix}_credit_{credit['subject']}",
                )
    return int(minutes), where, credits


def _log_hours_for_lesson(
    db: Database,
    student: dict[str, Any],
    lesson: dict[str, Any],
    *,
    minutes: int,
    location: str,
    credits: dict[str, int],
) -> None:
    """The actual db.log_activity call behind every "Approve & log hours"
    button below -- log_activity already sets status='completed' when
    given a lesson_id, so approving and archiving are the same act."""
    payload = lesson["payload"]
    db.log_activity(
        student_id=student["id"],
        title=lesson.get("title", "Lesson"),
        tier=config.TIER_CORE,
        primary_subject=lesson["subject"],
        minutes=minutes,
        subject_credits={k: v for k, v in credits.items() if v > 0},
        occurred_on=_ui.date.today().isoformat(),
        description=payload.get("overview", ""),
        source=lesson["agent"],
        location=location,
        lesson_id=lesson["id"],
    )


def _render_quiz_review(db: Database, student: dict[str, Any], lesson: dict[str, Any]) -> bool:
    """The quiz he took, laid out for the parent the same way his own
    graded view showed it -- each question, which answer he picked, which
    was right, and the explanation. The review card used to surface the
    quiz as a single score line and nothing more, so a parent could see
    *that* he scored 4/5 but never *which* one he missed or what he chose;
    the writing sitting right beside it was fully readable, and the quiz
    should be too.

    Reads the latest graded attempt (list_quiz_attempts is newest-first)
    and its stored per-question `detail`. Returns True when it rendered
    something, so the caller can count "there's a quiz to look at" among
    the reasons this card has anything to show. Renders nothing -- and
    returns False -- for a lesson with no quiz, or a quiz he hasn't taken
    yet.
    """
    attempts = db.list_quiz_attempts(student["id"], lesson_id=lesson["id"])
    if not attempts:
        return False
    latest = attempts[0]
    detail = latest.get("detail") or []
    if not detail:
        return False

    correct, total = latest["correct"], latest["total"]
    pct = round(100 * correct / total) if total else 0
    verdict = "🎯 passed" if latest.get("passed") else "below the pass threshold"
    suffix = f" · latest of {len(attempts)} attempts" if len(attempts) > 1 else ""
    _ui.st.markdown(f"**📝 Quiz — {correct}/{total} ({pct}%)** — {verdict}{suffix}")

    for index, item in enumerate(detail):
        pick = item.get("pick")
        right = pick == item.get("correct_index")
        marker = "✅" if right else "❌"
        # The ones he missed open on their own -- those are what a parent is
        # scanning for; the ones he got right stay a click away rather than
        # padding out the card.
        with _ui.st.expander(f"{marker} {index + 1}. {md(item['question'])}", expanded=not right):
            for choice_index, choice in enumerate(item.get("choices") or []):
                tag = ""
                if choice_index == item.get("correct_index"):
                    tag = " — correct answer"
                elif choice_index == pick:
                    tag = " — his answer"
                _ui.st.markdown(f"- {md(choice)}{tag}")
            if pick is None:
                _ui.st.caption("He left this one blank.")
            if item.get("explanation"):
                _ui.st.caption(md(item["explanation"]))
    return True


def _render_writing_review_controls(
    db: Database,
    student: dict[str, Any],
    lesson: dict[str, Any],
    index: int,
    activity: dict[str, Any],
    *,
    key_prefix: str,
    metadata: dict[str, Any],
    review_map: dict[str, Any],
) -> None:
    """One writing activity's evidence and its approve/send-back call, meant
    to sit directly under that activity in the parent's inline review: his
    response, earlier drafts, the automated read, and -- once he's turned the
    whole lesson in -- the buttons to approve it or bounce it back to him."""
    responses = metadata.get("writing_responses") or {}
    text = responses.get(str(index), "")
    review = review_map.get(str(index), {})
    status = review.get("status", config.WRITING_DRAFT)

    # His actual submission, made to stand out from the assignment text
    # above it -- a bold label and its own boxed panel, not a subtle italic
    # line that reads as more instructions. This is the thing a parent
    # opened the card to see.
    _ui.st.markdown("**✍️ What he turned in:**")
    if text:
        with _ui.st.container(border=True):
            _ui.st.write(md(text))
    else:
        _ui.st.caption("He hasn't written a response yet.")

    # The parts he was asked to cover, and which he checked off -- so you can
    # confirm a ticked box was actually done, not just clicked past. He can't
    # turn a writing activity in until every box is ticked, so all showing ✅
    # is his self-report, the ❌ (if any, on an already-submitted lesson from
    # before this existed) a genuine gap.
    checklist_items = activity.get("checklist") or []
    if checklist_items:
        stored_checks = (metadata.get("checklist_checked") or {}).get(str(index)) or []
        _ui.st.caption("Parts he had to cover:")
        for item_index, item in enumerate(checklist_items):
            ticked = item_index < len(stored_checks) and stored_checks[item_index]
            _ui.st.markdown(f"{'✅' if ticked else '⬜'} {md(item)}")

    versions = db.list_writing_response_versions(lesson["id"], index)
    if len(versions) > 1:
        with _ui.st.expander(f"Earlier drafts ({len(versions) - 1})"):
            for version in versions[:-1]:
                _ui.st.caption(version["saved_at"])
                _ui.st.write(md(version["text"]))
                _ui.st.divider()

    ai_review = _stored_ai_review(metadata, index)
    if ai_review is not None:
        # The same stored result he already saw before submitting -- his
        # view showed strengths and next moves; yours adds what the
        # assignment asked for that's still missing, and anything
        # factually wrong. No second model call: this is read back, not
        # regenerated.
        with _ui.st.expander("🔍 What the automated read noticed"):
            # Three tiers, loudest first. This card is read to decide
            # whether to send the assignment back, so the two reasons to
            # do that shouldn't sit quieter than the praise -- which is
            # what a plain bullet under a ⚠️ alert was doing. `missing`
            # carries the same 🔁 his own view uses for the same items,
            # so the mark means one thing on both sides of the app.
            for concern in ai_review.get("concerns") or []:
                _ui.st.error(f"⚠️ **Check this** — {md(concern)}")
            for item in ai_review.get("missing") or []:
                _ui.st.warning(f"🔁 **Needs rework** — {md(item)}")
            for strength in ai_review.get("strengths") or []:
                _ui.st.markdown(f"- ✅ **Working:** {md(strength)}")
            if not any(ai_review.get(k) for k in ("concerns", "missing", "strengths")):
                _ui.st.caption("Nothing flagged.")
            _ui.st.caption(
                "Advisory only, and it can be wrong -- it never approves "
                "anything on its own."
            )

    # While you're still reviewing (the lesson's turned in but not yet
    # approved or sent back), a per-piece verdict is a *marker*, not a
    # commit -- approving or flagging one piece leaves every other piece's
    # controls right where they are, and nothing reaches him until the one
    # lesson-wide decision at the bottom. This is the fix for the trap where
    # bouncing the first of three written answers hid the forms for the other
    # two ("all 3 have their own Send back... feel like this should almost be
    # something designated on the whole lesson").
    lesson_under_review = lesson["status"] == "submitted"

    def _reopen_button(label: str) -> None:
        if lesson_under_review and _ui.st.button(
            label, key=f"{key_prefix}_reopen_writing_{lesson['id']}_{index}"
        ):
            db.set_writing_review(lesson["id"], index, config.WRITING_SUBMITTED)
            _ui.st.rerun()

    if status == config.WRITING_APPROVED:
        approval_note = review.get("approval_feedback")
        if approval_note:
            _ui.st.success(f"✅ Approved with a note for him: {md(approval_note)}")
            if review.get("approval_read_at"):
                _ui.st.caption(f"👀 He read it — {review['approval_read_at']}")
                if review.get("approval_reply"):
                    _ui.st.caption(f"💬 He said: {md(review['approval_reply'])}")
            else:
                _ui.st.caption("⏳ Waiting on him to read it and reply that he saw it.")
        else:
            _ui.st.success("✅ Approved.")
        _reopen_button("↩️ Undo — decide on this one again")
    elif status == config.WRITING_NEEDS_REVISION:
        history = _feedback_history(
            review, history_key="feedback_history", single_key="feedback"
        )
        # "Flagged" until the lesson-wide send-back actually commits; only then
        # is it truly "sent back." Keeping the wording honest matters: a parent
        # mid-review shouldn't think he's already seen this.
        lead = (
            "🔁 Flagged for rework — goes back to him when you send the lesson back"
            if lesson_under_review
            else "↩️ Sent back for revision"
        )
        if len(history) <= 1:
            _ui.st.warning(lead + (f": {md(history[0])}" if history else "."))
        else:
            _ui.st.warning(lead + " — every note you've given so far:")
            for note in history:
                _ui.st.markdown(f"- {md(note)}")
        _reopen_button("↩️ Undo — decide on this one again")
    elif status == config.WRITING_SUBMITTED and lesson_under_review:
        # If this is a *re*-review -- you sent it back once, he reworked it and
        # turned it in again -- the notes you gave last time are the whole
        # point of comparison, so surface them right above the buttons rather
        # than making you remember what you'd asked for. Empty on a first pass.
        prior_notes = _feedback_history(
            review, history_key="feedback_history", single_key="feedback"
        )
        if prior_notes:
            _ui.st.warning(
                "↩️ You sent this back "
                + (
                    "before — what you asked for:"
                    if len(prior_notes) == 1
                    else "before — every note so far:"
                )
            )
            for note in prior_notes:
                _ui.st.markdown(f"- {md(note)}")
            _ui.st.caption("His reworked response is what's shown above.")
            if review.get("revision_reply"):
                # What he said he'd change when he turned it back in -- so you
                # can check the rework against his own stated plan, not just the
                # note you gave.
                _ui.st.info(f"💬 He said he'd change: {md(review['revision_reply'])}")
        _ui.st.info("⏳ He's submitted this — awaiting your review.")
        review_key = f"{key_prefix}_writing_review_{lesson['id']}_{index}"
        with _ui.st.form(review_key):
            feedback = _ui.st.text_area(
                "Feedback for him",
                key=f"{review_key}_feedback",
                help=(
                    "Flag for rework → he has to revise this before the lesson "
                    "counts. Approve → this piece counts, but he still has to read "
                    "your note and reply that he saw it. Nothing reaches him until "
                    "you send the whole lesson back (or approve it) below."
                ),
            )
            approve_col, bounce_col = _ui.st.columns(2)
            approve = approve_col.form_submit_button("✅ Approve", type="primary")
            bounce = bounce_col.form_submit_button("🔁 Flag for rework")
        if approve:
            db.set_writing_review(
                lesson["id"], index, config.WRITING_APPROVED, approval_note=feedback
            )
            _ui.st.rerun()
        elif bounce:
            # Record the verdict on this one piece and nothing more -- the whole
            # lesson only goes back when you commit the single send-back at the
            # bottom, so flagging one answer never hides the others' controls.
            db.set_writing_review(lesson["id"], index, config.WRITING_NEEDS_REVISION, feedback)
            _ui.st.rerun()
    elif status == config.WRITING_SUBMITTED:
        # Submitted at the activity level but the lesson as a whole
        # hasn't been turned in yet -- possible on data from before this
        # gate existed. Nothing to act on until he turns in the rest.
        _ui.st.caption("⏳ Submitted — waiting on him to turn in the whole lesson.")
    else:
        _ui.st.caption("Still drafting — he hasn't submitted this one yet.")

    # Add or edit the self-check parts on a lesson he hasn't turned in yet --
    # the way to bring the checklist gate to lessons generated before it
    # existed, without regenerating the day. "Suggest" reads the parts out of
    # the assignment's own instructions; you confirm or edit before saving,
    # so nothing goes live on his screen that you didn't approve.
    if lesson["status"] in ("planned", "needs_revision"):
        existing_items = activity.get("checklist") or []
        summary = f" ({len(existing_items)})" if existing_items else " — none yet"
        with _ui.st.expander(f"🧩 Self-check parts he must tick{summary}"):
            edit_key = f"{key_prefix}_checklist_edit_{index}"
            if edit_key not in _ui.st.session_state:
                _ui.st.session_state[edit_key] = "\n".join(existing_items)
            _ui.st.text_area(
                "One part per line — he'll have to tick each before he can turn this in.",
                key=edit_key,
                height=110,
            )
            save_col, suggest_col = _ui.st.columns(2)
            if save_col.button("Save parts", key=f"{key_prefix}_checklist_save_{index}"):
                items = [
                    line.strip()
                    for line in _ui.st.session_state[edit_key].splitlines()
                    if line.strip()
                ]
                db.set_activity_checklist_items(lesson["id"], index, items)
                _ui.st.success("Saved.")
                _ui.st.rerun()
            if suggest_col.button(
                "✨ Suggest from the instructions",
                key=f"{key_prefix}_checklist_suggest_{index}",
            ):
                with _ui.st.spinner("Reading the assignment…"):
                    try:
                        suggested = checklist_suggest.suggest_checklist(
                            activity.get("instructions", "")
                        )
                    except LessonGenerationError as exc:
                        _ui.st.error(f"Couldn't suggest right now: {exc}")
                        suggested = None
                if suggested:
                    _ui.st.session_state[edit_key] = "\n".join(suggested)
                    _ui.st.rerun()
                elif suggested is not None:
                    _ui.st.caption(
                        "This assignment reads as a single ask — no separate parts to "
                        "check off. Add your own above if you want to."
                    )


def _render_activity_grade_picker(
    db: Database,
    lesson: dict[str, Any],
    index: int,
    activity: dict[str, Any],
    *,
    metadata: dict[str, Any],
    key_prefix: str,
) -> None:
    """Grade one activity against its own answer key, inline under his work.

    The new fixed lesson shape: a lesson's grade is its two activity verdicts
    plus the quiz (plus math mastery), each activity scored on its own rather
    than one band for the whole lesson. The answer key (which the student never
    sees) sits right above the picker so the parent grades against it without
    scrolling, and each verdict is saved independently."""
    answer = (activity.get("answer") or "").strip()
    if answer:
        _ui.st.markdown(
            f'<div style="background:var(--c-panel); border-left:3px solid '
            f'var(--c-good); border-radius:var(--c-radius); padding:10px 14px; '
            f'margin:8px 0;"><b>✅ Answer key</b><br>'
            f'{html.escape(answer).replace(chr(10), "<br>")}'
            f"</div>",
            unsafe_allow_html=True,
        )
    result = (metadata.get("activity_results") or {}).get(str(index)) or {}
    current = result.get("verdict")
    # No pre-selected default -- index=0 would sit on "Nailed it," so a parent
    # who saved without reading would hand out a 100%.
    verdict = _ui.st.radio(
        "How did he do on this one?",
        config.ASSESSMENT_VERDICTS,
        index=config.ASSESSMENT_VERDICTS.index(current)
        if current in config.ASSESSMENT_VERDICTS
        else None,
        format_func=lambda v: config.ASSESSMENT_VERDICT_LABELS[v],
        key=f"{key_prefix}_actgrade_{lesson['id']}_{index}",
    )
    _ui.st.caption(
        "This activity's band is part of his grade for the subject — the "
        "percentage on each one is what it's worth."
    )
    if _ui.st.button(
        "💾 Save this grade",
        key=f"{key_prefix}_actgrade_save_{lesson['id']}_{index}",
    ):
        if verdict is None:
            _ui.st.warning("Pick a band first.")
        else:
            db.record_activity_grade(lesson["id"], index, verdict)
            _ui.st.success("Saved.")
            _ui.st.rerun()
    if result:
        _ui.st.caption(
            f"Last recorded: {config.ASSESSMENT_VERDICT_LABELS.get(result.get('verdict'), '')} "
            f"on {result.get('assessed_on', '')}"
        )


def _render_final_grade_decision(
    db: Database,
    student: dict[str, Any],
    lesson: dict[str, Any],
    *,
    key_prefix: str,
    metadata: dict[str, Any],
    assessment: dict[str, Any],
    skill_id: Any,
    writing_all_approved: bool,
    writing_flagged: list[tuple[int, str]] | None = None,
    writing_undecided: bool = False,
) -> None:
    """The one lesson-wide call, at the very bottom of the review: mastery
    for a Math skill (a `skill_id`), the five-band verdict for every other
    graded subject. Only opens up once he's turned the lesson in AND every
    writing piece in it is individually approved -- never two "send it back"
    buttons live for the same lesson at once. Approving folds in logging the
    hours in the same click; sending back reopens it to him.

    If instead you've flagged one or more written pieces for rework, this is
    also where that single send-back is committed -- one button that carries
    every per-piece note back to him at once, pre-empting any grading (you
    don't grade a lesson you're bouncing)."""
    # The flagged-writing send-back short-circuits everything below: you've
    # decided at least one piece needs another look, so the whole lesson goes
    # back rather than getting a grade. Held until no piece is still undecided,
    # so you can't bounce a lesson you haven't finished reviewing.
    writing_flagged = writing_flagged or []
    if (
        lesson["status"] == "submitted"
        and writing_flagged
        and not writing_undecided
    ):
        count = len(writing_flagged)
        which = ", ".join(f"No. {number} ({title})" for number, title in writing_flagged)
        _ui.st.warning(
            f"🔁 You've flagged {count} written "
            f"{'piece' if count == 1 else 'pieces'} for rework: {which}. "
            "Sending the lesson back gives him your note on each one."
        )
        with _ui.st.form(f"{key_prefix}_sendback_{lesson['id']}"):
            note = _ui.st.text_area(
                "Add a note for the whole lesson? (optional — each flagged "
                "piece already carries the note you gave it)"
            )
            send = _ui.st.form_submit_button(
                "↩️ Send back for revision", type="primary"
            )
        if send:
            db.send_lesson_back(lesson["id"], note)
            _ui.st.success("Sent back — he'll see your note on each flagged piece.")
            _ui.st.rerun()
        return

    if skill_id:
        current = db.mastery_map(student["id"]).get(skill_id, {})
        quiz_result = metadata.get("quiz_result") or {}
        latest_score = (
            round(100 * quiz_result["correct"] / quiz_result["total"])
            if quiz_result.get("total")
            else current.get("score")
        )
        mastery_bar = db.get_int_setting("math_mastery_percent")
        # "Mastered" now has to be earned by the quiz, not just approved: the
        # skill only records as mastered when his latest quiz clears the mastery
        # bar, or when you deliberately override. This is what stops a stale
        # "mastered at 80%" from being minted by an Approve click on a lesson he
        # didn't actually ace -- reported directly.
        earned_mastery = latest_score is not None and latest_score >= mastery_bar
        if current.get("status") == "mastered":
            _ui.st.success(f"✅ Already approved — mastered at {current.get('score') or '?'}%.")
        elif current.get("status") == "in_progress" and str(
            current.get("notes", "")
        ).startswith("Dropped from mastered"):
            # A skill that was mastered but a later quiz knocked back down, so
            # the parent isn't misled by a stale "mastered" while he's clearly
            # struggling now. The note carries the score that dropped it.
            _ui.st.warning(f"⚠️ {md(current['notes'])} It's back to *in progress* — worth another look.")
        _ui.st.caption(
            f"Mastery needs a quiz at {mastery_bar}%+ — his latest was "
            f"{latest_score if latest_score is not None else '—'}%. Approving logs the "
            "hours and accepts his work; it records the skill as **mastered** only when "
            "the quiz clears that bar (or you tick the override below). A weak quiz on a "
            "skill he'd mastered drops it back on its own."
        )
        if lesson["status"] == "submitted" and writing_all_approved:
            with _ui.st.form(f"{key_prefix}_assess_{lesson['id']}"):
                notes = _ui.st.text_area("Notes (optional)", value=current.get("notes", ""))
                feedback = _ui.st.text_area(
                    "Feedback (shown to him if you send it back for more practice)"
                )
                override_master = False
                if not earned_mastery:
                    override_master = _ui.st.checkbox(
                        f"Mark this skill mastered anyway (his latest quiz was "
                        f"{latest_score if latest_score is not None else '—'}%, under the "
                        f"{mastery_bar}% bar)",
                        key=f"{key_prefix}_master_override_{lesson['id']}",
                    )
                minutes, where, credits = _hours_inputs(
                    lesson["payload"], f"{key_prefix}_hrs_{lesson['id']}"
                )
                approve_col, practice_col = _ui.st.columns(2)
                approve = approve_col.form_submit_button("✅ Approve & log hours", type="primary")
                keep_practicing = practice_col.form_submit_button(
                    "🔁 Not yet — send back for more practice"
                )
            if approve:
                mastered = earned_mastery or override_master
                db.set_mastery(
                    student["id"], skill_id,
                    "mastered" if mastered else "in_progress",
                    score=latest_score, notes=notes,
                )
                _log_hours_for_lesson(
                    db, student, lesson, minutes=minutes, location=where, credits=credits
                )
                _ui.st.success(
                    "Approved and logged — the next skill is unlocked."
                    if mastered
                    else "Approved and logged. The skill stays *in progress* until a "
                    "stronger quiz — the next skill won't unlock yet."
                )
                _ui.st.rerun()
            elif keep_practicing:
                db.set_mastery(
                    student["id"], skill_id, "in_progress", score=latest_score, notes=notes
                )
                db.send_lesson_back(lesson["id"], feedback)
                _ui.st.success("Sent back — he'll see this again to keep practicing.")
                _ui.st.rerun()
        elif lesson["status"] == "submitted":
            _ui.st.caption("Approve his response above before deciding on this skill.")
        elif lesson["status"] == "needs_revision":
            _ui.st.caption(
                "↩️ Sent back — waiting on him to keep practicing and turn it in again."
            )
        elif lesson["status"] == "planned":
            _ui.st.caption("Still working — nothing to review yet.")
    elif assessment:
        result = metadata.get("assessment_result") or {}
        current_verdict = result.get("verdict")
        if lesson["status"] == "submitted" and writing_all_approved:
            with _ui.st.form(f"{key_prefix}_assess_{lesson['id']}"):
                # Vertical, not horizontal: five bands with their percentages
                # spelled out don't fit on one row without truncating exactly
                # the part that says what you're assigning. And no
                # pre-selected default -- index=0 would sit on "Nailed it,"
                # so a parent who hit Save without reading would hand out a
                # 100%.
                verdict = _ui.st.radio(
                    "How'd it go?",
                    config.ASSESSMENT_VERDICTS,
                    index=config.ASSESSMENT_VERDICTS.index(current_verdict)
                    if current_verdict in config.ASSESSMENT_VERDICTS
                    else None,
                    format_func=lambda v: config.ASSESSMENT_VERDICT_LABELS[v],
                )
                _ui.st.caption(
                    "This band is part of his grade for the subject — the "
                    "percentage on each one is what it's worth."
                )
                notes = _ui.st.text_area("Notes (optional)", value=result.get("notes", ""))
                feedback = _ui.st.text_area("Feedback (shown to him if you send it back)")
                minutes, where, credits = _hours_inputs(
                    lesson["payload"], f"{key_prefix}_hrs_{lesson['id']}"
                )
                approve_col, bounce_col = _ui.st.columns(2)
                approve = approve_col.form_submit_button("✅ Approve & log hours", type="primary")
                bounce = bounce_col.form_submit_button("↩️ Send back for revision")
            if approve:
                if verdict is None:
                    _ui.st.warning("Pick a band first.")
                else:
                    db.record_assessment(lesson["id"], verdict, notes)
                    _log_hours_for_lesson(
                        db, student, lesson, minutes=minutes, location=where, credits=credits
                    )
                    _ui.st.success("Approved and logged.")
                    _ui.st.rerun()
            elif bounce:
                db.send_lesson_back(lesson["id"], feedback)
                _ui.st.success("Sent back for revision.")
                _ui.st.rerun()
        elif lesson["status"] == "submitted":
            _ui.st.caption("Approve his response above before grading the whole lesson.")
        elif lesson["status"] == "needs_revision":
            _ui.st.caption("↩️ Sent back — waiting on him to revise and turn it in again.")
        elif lesson["status"] == "planned":
            _ui.st.caption("Still working — nothing to review yet.")
        if result:
            _ui.st.caption(
                f"Last recorded: {config.ASSESSMENT_VERDICT_LABELS.get(result.get('verdict'), '')} "
                f"on {result.get('assessed_on', '')}"
            )
    else:
        # New fixed shape: no lesson-wide band. Each activity was graded on its
        # own above; the final call here just files the lesson and logs the
        # hours once every activity has a verdict (and every writing piece is
        # approved). His grade for the lesson is those activity verdicts plus
        # the quiz -- shown here so the parent knows what they're filing.
        gradeable = _gradeable_activities(lesson["payload"])
        if not gradeable:
            return
        recorded = _activity_grades_recorded(metadata, lesson["payload"])
        total = len(gradeable)
        if lesson["status"] == "submitted" and writing_all_approved:
            if recorded < total:
                _ui.st.info(
                    f"Grade each activity above first — {recorded} of {total} done. "
                    "Each activity's verdict is part of his grade for the subject."
                )
            with _ui.st.form(f"{key_prefix}_complete_{lesson['id']}"):
                _ui.st.caption(
                    "His grade for this lesson is the two activity verdicts above "
                    "plus the quiz. Approving logs the hours and files it."
                )
                feedback = _ui.st.text_area("Feedback (shown to him if you send it back)")
                minutes, where, credits = _hours_inputs(
                    lesson["payload"], f"{key_prefix}_hrs_{lesson['id']}"
                )
                approve_col, bounce_col = _ui.st.columns(2)
                approve = approve_col.form_submit_button(
                    "✅ Approve & log hours",
                    type="primary",
                    disabled=recorded < total,
                )
                bounce = bounce_col.form_submit_button("↩️ Send back for revision")
            if approve:
                _log_hours_for_lesson(
                    db, student, lesson, minutes=minutes, location=where, credits=credits
                )
                _ui.st.success("Approved and logged.")
                _ui.st.rerun()
            elif bounce:
                db.send_lesson_back(lesson["id"], feedback)
                _ui.st.success("Sent back for revision.")
                _ui.st.rerun()
        elif lesson["status"] == "submitted":
            _ui.st.caption("Approve his written responses above before filing the lesson.")
        elif lesson["status"] == "needs_revision":
            _ui.st.caption("↩️ Sent back — waiting on him to revise and turn it in again.")
        elif lesson["status"] == "planned":
            _ui.st.caption("Still working — nothing to review yet.")


def render_lesson_review(
    db: Database, student: dict[str, Any], lesson: dict[str, Any], key_prefix: str
) -> None:
    """Grade in place. The whole lesson as he saw it, and under each activity
    the very submission it produced -- his written response with its own
    approve/send-back buttons, the reading check -- and after the activities
    the quiz with his answers against the key. A parent reads top to bottom
    and never scrolls back up to a separate panel of controls to act on what
    they just read.

    Replaces the old split of a read-only lesson preview plus a detached
    assessment card. The lesson-wide decision (mastery, or the five-band
    verdict, folding in the hours) still lands exactly once, at the very end.

    The content is the parent view -- his responses shown, but the answer
    key and parent notes still held back exactly as they are on his own
    screen -- so it stays faithful to the lesson he actually worked from.
    """
    payload = lesson["payload"]
    metadata = lesson.get("metadata") or {}
    assessment = payload.get("assessment") or {}
    skill_id = metadata.get("skill_id")
    activities = payload.get("activities") or []
    review_map = metadata.get("writing_review") or {}
    reading_checks = metadata.get("reading_checks") or {}

    # If you've sent this lesson back before and he's turned it in again, the
    # notes you gave are the frame for this whole re-read -- put them at the
    # very top so you're grading against what you asked for, not from memory.
    lesson_notes = _feedback_history(
        metadata, history_key="lesson_feedback_history", single_key="lesson_feedback"
    )
    if lesson_notes:
        with _ui.st.container(border=True):
            if len(lesson_notes) == 1:
                _ui.st.markdown("↩️ **You sent this back — what you asked him for:**")
            else:
                _ui.st.markdown("↩️ **You've sent this back before — every note so far:**")
            for note in lesson_notes:
                _ui.st.markdown(f"- {md(note)}")

    if payload.get("overview"):
        _ui.st.write(md(payload["overview"]))
    objectives = payload.get("learning_objectives") or []
    materials = payload.get("materials") or []
    if objectives or materials:
        columns = _ui.st.columns(2)
        with columns[0]:
            if objectives:
                _ui.st.markdown("**Learning objectives**")
                for objective in objectives:
                    _ui.st.markdown(f"- {md(objective)}")
        with columns[1]:
            if materials:
                _ui.st.markdown("**Materials**")
                for item in materials:
                    _ui.st.markdown(f"- {md(item)}")

    # The teaching half he worked from -- shown here too so a parent grades with
    # the same Learn and worked example in front of them that he had.
    _render_learn_section(lesson, parent=True)

    for index, activity in enumerate(activities):
        with _ui.st.container(border=True):
            _ui.st.markdown(
                f"**{index + 1}. {md(activity.get('title', 'Activity'))}**  \n"
                f"{_comic_phase_pill_html(activity)} · "
                f"{activity.get('minutes', 0)} min",
                unsafe_allow_html=True,
            )
            # The activity exactly as he saw it (parent side: answer key and
            # parent notes still held back), then his own work and the
            # grading controls right underneath -- never up in a separate
            # block he has to scroll away to.
            _render_activity_body(
                activity,
                index,
                parent=True,
                db=db,
                lesson_id=lesson["id"],
                metadata=metadata,
                student=student,
                review_owns_response=True,
            )
            stored = reading_checks.get(str(index))
            if stored:
                correct, total = stored.get("correct", 0), stored.get("total", 0)
                label = f"📖 Reading check: {correct}/{total}"
                if total and correct == total:
                    _ui.st.caption(f"{label} ✅")
                else:
                    _ui.st.warning(f"{label} — worth asking whether he actually did the reading.")
            if _needs_written_response(activity):
                _render_writing_review_controls(
                    db, student, lesson, index, activity,
                    key_prefix=key_prefix, metadata=metadata, review_map=review_map,
                )
            # New fixed shape: grade this activity on its own, against its answer
            # key, right here under his work -- once he's turned the lesson in.
            if _has_answer_key(activity) and lesson["status"] in ("submitted", "completed"):
                _render_activity_grade_picker(
                    db, lesson, index, activity,
                    metadata=metadata, key_prefix=key_prefix,
                )

    if payload.get("quiz"):
        with _ui.st.container(border=True):
            if not _render_quiz_review(db, student, lesson):
                _ui.st.caption("📝 Quiz — he hasn't taken it yet.")

    # The parent's answer sheet / grading guide, sitting right below all his
    # work where the grading actually happens -- not a tiny caption up top he
    # has to scroll past. Reported: "wheres that answer sheet for me? that
    # should be right below his response for all activities." This is whatever
    # the lesson already carries in `assessment` (the paper he hands over, plus
    # what counts as mastered); the student never sees `assessment`, so this is
    # the one place these worked details surface.
    if (
        assessment.get("description")
        or assessment.get("answer_key")
        or assessment.get("mastery_criteria")
        or assessment.get("rubric")
    ):
        with _ui.st.container(border=True):
            _ui.st.markdown("**🔑 For grading — the hand-in & how to score it**")
            if assessment.get("kind"):
                _ui.st.caption(f"*{md(assessment['kind'])}*")
            if assessment.get("description"):
                _ui.st.markdown(md(assessment["description"]))
            # The leveled rubric -- what strong/getting-there/not-yet looks like.
            # Safe to have shown him too (it's his bar), so it reads next to the
            # verdict picker as the consistent words to grade against.
            if assessment.get("rubric"):
                _ui.st.markdown(
                    f'<div style="background:var(--c-panel); border-left:3px solid '
                    f'var(--c-warn); border-radius:var(--c-radius); padding:10px 14px; '
                    f'margin:8px 0;"><b>🎯 Grading rubric</b><br>'
                    f'{html.escape(assessment["rubric"]).replace(chr(10), "<br>")}'
                    f"</div>",
                    unsafe_allow_html=True,
                )
            # The worked answer key -- newly generated lessons carry it (older
            # ones won't, so it's shown only when present). Set apart in its own
            # tinted block so it reads as "the answers," not more prompt.
            if assessment.get("answer_key"):
                _ui.st.markdown(
                    f'<div style="background:var(--c-panel); border-left:3px solid '
                    f'var(--c-good); border-radius:var(--c-radius); padding:10px 14px; '
                    f'margin:8px 0;"><b>✅ Answer key</b><br>'
                    f'{html.escape(assessment["answer_key"]).replace(chr(10), "<br>")}'
                    f"</div>",
                    unsafe_allow_html=True,
                )
            if assessment.get("mastery_criteria"):
                _ui.st.markdown(
                    f"**Counts as mastered when:** {md(assessment['mastery_criteria'])}"
                )

    # The one lesson-wide decision reads the per-piece verdicts marked above.
    # Every writing piece approved -> the grade/approve flow opens. Any piece
    # flagged for rework -> a single "send the lesson back" that carries all the
    # per-piece notes at once. A piece still undecided -> neither, until you rule
    # on it. This is what keeps flagging one of three answers from firing off a
    # send-back (and hiding the other two) the moment you click it.
    writing_activities = [
        (index, activity)
        for index, activity in enumerate(activities)
        if _needs_written_response(activity)
    ]
    writing_statuses = {
        index: (review_map.get(str(index)) or {}).get("status", config.WRITING_DRAFT)
        for index, _ in writing_activities
    }
    writing_all_approved = all(
        status == config.WRITING_APPROVED for status in writing_statuses.values()
    )
    writing_flagged = [
        (index + 1, md(activities[index].get("title", "Activity")))
        for index, status in writing_statuses.items()
        if status == config.WRITING_NEEDS_REVISION
    ]
    # Anything not yet approved or flagged is still awaiting your call -- a piece
    # he's turned in (submitted) or, on old data, one still in draft.
    writing_undecided = any(
        status not in (config.WRITING_APPROVED, config.WRITING_NEEDS_REVISION)
        for status in writing_statuses.values()
    )
    _render_final_grade_decision(
        db,
        student,
        lesson,
        key_prefix=key_prefix,
        metadata=metadata,
        assessment=assessment,
        skill_id=skill_id,
        writing_all_approved=writing_all_approved,
        writing_flagged=writing_flagged,
        writing_undecided=writing_undecided,
    )

    # Your own links/resources for this lesson (a video you found, an article,
    # a note) -- added here, shown to him in the lesson.
    _ui.render_lesson_resources(db, lesson["id"], metadata, parent=True)


