"""Vocabulary review -- the multiple-choice, auto-graded word quiz.

Split out of compass.ui. Only st/date/is_parent go through `_ui`.
"""
from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

import compass.ui as _ui
from compass.storage.db import Database
from compass.ui import _COMIC_PANEL_CSS, md


VOCAB_STREAK_HYPE = ["Nice!", "Boom!", "Nailed it!", "You got it!", "Crushed it!", "Sweet!"]
VOCAB_STREAK_ON_FIRE = 5  # streak length that earns balloons, not just a toast

VOCAB_QUIZ_CHOICES = 4  # the correct definition plus up to three decoys
VOCAB_QUIZ_MIN_DEFINED_WORDS = 2  # need at least one other word to draw a decoy from


def _render_vocab_done_button(db: Database, student: dict[str, Any], today: str) -> None:
    """A real, persisted "he reviewed his words today" signal -- unlike the
    Concentration game's own streak/reviewed-count (session state only, gone
    the moment the browser session ends), this survives a refresh or a new
    session, and is what render_today_checklist reads to show it alongside
    lesson and life-skill completions. Always available, not gated behind
    clearing every due word in one sitting -- same trust-his-click
    philosophy as a lesson's own "I'm done for today" button, and the same
    reason that one exists: nothing here was actually prompting him to treat
    this as a real, completable task.
    """
    if db.vocab_reviewed_on(student["id"], today):
        _ui.st.success("✅ Marked done for today.")
        return
    if _ui.st.button("✅ I'm done with words for today", key="vocab_done_today"):
        db.mark_vocab_reviewed(student["id"], today)
        _ui.st.rerun()


def render_vocab_activity_for_parent(
    db: Database, student: dict[str, Any], *, day: str | None = None
) -> None:
    """A parent's window into the words game: exactly which words he answered
    today and how he did on each -- not just the cumulative box counts, which
    never say what happened *today* (reported: "i also dont see any parent
    insight into what he actually did for that today"). Reads the per-answer
    log; the marks are his real picks, so a word he got wrong then right in the
    same sitting shows both. Meant for the parent Vocabulary tab."""
    today = day or _ui.date.today().isoformat()
    attempts = db.vocab_attempts_on(student["id"], today)
    _ui.st.markdown("**👀 What he did in the words game today**")
    if not attempts:
        if db.vocab_reviewed_on(student["id"], today):
            _ui.st.caption(
                "He marked words done for today but didn't answer any — nothing "
                "was due, or he cleared the game before a word came up."
            )
        else:
            _ui.st.caption("He hasn't played the words game yet today.")
    else:
        total = len(attempts)
        correct = sum(1 for a in attempts if a["correct"])
        _ui.st.caption(
            f"He gave **{total}** answer(s) in the words game today — ✅ {correct} "
            f"right, ❌ {total - correct} missed."
        )
        # Collapse to one line per word, in the order he first met it, with a
        # mark per try -- so a word he missed then got shows "❌✅" not twice.
        by_word: dict[str, list[bool]] = {}
        for attempt in attempts:
            by_word.setdefault(attempt["word"], []).append(bool(attempt["correct"]))
        for word, results in by_word.items():
            marks = "".join("✅" if r else "❌" for r in results)
            tries = f" · {len(results)} tries" if len(results) > 1 else ""
            _ui.st.markdown(f"{marks} **{md(word)}**{tries}")

    _render_vocab_rollup(db, student, today)


def _render_vocab_rollup(
    db: Database, student: dict[str, Any], today: str, *, days: int = 7
) -> None:
    """A compact last-week view under today's detail: one line per day he
    played, with answers and accuracy, plus a window total -- so a parent can
    see whether he's keeping up with words over time, not just today."""
    end = _ui.date.fromisoformat(today)
    start = end - timedelta(days=days - 1)
    rows = db.vocab_activity_rollup(
        student["id"], start.isoformat(), end.isoformat()
    )
    if not rows:
        return
    total = sum(r["answered"] for r in rows)
    correct = sum(r["correct"] or 0 for r in rows)
    pct = round(100 * correct / total) if total else 0
    with _ui.st.expander(
        f"📅 Last {days} days — {correct}/{total} right ({pct}%), "
        f"{len(rows)} day(s) played"
    ):
        for row in rows:
            answered = row["answered"]
            day_correct = row["correct"] or 0
            day_pct = round(100 * day_correct / answered) if answered else 0
            label = _ui.date.fromisoformat(row["reviewed_on"]).strftime("%a %b %-d")
            _ui.st.markdown(
                f"**{label}** — {day_correct}/{answered} right ({day_pct}%)"
            )


def render_vocab_quiz(db: Database, student: dict[str, Any]) -> None:
    """Vocabulary review: multiple choice, auto-graded. The word shows, four
    possible definitions follow -- the real one plus up to three decoys
    pulled from his own other vocabulary words (no AI call needed, and a
    decoy that's a real definition of a real word he's also learning is a
    more honest test than an invented one) -- pick one, get graded
    immediately.

    Replaced a Concentration/memory-match game that mostly tested spatial
    memory (where was that card?) rather than whether he actually knew a
    definition -- matching two already-visible cards never required
    recalling one cold. This asks him to recall it directly instead, same
    db.record_vocabulary_review() call either way, so the Leitner schedule
    underneath means the same thing regardless of which review mode came
    before it.

    One word on screen at a time, not a whole board of them -- a wrong
    pick's reveal (the real definition, right there next to what he
    guessed) is the actual teaching moment, so it stays up until he clicks
    past it rather than auto-advancing to the next word.
    """
    today = _ui.date.today().isoformat()
    due = [entry for entry in db.vocabulary_due(student["id"], limit=25) if entry["definition"]]
    streak = _ui.st.session_state.setdefault("vocab_streak", 0)
    best_streak = _ui.st.session_state.setdefault("vocab_best_streak", 0)
    reviewed = _ui.st.session_state.setdefault("vocab_reviewed_count", 0)
    state = _ui.st.session_state.setdefault("vocab_quiz", {})
    # Answering a word moves its own next_review_on forward regardless of
    # right or wrong (see record_vocabulary_review), so it drops out of
    # `due` the instant he picks -- before he's even seen the reveal. A
    # mid-reveal word (picked is set, waiting on "Next word") has to keep
    # showing anyway, even once `due` no longer contains it or is empty.
    mid_reveal = state.get("picked") is not None

    _ui.st.markdown(_COMIC_PANEL_CSS, unsafe_allow_html=True)
    with _ui.st.container(key="comic_frame_vocab"):
        _ui.st.markdown(
            '<div class="comic-frame-title">🔤 Words to Review</div>', unsafe_allow_html=True
        )

        if not due and not mid_reveal:
            if reviewed:
                _ui.st.success(
                    f"🎉 All caught up! {reviewed} word(s) reviewed, best streak {best_streak}."
                )
            else:
                _ui.st.success("Nothing due for review today.")
            _render_vocab_done_button(db, student, today)
            return

        all_defined = [w for w in db.list_vocabulary(student["id"]) if w["definition"]]
        if len(all_defined) < VOCAB_QUIZ_MIN_DEFINED_WORDS and not mid_reveal:
            _ui.st.info(
                "Add a few more words (with definitions) from his reading before he can be "
                "quizzed on them."
            )
            _render_vocab_done_button(db, student, today)
            return

        if "word_id" not in state:
            word = due[0]
            decoy_pool = [w["definition"] for w in all_defined if w["id"] != word["id"]]
            random.shuffle(decoy_pool)
            choices = [word["definition"]] + decoy_pool[: VOCAB_QUIZ_CHOICES - 1]
            random.shuffle(choices)
            state.clear()
            state.update(word_id=word["id"], choices=choices, picked=None)

        word = next(w for w in all_defined if w["id"] == state["word_id"])

        with _ui.st.container(key=f"comic_panel_vocab_{word['id']}"):
            # No issue tag here, unlike the activity panels -- the metrics
            # row right below already shows the streak, and a badge
            # repeating the same number just above it read as duplicative
            # rather than styled.
            metrics = _ui.st.columns(3)
            metrics[0].metric("🔥 Streak", streak)
            metrics[1].metric("✅ Reviewed", reviewed)
            metrics[2].metric("Left today", len(due))

            _ui.st.markdown(f"## {md(word['word'].upper())}")

            if state["picked"] is None:
                _ui.st.caption("Which definition is correct?")
                for index, choice in enumerate(state["choices"]):
                    if _ui.st.button(
                        md(choice), key=f"vocab_choice_{word['id']}_{index}", width="stretch"
                    ):
                        correct = choice == word["definition"]
                        state["picked"] = choice
                        db.record_vocabulary_review(word["id"], correct=correct)
                        _ui.st.session_state["vocab_reviewed_count"] = reviewed + 1
                        if correct:
                            new_streak = streak + 1
                            _ui.st.session_state["vocab_streak"] = new_streak
                            _ui.st.session_state["vocab_best_streak"] = max(best_streak, new_streak)
                            if new_streak >= VOCAB_STREAK_ON_FIRE:
                                _ui.st.toast(f"🚀 {new_streak} in a row — you're on fire!")
                            else:
                                _ui.st.toast(
                                    f"{random.choice(VOCAB_STREAK_HYPE)} 🔥 {new_streak} in a row"
                                )
                        else:
                            _ui.st.session_state["vocab_streak"] = 0
                            _ui.st.toast("❌ Not quite.")
                        _ui.st.rerun()
            else:
                for choice in state["choices"]:
                    if choice == word["definition"]:
                        _ui.st.success(f"✅ {md(choice)}")
                    elif choice == state["picked"]:
                        _ui.st.error(f"❌ {md(choice)} — your pick")
                    else:
                        _ui.st.write(md(choice))
                if _ui.st.button("Next word ▶️", type="primary", key="vocab_next_word"):
                    state.clear()
                    _ui.st.rerun()

        _ui.st.divider()
        _render_vocab_done_button(db, student, today)


