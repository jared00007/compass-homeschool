"""The "Comic Panels" lesson layout -- render_lesson and the activity-card grid
every subject's lesson renders through.

Split out of compass.ui. Only st/date/is_parent (the names tests patch on the
package) go through `_ui`; everything else is a plain import.
"""
from __future__ import annotations

import html
from functools import partial
from typing import Any

import compass.ui as _ui
from compass import config, subjects
from compass.agents import LessonGenerationError, writing_review
from compass.export import (
    DocxExtractionError,
    extract_docx_text,
    lesson_to_pdf,
    suggested_pdf_filename,
)
from compass.storage.db import Database
from compass.ui import _maybe_auto_submit_lesson, _needs_written_response, md
from compass.writing_checks import check_writing, writing_hints


# Sampled three redesigns for the English page (stacked expanders felt "stale
# and full") and this is the one picked: activities become an ink-bordered
# panel grid instead of an accordion, each with an issue tag and a kind pill,
# always open rather than collapsed. Reuses theme.py's own CSS custom
# properties throughout (no new palette) -- opt-in via `comic_layout` on
# render_lesson so Math/Science/History keep the plain expander layout they
# already had.
_COMIC_PANEL_CSS = """
<style>
div[class*="st-key-comic_panel_"] {
  background: var(--c-panel);
  background-image: var(--c-panel-texture);
  background-repeat: no-repeat;
  border: 2px solid var(--c-text);
  border-radius: var(--c-radius);
  box-shadow: 4px 4px 0 rgba(36,28,18,.22);
  padding: .9rem 1.1rem .8rem;
  position: relative;
  margin-bottom: 1rem;
}
.comic-issue-tag {
  position: absolute;
  top: -12px;
  left: 14px;
  background: var(--c-primary);
  border: 2px solid var(--c-text);
  border-radius: 999px;
  font-family: var(--c-head);
  font-weight: 800;
  font-size: .68rem;
  padding: .15rem .55rem;
  color: var(--c-text);
  white-space: nowrap;
}
.comic-kind-icon { font-size: 1.2rem; margin-right: .35rem; }
.comic-pill {
  display: inline-flex; align-items: center; gap: .3rem;
  font-family: var(--c-head); font-weight: 700; font-size: .66rem;
  text-transform: uppercase; letter-spacing: .03em;
  padding: .2rem .55rem; border-radius: 999px;
}
.comic-pill--reading { background: var(--c-pill-reading-bg); color: var(--c-alt); }
.comic-pill--writing { background: var(--c-pill-writing-bg); color: var(--c-warn); }
.comic-pill--discussion { background: var(--c-pill-discussion-bg); color: var(--c-good); }
.comic-pill--instruction { background: var(--c-pill-instruction-bg); color: var(--c-pill-instruction-fg); }
.comic-pill--neutral { background: var(--c-panel); color: var(--c-dim); border: 1px solid var(--c-border); }
.comic-pill--rework { background: var(--c-pill-writing-bg); color: var(--c-warn); border: 1.5px solid var(--c-warn); margin-left: .4rem; }
.comic-pill--note { background: var(--c-pill-reading-bg); color: var(--c-alt); border: 1.5px solid var(--c-alt); margin-left: .4rem; }
.comic-progress-dots { display: flex; gap: .4rem; margin: .1rem 0 1.1rem; }
.comic-progress-dots span {
  width: 26px; height: 8px; border-radius: 999px; background: var(--c-border);
  opacity: .25; display: inline-block;
}
.comic-progress-dots span.done { background: var(--c-good); opacity: 1; }
.comic-progress-dots span.current { background: var(--c-primary); opacity: 1; }
div[class*="st-key-comic_frame_"] {
  background: var(--c-panel);
  border: 1px solid var(--c-border);
  border-radius: var(--c-radius);
  box-shadow: 5px 5px 0 rgba(36,28,18,.14);
  padding: 1.5rem 1.6rem 1.3rem;
  margin-bottom: 1.3rem;
}
.comic-frame-title {
  font-family: var(--c-head);
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: .02em;
  font-size: .78rem;
  color: var(--c-dim);
  margin-bottom: 1rem;
  display: flex;
  align-items: center;
  gap: .4rem;
}
</style>
"""

_COMIC_KIND_PILL_VARIANT = {
    "reading": "reading",
    "writing": "writing",
    "discussion": "discussion",
    "instruction": "instruction",
}
_COMIC_KIND_ICONS = {
    "reading": "📚",
    "writing": "✍️",
    "discussion": "💬",
    "instruction": "🧭",
    "practice": "🛠️",
    "field": "🧳",
    "project": "🧩",
    "assessment": "📝",
}

# Activities now carry a phase (learn/practice) instead of the old 8-value kind.
_PHASE_LABELS = {"learn": "Learn", "practice": "Practice"}
_PHASE_ICONS = {"learn": "📖", "practice": "🛠️"}
_PHASE_PILL_VARIANT = {"learn": "instruction", "practice": "writing"}


def activity_phase(activity: dict[str, Any]) -> str:
    """learn or practice. New lessons carry `phase` directly; a lesson written
    before the switch is read off its old `kind` -- only a bare "instruction"
    was teaching, everything else was work he did."""
    phase = activity.get("phase")
    if phase in _PHASE_LABELS:
        return phase
    return "learn" if activity.get("kind") == "instruction" else "practice"


def _comic_phase_pill_html(activity: dict[str, Any]) -> str:
    phase = activity_phase(activity)
    variant = _PHASE_PILL_VARIANT.get(phase, "neutral")
    icon = _PHASE_ICONS.get(phase, "📌")
    label = html.escape(_PHASE_LABELS.get(phase, "activity"))
    return (
        f'<span class="comic-kind-icon">{icon}</span>'
        f'<span class="comic-pill comic-pill--{variant}">{label}</span>'
    )


def _comic_review_flag_html(
    index: int, metadata: dict[str, Any] | None, *, parent: bool
) -> str:
    """A loud pill on an activity's own header, on his side, when the parent has
    flagged that specific piece -- ↩️ for a redo, 💬 for an approval note he
    hasn't opened yet. A math lesson can come back with several written answers
    and only one or two actually needing work; without this he had to open each
    card to find out which ("its hard for him to know which actual activity has
    feedback/rework required"). Returns "" when there's nothing to flag or on
    the parent's side, where the review controls themselves already show it."""
    if parent:
        return ""
    review = ((metadata or {}).get("writing_review") or {}).get(str(index)) or {}
    status = review.get("status")
    if status == config.WRITING_NEEDS_REVISION:
        return '<span class="comic-pill comic-pill--rework">↩️ Needs another look</span>'
    if (
        status == config.WRITING_APPROVED
        and review.get("approval_feedback")
        and not review.get("approval_read_at")
    ):
        return '<span class="comic-pill comic-pill--note">💬 A note to read</span>'
    return ""


def _writing_rework_summary(
    activities: list[dict[str, Any]], metadata: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """The specific activities the parent sent back for another look, each with
    the latest note on it -- so the red banner at the top of a sent-back lesson
    can name exactly which pieces need work rather than a blanket "check your
    work below." Reads the per-activity writing_review entries in order; newest
    note wins (feedback_history is oldest-first). Each item: number (1-based),
    title, note (may be "")."""
    reviews = (metadata or {}).get("writing_review") or {}
    flagged: list[dict[str, Any]] = []
    for index, activity in enumerate(activities):
        review = reviews.get(str(index)) or {}
        if review.get("status") != config.WRITING_NEEDS_REVISION:
            continue
        history = _feedback_history(
            review, history_key="feedback_history", single_key="feedback"
        )
        flagged.append(
            {
                "number": index + 1,
                "title": activity.get("title") or "Activity",
                "note": history[-1] if history else "",
            }
        )
    return flagged


def _comic_progress_dots_html(
    activities: list[dict[str, Any]], metadata: dict[str, Any] | None
) -> str:
    """One dot per activity, in order. There's no real per-activity "done"
    signal for a reading/instruction/discussion activity -- he doesn't check
    those off individually -- so this reads activities in sequence and
    treats everything up to the next *unmet* typed-response requirement as
    passed, the requirement itself as "current", and anything after as still
    ahead. A lesson with no typed-response activity at all falls back to the
    one real lesson-level signal instead of inventing per-activity state:
    every dot lit once he's marked the whole lesson done, none lit before
    that.
    """
    if not activities:
        return ""
    metadata = metadata or {}
    required = [i for i, a in enumerate(activities) if _needs_written_response(a)]
    if required:
        saved = metadata.get("writing_responses") or {}
        done = {i for i in required if (saved.get(str(i)) or "").strip()}
        next_up = next((i for i in required if i not in done), None)
        cutoff = next_up if next_up is not None else len(activities)
        classes = [
            "done" if i < cutoff else ("current" if i == cutoff else "")
            for i in range(len(activities))
        ]
    else:
        lit = bool(metadata.get("student_done_on"))
        classes = ["done" if lit else "" for _ in activities]
    dots = "".join(f'<span class="{c}"></span>' for c in classes)
    return '<div class="comic-progress-dots">' + dots + "</div>"


def _render_reading_check(
    activity: dict[str, Any],
    index: int,
    *,
    db: Database,
    lesson_id: int,
    metadata: dict[str, Any] | None,
) -> None:
    """"Did you actually read it?" -- two or three specifics from the text,
    graded on the spot.

    Every English lesson opens with "read chapters 9-10" and, before this,
    nothing ever checked that it happened -- which is plausibly upstream of
    a lot of thin writing, since you can't write 200 words about a chapter
    you skimmed. Deliberately ungated: it reports, it doesn't block. A
    question the model got wrong about an obscure book would otherwise
    strand him on reading he actually did.
    """
    questions = activity.get("reading_check") or []
    if not questions:
        return

    stored = ((metadata or {}).get("reading_checks") or {}).get(str(index))
    if stored:
        correct, total = stored.get("correct", 0), stored.get("total", 0)
        if total and correct == total:
            _ui.st.success(f"📖 Reading check: {correct}/{total} — you read it.")
        else:
            _ui.st.warning(
                f"📖 Reading check: {correct}/{total}. Worth going back over that "
                "part before you keep going."
            )
        return

    with _ui.st.form(f"reading_check_{lesson_id}_{index}"):
        _ui.st.markdown("**📖 Quick check — did you read it?**")
        picks: list[int | None] = []
        for question_index, item in enumerate(questions):
            _ui.st.markdown(f"{question_index + 1}. {md(item['question'])}")
            picks.append(
                _ui.st.radio(
                    "choices",
                    options=list(range(len(item["choices"]))),
                    format_func=lambda i, choices=item["choices"]: md(choices[i]),
                    index=None,
                    label_visibility="collapsed",
                    key=f"reading_pick_{lesson_id}_{index}_{question_index}",
                )
            )
        submitted = _ui.st.form_submit_button("Check")

    if submitted:
        if any(pick is None for pick in picks):
            _ui.st.warning("Answer all of them first.")
            return
        correct = sum(
            1 for item, pick in zip(questions, picks) if pick == item["correct_index"]
        )
        db.save_reading_check(lesson_id, index, correct, len(questions))
        _ui.st.rerun()


def _feedback_history(source: dict[str, Any], *, history_key: str, single_key: str) -> list[str]:
    """Every note given so far on one piece of feedback, oldest first --
    falls back to a single legacy field for data saved before `history_key`
    existed. Shared by every place that reads a feedback trail (per-activity
    writing review, student and parent side, and the whole-lesson banner)
    so a future change to the fallback rule can't be applied to two of the
    three copies and forgotten on the third -- exactly what happened once
    already, when a second bounce silently overwrote the first note."""
    return source.get(history_key) or (
        [source[single_key]] if source.get(single_key) else []
    )


def _stored_ai_review(metadata: dict[str, Any] | None, index: int) -> dict[str, Any] | None:
    """The automated read of this activity's response, if one has been run.

    Read straight off the metadata already in hand rather than through
    `writing_review.existing_review`, which takes a whole lesson row --
    the render path only ever has the metadata dict.
    """
    return ((metadata or {}).get("writing_ai_review") or {}).get(str(index))


def _render_ai_review_for_student(review: dict[str, Any]) -> None:
    """His side of the stored review: what's working, then at most two next
    moves. The parent's own view of the same result (in
    `render_assessment_card`) carries the fuller diagnostic -- the missing
    requirements and any factual corrections -- deliberately not repeated
    here, where a wall of everything wrong is the thing most likely to make
    him give up rather than revise."""
    _ui.st.divider()
    _ui.st.markdown("**🔍 A read on what you wrote**")
    for strength in review.get("strengths") or []:
        _ui.st.success(f"👍 {md(strength)}")
    # Amber and marked "go fix", not a neutral blue note -- these are the
    # whole reason the read exists, and a plain arrow in an info box reads
    # as "here's a thought" rather than "this needs another pass." 🔁 is the
    # same "needs more work" mark the assessment verdicts already use
    # (config.ASSESSMENT_VERDICT_LABELS), so it means one thing app-wide.
    for move in review.get("next_moves") or []:
        _ui.st.warning(f"🔁 **Go fix this:** {md(move)}")
    if not (review.get("next_moves") or review.get("strengths")):
        _ui.st.caption("Nothing flagged — give it another read yourself, then submit.")
    _ui.st.caption("This is a suggestion, not a grade. Your parent still reads it too.")


def _render_activity_body(
    activity: dict[str, Any],
    index: int,
    *,
    parent: bool,
    db: Database | None,
    lesson_id: int | None,
    metadata: dict[str, Any] | None,
    student: dict[str, Any] | None = None,
    review_owns_response: bool = False,
) -> None:
    """The inside of one activity: video, worked example, instructions, and
    (when it applies) the typed-response box. Shared by both the plain
    expander layout and the comic-panel layout so the two never drift apart.

    `review_owns_response` is set only by the parent's inline grading view
    (render_lesson_review): there, his written response and the approve/send
    -back controls are rendered together right below the activity by
    `_render_writing_review_controls`, so this function renders the activity
    *content* and stops short of showing the response a second time."""
    video = activity.get("video") or {}
    if video.get("found") and video.get("url"):
        _ui.st.markdown(f"▶️ **[{md(video.get('title', 'Watch'))}]({video['url']})**")
        caption_parts = []
        if video.get("channel"):
            caption_parts.append(video["channel"])
        if video.get("why"):
            caption_parts.append(video["why"])
        if caption_parts:
            _ui.st.caption(" — ".join(caption_parts))
        if parent:
            _ui.st.caption(
                "Checked against a real search result and restricted to "
                "YouTube, but Compass doesn't control what YouTube "
                "recommends once the video ends."
            )

    example = activity.get("example")
    if example:
        _ui.st.markdown(
            f'<div style="background:var(--c-panel); border-left:3px solid '
            f'var(--c-alt); border-radius:var(--c-radius); padding:10px 14px; '
            f'margin-bottom:10px; font-size:13.5px;">'
            f'<b>📖 Here\'s how:</b><br>{html.escape(example).replace(chr(10), "<br>")}'
            f"</div>",
            unsafe_allow_html=True,
        )
    _ui.st.write(md(activity.get("instructions", "")))

    if not parent and db is not None and lesson_id is not None:
        _render_reading_check(
            activity, index, db=db, lesson_id=lesson_id, metadata=metadata
        )

    # Practice feedback: for an objective activity, the worked answers to its own
    # problems, tucked behind a toggle so he tries first and then sees where he
    # went wrong. This is the "practice is reviewed" half of Learn -> Practice ->
    # Prove for anything the parent doesn't hand-grade.
    self_check = activity.get("self_check")
    if self_check:
        with _ui.st.expander("✅ Check your work", expanded=False):
            _ui.st.caption("Give it a real try first — then open this to see how you did.")
            _ui.st.markdown(md(self_check))

    if _needs_written_response(activity) and not review_owns_response:
        saved = ((metadata or {}).get("writing_responses") or {}).get(str(index), "")
        if not parent and db is not None and lesson_id is not None:
            review = ((metadata or {}).get("writing_review") or {}).get(str(index), {})
            status = review.get("status", config.WRITING_DRAFT)

            if status == config.WRITING_APPROVED:
                _ui.st.success("✅ Your parent approved this one.")
                approval_note = review.get("approval_feedback")
                if approval_note and not review.get("approval_read_at"):
                    # Approved, so it counts -- but they left you something to
                    # read. Same deal as travel-journal feedback: clearing it
                    # takes a real reply in your own words, not a one-tap, so a
                    # note isn't scrolled past just because the piece passed.
                    _ui.render_writing_feedback_reply_form(
                        db, lesson_id, index, approval_note, key_prefix="lesson"
                    )
                elif approval_note:
                    _ui.st.caption(f"💬 Note from your parent: {md(approval_note)}")
                    if review.get("approval_reply"):
                        _ui.st.caption(f"✅ You replied: {md(review['approval_reply'])}")
                _ui.st.write(md(saved))
                return

            if status == config.WRITING_NEEDS_REVISION:
                history = _feedback_history(
                    review, history_key="feedback_history", single_key="feedback"
                )
                if len(history) == 1:
                    _ui.st.warning(f"Your parent asked for another look: {md(history[0])}")
                elif history:
                    _ui.st.warning(
                        "Your parent asked for another look — everything they've flagged "
                        "so far:\n\n" + "\n".join(f"- {md(note)}" for note in history)
                    )
                else:
                    _ui.st.warning("Your parent asked for another look — revise it below.")

            if status == config.WRITING_SUBMITTED:
                _ui.st.info("⏳ Submitted — waiting on your parent to look at it.")
                _ui.st.write(md(saved))
                if _ui.st.button(
                    "✏️ Actually, let me revise it",
                    key=f"reopen_writing_{lesson_id}_{index}",
                ):
                    db.set_writing_review(lesson_id, index, config.WRITING_DRAFT)
                    _ui.st.rerun()
                return

            draft_key = f"writing_draft_{lesson_id}_{index}"
            # Some kids would rather write in Word than in the box below --
            # the upload just refills that box with the doc's text rather
            # than opening a separate review path, so every check further
            # down (word count, AI review, parent review) keeps working
            # exactly the same whichever way the words got there. Has to run
            # -- and, on a change, rerun -- *before* the text_area below is
            # instantiated: Streamlit refuses a session_state write to a
            # widget's own key once that widget has already appeared this
            # run. Uploading again overwrites whatever's in the box, same as
            # re-typing over it would; comparing against the box's current
            # value (rather than unconditionally rerunning) is what stops
            # this from fighting a response he's since edited by hand -- the
            # file stays "uploaded" across reruns even after its text has
            # already been pulled in.
            uploaded_doc = _ui.st.file_uploader(
                "...or upload a Word doc instead",
                type=["docx"],
                key=f"writing_upload_{lesson_id}_{index}",
            )
            if uploaded_doc is not None:
                try:
                    extracted = extract_docx_text(uploaded_doc)
                except DocxExtractionError as exc:
                    _ui.st.error(str(exc))
                else:
                    if extracted != _ui.st.session_state.get(draft_key, saved):
                        _ui.st.session_state[draft_key] = extracted
                        _ui.st.rerun()
            # The parts he has to cover, one checkbox each -- the fix for
            # skimming a multi-part prompt and answering only the first half.
            # He has to tick every one before "Submit for review" unlocks, so
            # each requirement is something he had to see and acknowledge, not
            # something buried in a paragraph he read past. Ticks persist
            # (checklist_checked in metadata) so a reload doesn't re-lock it.
            checklist_items = activity.get("checklist") or []
            checklist_ready = True
            if checklist_items:
                stored_checks = (
                    ((metadata or {}).get("checklist_checked") or {}).get(str(index)) or []
                )
                for item_index in range(len(checklist_items)):
                    state_key = f"checkitem_{lesson_id}_{index}_{item_index}"
                    if state_key not in _ui.st.session_state:
                        _ui.st.session_state[state_key] = (
                            stored_checks[item_index]
                            if item_index < len(stored_checks)
                            else False
                        )

                def _persist_checklist(lid=lesson_id, idx=index, count=len(checklist_items)):
                    db.set_activity_checklist(
                        lid,
                        idx,
                        [
                            bool(_ui.st.session_state.get(f"checkitem_{lid}_{idx}_{i}"))
                            for i in range(count)
                        ],
                    )

                _ui.st.markdown("**✅ Before you turn it in, check off each part:**")
                checked = [
                    _ui.st.checkbox(
                        md(item),
                        key=f"checkitem_{lesson_id}_{index}_{item_index}",
                        on_change=_persist_checklist,
                    )
                    for item_index, item in enumerate(checklist_items)
                ]
                checklist_ready = all(checked)

            response = _ui.st.text_area(
                "Your response",
                value=_ui.st.session_state.get(draft_key, saved),
                height=160,
                key=draft_key,
            )

            # Coach-only self-help, never a block. The mechanical basics he
            # keeps skipping (capitals, run-ons, end punctuation) caught
            # instantly so he can fix them himself, and -- for anything
            # paragraph-shaped -- a structure to lean on when a blank box is
            # the thing that stalls him. Deeper feedback is "Check my work"
            # and the parent's review.
            for hint_index, hint in enumerate(writing_hints(response)):
                if hint_index == 0:
                    _ui.st.caption("✍️ Quick check before you turn it in:")
                _ui.st.caption(f"• {hint}")

            # Redo gate: a piece the parent sent back can't go straight back in
            # on a silent resubmit -- he has to say, in a few words, what he's
            # changing. Same "more than a one-tap" bar the approval note carries,
            # and the reply rides along to the parent next to the reworked piece.
            revision_reply = ""
            revision_reply_ok = True
            if status == config.WRITING_NEEDS_REVISION:
                revision_reply = _ui.st.text_input(
                    "Before you turn it back in — what are you changing? (in your own words)",
                    value=review.get("revision_reply", ""),
                    key=f"revision_reply_{lesson_id}_{index}",
                    placeholder="e.g. I'm adding a quote to back up my point",
                )
                revision_reply_ok = (
                    len(revision_reply.split()) >= config.WRITING_FEEDBACK_REPLY_MIN_WORDS
                )
                if not revision_reply_ok:
                    _ui.st.caption(
                        f"Say a little about what you'll fix — at least "
                        f"{config.WRITING_FEEDBACK_REPLY_MIN_WORDS} words — before you "
                        "turn it back in."
                    )

            ai_review = _stored_ai_review(metadata, index)
            save_col, check_col, submit_col = _ui.st.columns(3)
            if save_col.button("Save draft", key=f"save_writing_{lesson_id}_{index}"):
                db.save_writing_response(lesson_id, index, response)
                _ui.st.success("Saved.")
                _ui.st.rerun()
            # One call per activity, ever -- the button is gone once a review
            # exists, so a student who'd rather not write can't iterate
            # against the reviewer in place of thinking. Deliberately not
            # offered while there's nothing written to review.
            if ai_review is None and response.strip():
                if check_col.button(
                    "🔍 Check my work", key=f"aicheck_writing_{lesson_id}_{index}"
                ):
                    db.save_writing_response(lesson_id, index, response)
                    with _ui.st.spinner("Reading what you wrote…"):
                        try:
                            writing_review.review_writing(
                                db, student, db.get_lesson(lesson_id), index, response
                            )
                        except LessonGenerationError as exc:
                            _ui.st.error(str(exc))
                        else:
                            _ui.st.rerun()
            submit_clicked = submit_col.button(
                "Submit for review",
                key=f"submit_writing_{lesson_id}_{index}",
                type="primary",
                disabled=not (checklist_ready and revision_reply_ok),
            )
            if not checklist_ready:
                _ui.st.caption(
                    "Tick every part above once you've actually done it — that's how "
                    "you turn this in."
                )
            if submit_clicked:
                # Record his reply to the send-back first, while the piece is
                # still 'needs_revision' (the setter's own guard) -- then the
                # resubmit below carries it forward for the parent to see.
                if status == config.WRITING_NEEDS_REVISION and revision_reply.strip():
                    db.set_writing_revision_reply(lesson_id, index, revision_reply.strip())
                requirements = activity.get("writing_requirements")
                # A math answer is a number or an expression, not prose --
                # "42" is a complete answer, not a zero-sentence failure. The
                # generator sometimes tags a numeric-answer step as a written
                # response and even sets min_sentences on it, which then
                # rejected the answer until he typed a stray period to make it
                # count as a "sentence." Prose word/sentence/quote rules never
                # apply to a math response; only the not-blank check does.
                lesson_row = db.get_lesson(lesson_id)
                if lesson_row and lesson_row.get("agent") == "math":
                    requirements = None
                problems = check_writing(response, requirements)
                if problems:
                    for problem in problems:
                        _ui.st.error(problem)
                else:
                    db.save_writing_response(lesson_id, index, response)
                    db.set_writing_review(lesson_id, index, config.WRITING_SUBMITTED)
                    if _maybe_auto_submit_lesson(db, lesson_id):
                        _ui.st.success(
                            "Submitted — that was the last thing, so your whole "
                            "lesson just went to your parent to review. 📬"
                        )
                    else:
                        _ui.st.success("Submitted!")
                    _ui.st.rerun()

            if ai_review is not None:
                _render_ai_review_for_student(ai_review)
        elif saved:
            _ui.st.markdown("**His response**")
            _ui.st.write(md(saved))


def _render_activity_comic_panel(
    activity: dict[str, Any],
    index: int,
    *,
    parent: bool,
    db: Database | None,
    lesson_id: int | None,
    metadata: dict[str, Any] | None,
    key_prefix: str,
    student: dict[str, Any] | None = None,
) -> None:
    """One activity's card, full width. Collapsing is his own reading
    convenience -- a card he's tucked away as done shrinks to just the
    title bar with a reopen button, nothing more. Parent view always
    shows every card in full regardless of what's collapsed: a parent
    opening a lesson to review or approve it needs to see everything, not
    whatever the student happened to tuck away for himself while working
    through it.
    """
    collapsed = (
        not parent
        and db is not None
        and lesson_id is not None
        and index in ((metadata or {}).get("collapsed_activities") or [])
    )

    with _ui.st.container(key=f"comic_panel_activity_{key_prefix}_{index}"):
        _ui.st.markdown(f'<div class="comic-issue-tag">No. {index + 1}</div>', unsafe_allow_html=True)
        _ui.st.markdown(
            f"##### {md(activity.get('title', 'Activity'))}  \n"
            f"{_comic_phase_pill_html(activity)}"
            f"{_comic_review_flag_html(index, metadata, parent=parent)}",
            unsafe_allow_html=True,
        )
        if collapsed:
            if _ui.st.button("↩️ Done — tap to reopen", key=f"reopen_activity_{key_prefix}_{index}"):
                db.set_activity_collapsed(lesson_id, index, False)
                _ui.st.rerun()
            return

        _ui.st.caption(f"{activity.get('minutes', 0)} min")
        _render_activity_body(
            activity, index, parent=parent, db=db, lesson_id=lesson_id,
            metadata=metadata, student=student,
        )
        if not parent and db is not None and lesson_id is not None:
            if _ui.st.button("✅ Mark this one done", key=f"collapse_activity_{key_prefix}_{index}"):
                db.set_activity_collapsed(lesson_id, index, True)
                _ui.st.rerun()


def _render_learn_section(lesson: dict[str, Any], *, parent: bool) -> None:
    """The teaching half of the fixed lesson shape -- the Learn explanation (with
    its one video) and the walked-through Worked example -- rendered before the
    two graded activities. Silent on an old-shape lesson that has neither, so it
    layers in without disturbing how existing lessons render."""
    learn = lesson.get("learn") or {}
    explanation = (learn.get("explanation") or "").strip()
    worked = lesson.get("worked_example") or {}
    problem = (worked.get("problem") or "").strip()
    steps = (worked.get("steps") or "").strip()

    if explanation:
        _ui.st.markdown("### 📗 Learn")
        _ui.st.write(md(explanation))
        video = learn.get("video") or {}
        if video.get("found") and video.get("url"):
            _ui.st.markdown(f"▶️ **[{md(video.get('title', 'Watch'))}]({video['url']})**")
            bits = [b for b in (video.get("channel"), video.get("why")) if b]
            if bits:
                _ui.st.caption(" — ".join(bits))
            if parent:
                _ui.st.caption(
                    "Checked against a real search result and restricted to YouTube, "
                    "but Compass doesn't control what YouTube recommends after it ends."
                )

    if problem or steps:
        _ui.st.markdown("### 🧭 Let's do one together")
        _ui.st.caption("Worked all the way through, so you can see how — you're not graded on this one.")
        if problem:
            _ui.st.markdown(f"**{md(problem)}**")
        if steps:
            _ui.st.markdown(
                f'<div style="background:var(--c-panel); border-left:3px solid '
                f'var(--c-alt); border-radius:var(--c-radius); padding:10px 14px; '
                f'margin:6px 0 12px; font-size:14px;">'
                f'{html.escape(steps).replace(chr(10), "<br>")}</div>',
                unsafe_allow_html=True,
            )

    if explanation or problem or steps:
        # The graded work starts here -- a clear line between "taught" and "your
        # turn," since the two activities below are what actually get a grade.
        _ui.st.markdown("### ✏️ Now you try")


def render_lesson(
    lesson: dict[str, Any],
    for_parent: bool | None = None,
    *,
    db: Database | None = None,
    lesson_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    comic_layout: bool = False,
    comic_frame_title: str = "📘 Current Lesson",
    student: dict[str, Any] | None = None,
    printable: bool = False,
) -> None:
    """Render a lesson. In student view the answer key never reaches the page.

    The redaction happens here rather than in a CSS class or an expander, because
    anything sent to the browser can be read out of it. What a student must not
    see is simply not written.

    `db`/`lesson_id`/`metadata` are optional and only matter for a writing
    activity: given all three, in student view, that activity gets an actual
    text box instead of just instructions to write on paper -- his response
    saves straight to this lesson (`Database.save_writing_response`), which
    is what `render_assessment_card` later shows a parent when it's time to
    check the lesson. Omitted (the generation-preview call in
    `generate_and_log`, where nothing's been written yet and the viewer is
    the parent anyway), the writing activity just renders like any other.
    """
    parent = _ui.is_parent() if for_parent is None else for_parent
    objectives = lesson.get("learning_objectives") or []
    materials = lesson.get("materials") or []
    activities = lesson.get("activities") or []

    if comic_layout:
        _ui.st.markdown(_COMIC_PANEL_CSS, unsafe_allow_html=True)
        key_prefix = str(lesson_id) if lesson_id is not None else str(id(lesson))
        with _ui.st.container(key=f"comic_frame_lesson_{key_prefix}"):
            _ui.st.markdown(
                f'<div class="comic-frame-title">{html.escape(comic_frame_title)}</div>',
                unsafe_allow_html=True,
            )
            dots = _comic_progress_dots_html(activities, metadata)
            if dots:
                _ui.st.markdown(dots, unsafe_allow_html=True)

            _ui.st.markdown(f"## {md(lesson.get('title', 'Lesson'))}")
            if lesson.get("overview"):
                _ui.st.write(md(lesson["overview"]))

            if objectives or materials:
                columns = _ui.st.columns(2)
                with columns[0]:
                    if objectives:
                        _ui.st.markdown("**Learning objectives**")
                        for objective in objectives:
                            _ui.st.markdown(f"- {md(objective)}")
                with columns[1]:
                    # Materials before activities on purpose -- knowing what
                    # you need is part of being set up to start, not a
                    # footnote to read after being told what to do.
                    if materials:
                        _ui.st.markdown("**Materials**")
                        for item in materials:
                            _ui.st.markdown(f"- {md(item)}")

            # The teaching half (Learn + Worked example) comes before the two
            # graded activities in the fixed lesson shape.
            _render_learn_section(lesson, parent=parent)

            # Single column, full width -- pairing two activities per row
            # (the original comic-grid mockup) left mismatched-height cards
            # squeezed side by side whenever one activity had more to show
            # than its neighbor (a video, a worked example). One card per
            # row lets each one take exactly the room it needs.
            for index, activity in enumerate(activities):
                _render_activity_comic_panel(
                    activity,
                    index,
                    parent=parent,
                    db=db,
                    lesson_id=lesson_id,
                    metadata=metadata,
                    key_prefix=key_prefix,
                    student=student,
                )
    else:
        _ui.st.subheader(md(lesson.get("title", "Lesson")))
        if lesson.get("overview"):
            _ui.st.write(md(lesson["overview"]))

        if objectives:
            _ui.st.markdown("**Learning objectives**")
            for objective in objectives:
                _ui.st.markdown(f"- {md(objective)}")
        if materials:
            _ui.st.markdown("**Materials**")
            for item in materials:
                _ui.st.markdown(f"- {md(item)}")

        _render_learn_section(lesson, parent=parent)

        if activities:
            _ui.st.markdown("**Activities**")
            for index, activity in enumerate(activities, start=1):
                header = (
                    f"{index}. {md(activity.get('title', 'Activity'))} · "
                    f"{_PHASE_LABELS.get(activity_phase(activity), '')} · {activity.get('minutes', 0)} min"
                )
                with _ui.st.expander(header, expanded=False):
                    _render_activity_body(
                        activity,
                        index - 1,
                        parent=parent,
                        db=db,
                        lesson_id=lesson_id,
                        metadata=metadata,
                        student=student,
                    )

    # Parent-only: the actual check now happens digitally, in Activity Log's
    # own review card (render_assessment_card), not here -- nothing for him
    # to do with this text, so student view shows nothing at all rather than
    # a "your parent has it" stub that no longer matches how it's checked.
    assessment = lesson.get("assessment") or {}
    # The rubric is the ONE part of the hand-in that's safe for him to see -- it
    # describes qualities of a strong response, not the answers. Shown to him as
    # his bar before he starts; the parent also gets it in the grading panel.
    if assessment.get("rubric") and not parent:
        with _ui.st.container(border=True, key=f"landon_card_rubric_{lesson_id or 'x'}"):
            _ui.st.markdown("**🎯 What a strong hand-in looks like**")
            _ui.st.markdown(md(assessment["rubric"]))
    if assessment and parent:
        _ui.st.markdown("**Hand-in** (the work he turns in for you to grade)")
        _ui.st.caption(
            "One of the two things his grade comes from -- the finished piece "
            "he hands you, graded with the 5-band verdict in the review tab. "
            "The other is the on-screen quiz below, which he takes and grades "
            "himself. Everything above is practice that gets him ready for these."
        )
        _ui.st.markdown(f"*{md(assessment.get('kind', ''))}* — {md(assessment.get('description', ''))}")
        if assessment.get("rubric"):
            _ui.st.markdown(f"**How it's graded (he sees this too):**\n\n{md(assessment['rubric'])}")
        if assessment.get("mastery_criteria"):
            _ui.st.markdown(f"**Counts as mastered when:** {md(assessment['mastery_criteria'])}")

    if parent:
        if lesson.get("parent_notes"):
            with _ui.st.expander("Notes for the parent"):
                _ui.st.write(md(lesson["parent_notes"]))

        credits = lesson.get("subject_credits") or []
        if credits:
            _ui.st.markdown("**Subject credit (feeds the WA compliance dashboard)**")
            for credit in credits:
                _ui.st.markdown(
                    f"- **{subjects.label(credit['subject'])}** — {credit['minutes']} min · "
                    f"{md(credit.get('justification', ''))}"
                )

        branches = lesson.get("branches") or []
        if branches:
            with _ui.st.expander(f"Branches this opens up ({len(branches)})"):
                for branch in branches:
                    _ui.st.markdown(f"- **{md(branch.get('topic'))}** — {md(branch.get('rationale', ''))}")

        quiz = lesson.get("quiz") or []
        if quiz:
            with _ui.st.expander(f"Quiz answer key ({len(quiz)} questions)"):
                for index, item in enumerate(quiz, start=1):
                    _ui.st.markdown(f"**{index}. {md(item['question'])}**")
                    for choice_index, choice in enumerate(item["choices"]):
                        marker = "✅" if choice_index == item["correct_index"] else "—"
                        _ui.st.markdown(f"{marker} {md(choice)}")
                    if item.get("explanation"):
                        _ui.st.caption(md(item["explanation"]))

    # A one-click printable worksheet for a paper day: the student copy (no
    # answer keys) with ruled lines under written activities and the quiz laid
    # out to circle. Offered wherever the lesson is shown to work from -- his
    # subject page (printable=True) -- rather than only the parent's review card.
    if printable:
        _ui.st.download_button(
            "🖨️ Print this as a worksheet (PDF)",
            data=partial(lesson_to_pdf, lesson, parent=False),
            file_name=suggested_pdf_filename(lesson),
            mime="application/pdf",
            key=f"print_worksheet_{lesson_id or id(lesson)}",
        )


