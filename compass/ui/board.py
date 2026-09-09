"""The weekly board -- the shared move control, the Mon-Fri day grid, and the
per-subject week view.

Split out of compass.ui. Only st/date/is_parent go through `_ui`.
"""
from __future__ import annotations

import re
from functools import partial
from typing import Any, Callable

import compass.ui as _ui
from compass import config, theme as theming, weekly
from compass.export import lesson_to_pdf, suggested_pdf_filename
from compass.storage.db import Database
from compass.ui import (
    BOARD_KIND_ICONS,
    EPIC_ICONS,
    SUBJECT_ICONS,
    _BOARD_ROW_ORDER,
    _board_identity,
    board_card_tag,
    hand_in_summary,
    md,
    render_lesson,
)


#
# One consistent control for moving any "story" -- a lesson, a Big Project
# step, a Choice Topic, a Life Skill, a Coding Camp module -- around the
# board: a date picker to assign or move it to a day, or send it back to the
# Backlog. Lives on every card that already carries an `active` flag and a
# `scheduled_for` date, in place of that surface's own scattered buttons.


def render_story_move_control(
    *,
    key: str,
    active: bool,
    scheduled_for: str | None,
    set_active: Callable[[bool], None],
    schedule: Callable[[str | None], None],
    validate_schedule: Callable[[str], str | None] | None = None,
    show_backlog_toggle: bool = True,
    delete: Callable[[], None] | None = None,
) -> None:
    """`key` must be unique per story (the caller's own id namespace, e.g.
    `f"step_{step['id']}"`). `set_active`/`schedule` are the two writes this
    control ever makes -- callers pass their own db call, e.g.
    `lambda a: db.set_project_step_active(step["id"], a)`.

    `validate_schedule`, if given, is called with the picked date before
    `schedule` -- return an error string to block the move (shown in place,
    the popover stays open) or `None` to let it through. Only lessons need
    this (two lessons from the same agent can't share a day); every other
    story type leaves it unset.

    `delete`, if given, adds a "🗑️ Delete" section at the bottom, gated behind a
    confirm checkbox because it's irreversible -- `delete()` is the caller's own
    hard-delete write (e.g. `lambda: db.delete_lesson(lid)`). Only lessons pass
    it today (an accidental double-generate a parent wants gone for good);
    catalog-backed stories like life skills are hidden/parked, never deleted.

    `show_backlog_toggle` stays on its default (on) for every caller today.
    Backlogging and un-backlogging are each their own one-way button --
    "Send to backlog" only when `active`, "Take out of Backlog" only when
    not -- never a single checkbox meaning opposite things depending on
    which state it started in. That used to read as "uncheck this to
    bring it back," which for a lesson meant something genuinely
    destructive: unchecking it called `set_active(True)`, and a lesson's
    own implementation of that used to silently reschedule to *today*,
    overwriting whatever day a parent had just picked in the very same
    popover (reported directly -- "i moved two math lessons from backlog
    to their own dates... and they have disappeared"). Picking a new day
    in "Assign to a specific day" already takes a story out of the
    backlog on its own, for every story kind (each one's own `schedule`
    write does this) -- "Take out of Backlog" is only there for
    reactivating *without* also changing the day.

    Widget keys fold in the current `scheduled_for` value for the date
    picker (the same trick `render_life_skill_catalog_manager` uses for
    its own checkbox -- `schedule` can change what's "current" as a side
    effect of a different widget's write, and a fixed key would read a
    stale session_state value as a fresh pick on the next run and
    silently redo it) -- but not for the backlog buttons, since a
    `st.button`'s own return value never persists across a rerun the way
    a checkbox's does, so there's no stale state for a fixed key to leak.
    """
    # Icon-only when there's nothing to report yet -- this sits in a narrow
    # top-right corner on a card grid (three cards to a row), and a two-word
    # label wraps into an unreadable vertical sliver at that width. The
    # other two states already read fine at that width on their own.
    #
    # `active` is checked *before* `scheduled_for`: every story type here
    # keeps its old scheduled_for/planned_for value even after being sent to
    # backlog (none of the set_active/send_to_backlog implementations clear
    # it), so a backlogged story with a leftover date would otherwise still
    # show "📅 <that date>" here instead of "🗄️ Backlog" -- exactly the
    # trigger for it no longer reading as backlogged at a glance.
    if not active:
        label = "🗄️ Backlog"
    elif scheduled_for:
        label = f"📅 {scheduled_for}"
    else:
        label = "📅"
    with _ui.st.popover(label, use_container_width=False, help="Move to a day, or send to Backlog"):
        if not active:
            _ui.st.caption("🗄️ Currently in the Backlog.")

        assign = _ui.st.checkbox(
            "Assign to a specific day",
            value=bool(scheduled_for),
            key=f"move_{key}_assign_{scheduled_for}",
        )
        if assign:
            picked = _ui.st.date_input(
                "Day",
                value=_ui.date.fromisoformat(scheduled_for) if scheduled_for else _ui.date.today(),
                key=f"move_{key}_date_{scheduled_for}",
            )
            if picked.isoformat() != scheduled_for:
                problem = validate_schedule(picked.isoformat()) if validate_schedule else None
                if problem:
                    _ui.st.error(problem)
                else:
                    schedule(picked.isoformat())
                    _ui.st.rerun()
        elif scheduled_for:
            schedule(None)
            _ui.st.rerun()

        if show_backlog_toggle:
            _ui.st.divider()
            if active:
                if _ui.st.button("🗄️ Send to backlog", key=f"move_{key}_send_to_backlog"):
                    set_active(False)
                    _ui.st.rerun()
            else:
                if _ui.st.button("↩️ Take out of Backlog", key=f"move_{key}_take_out_of_backlog"):
                    set_active(True)
                    _ui.st.rerun()

        if delete is not None:
            _ui.st.divider()
            _ui.st.caption("🗑️ **Delete** — once it's gone, it's gone for good.")
            confirm = _ui.st.checkbox(
                "Yes, delete this for good", key=f"move_{key}_delete_confirm"
            )
            if _ui.st.button(
                "🗑️ Delete",
                key=f"move_{key}_delete",
                disabled=not confirm,
                type="primary",
            ):
                delete()
                _ui.st.rerun()


# Where a story's own full content already renders elsewhere in the app --
# the Math/Science/English/History pages are planning tools with no
# per-lesson content view, so a lesson's real "deeper review" destination is
# Activity Log's own review queue, not its subject page. (page, link label,
# the tab that content lives under.)
#
# Life Skills' and Big Projects' own Checklist tab is each page's first tab,
# so a plain st.page_link there already lands exactly where it says --
# Streamlit opens a page on its first tab with no way to request another
# one. Activity Log's own "To review" tab is its *third* tab (behind "The
# record" and "Log something manually"), so the exact same page_link there
# always landed on the wrong screen instead -- confirmed live: "the
# navigation for next week's board, go to full lesson, doesn't actually
# work." A lesson's own deep link is handled separately below instead of
# through this table, as a same-page dialog that needs no tab at all.
_BOARD_DEEP_LINK: dict[str, tuple[str, str, str]] = {
    "life_skill": ("pages/6_Life_Skills.py", "Open it", "Checklist"),
    "coding_module": ("pages/6_Life_Skills.py", "Open it", "Coding Camp"),
    "choice_topic": ("pages/6_Life_Skills.py", "Open it", "Life Skills"),
    "project_step": ("pages/7_Big_Projects.py", "Open it", "Checklist"),
    "travel_entry": ("pages/9_Landons_Travels.py", "Open it", "Travel journal"),
}


def _render_board_deep_link(
    kind: str, item: dict[str, Any] | None = None, *, db: Database | None = None
) -> None:
    if kind == "lesson":
        # A page_link can only ever open a page on its *first* tab, and
        # Activity Log's lesson-review tab isn't its first -- no target
        # this function could name would ever actually land there. A
        # same-page st.dialog sidesteps the whole problem: no navigation,
        # no tab to miss, works identically for a lesson on this week's
        # board or next week's.
        assert item is not None

        @_ui.st.dialog(f"📘 {item['title']}", width="large")
        def _show_full_lesson() -> None:
            # for_parent is left unset so render_lesson falls back to
            # is_parent() -- on Landon's own board the assessment and answer
            # key stay hidden, exactly as they do in his normal lesson view.
            # The PDF matches: parent=is_parent() gives the parent the whole
            # lesson (answer key included) and Landon a clean copy of just the
            # lesson itself (no answer key, no assessment, no parent notes), so
            # he can print his own board lesson without it carrying anything he
            # isn't meant to see.
            parent = _ui.is_parent()
            _ui.st.download_button(
                "🖨️ Print to PDF",
                data=partial(lesson_to_pdf, item["payload"], parent=parent),
                file_name=suggested_pdf_filename(item["payload"]),
                mime="application/pdf",
                key=f"board_pdf_{item['id']}",
            )
            # In student view, hand render_lesson the db/lesson_id/metadata (and
            # student) so a writing activity gets its real text box + Word-doc
            # upload right here, not just instructions to write on paper --
            # reported directly: a writing assignment on his board "should be a
            # text input box for that writing assignment and upload file." The
            # parent keeps the plain preview (db left off) so their view stays
            # the read-only answer-key copy, not an input surface.
            student = db.ensure_default_student() if (db is not None and not parent) else None
            render_lesson(
                item["payload"],
                db=None if parent else db,
                lesson_id=item["id"],
                metadata=item.get("metadata") or {},
                student=student,
                # For him, the comic layout renders each activity open (not
                # tucked in a collapsed expander), so the writing box + upload
                # sit right there to fill in rather than a click deep. The
                # parent keeps the plain preview.
                comic_layout=not parent,
                comic_frame_title=f"📘 {item['title']}",
            )

        if _ui.st.button("🔍 View full lesson", key=f"board_view_lesson_{item['id']}"):
            _show_full_lesson()
        return

    page, label, tab_hint = _BOARD_DEEP_LINK[kind]
    _ui.st.page_link(page, label=label, icon="🔍")
    _ui.st.caption(f'Under the "{tab_hint}" tab.')


def _render_board_detail(
    description: str | None = None,
    materials: str | None = None,
    *,
    pace: str | None = None,
    note: str | None = None,
) -> None:
    """The actual content of a non-lesson board card -- what the step/skill/
    trip *is* -- rendered inside the expander regardless of `interactive`.

    Without this, a life-skill or coding card showed only its category and a
    project-step or travel card showed nothing at all: on Landon's read-only
    board (interactive=False) every parent-only affordance is stripped, so
    those cards opened to an empty body. Reported directly against his board:
    "life skill and big project arent loading in the board correctly with the
    lesson or steps." The description is the lesson/step itself and belongs on
    both boards; the move control and deep link stay parent-only above this."""
    if description:
        _ui.st.write(md(description))
    if materials:
        _ui.st.caption(f"🧰 You'll need: {md(materials)}")
    if pace:
        _ui.st.caption(f"⏳ {pace}")
    if note:
        _ui.st.caption(note)


def _render_board_estimate_editor(db: Database, kind: str, item: dict[str, Any]) -> None:
    """A compact, parent-only "how long is this block" input on a board card --
    the sprint-points-style estimate a parent asked to be able to set ("just
    like point scorng in sprints"). Pre-filled with the card's current
    effective estimate (their own saved one, or the rough default); saving a
    new number stores an override, and setting it to 0 clears back to the
    default. The day header's total and the card's own tag re-sum from this on
    the next run, so it doubles as the balance dial for the whole day."""
    widget_key = f"board_est_{kind}_{item['id']}"

    def _save(kind=kind, item_id=item["id"], key=widget_key) -> None:
        raw = _ui.st.session_state.get(key)
        # 0 (or blank) clears the override so the card falls back to its
        # default; any other number is stored as the parent's own estimate.
        db.set_board_estimate(kind, item_id, int(raw) if raw else None)

    _ui.st.number_input(
        "⏱️ Estimate (min)",
        min_value=0,
        max_value=600,
        step=5,
        value=board_item_minutes(kind, item),
        key=widget_key,
        on_change=_save,
        help="Your rough time for this block — feeds the day's total. Set to 0 to use the default.",
    )


def _project_step_pace(item: dict[str, Any]) -> str | None:
    """A step's loose day range as a pace phrase -- "a few days to a week is
    the idea", never a deadline (same framing pages/7_Big_Projects.py's own
    step rows use). None when the step carries no range to show."""
    lo, hi = item.get("min_days"), item.get("max_days")
    if not lo and not hi:
        return None
    if lo == hi:
        return f"about {lo} day" if lo == 1 else f"about {lo} days"
    return f"about {lo}-{hi} days"


_TRAVEL_BOARD_PROMPTS = {
    "planned": "✍️ Time to write this trip up.",
    "needs_revision": "↩️ Sent back — give it another pass.",
    "submitted": "📤 Written up — waiting on a parent to read it.",
    "completed": "✅ Written up and in the journal.",
}


def board_item_minutes(kind: str, item: dict[str, Any]) -> int:
    """A minutes estimate for one board story, so the weekly board can show a
    per-card time and sum a per-day total -- the "is this day too heavy or too
    light" gauge a parent asked for.

    A parent's own saved estimate wins first (`item["estimate_minutes"]`, set by
    set_board_estimate -- the sprint-points-style override, any int including 0).
    With none saved it falls back to a sensible default: a lesson's real
    estimate (its own `estimated_minutes`, else the sum of its activities'
    minutes, else its credited minutes); a travel entry's writing +
    social-studies credit; and a round, tunable per-kind block
    (config.BOARD_BLOCK_MINUTES) for the rest, which carry no stored duration.
    All estimates for balancing a week, not a claim of exact time -- callers
    render them with a "≈"."""
    override = item.get("estimate_minutes")
    if override is not None:
        return int(override)
    if kind == "lesson":
        payload = item.get("payload") or {}
        est = payload.get("estimated_minutes")
        if est:
            return int(est)
        activity_total = sum(int(a.get("minutes") or 0) for a in payload.get("activities") or [])
        if activity_total:
            return activity_total
        credit_total = sum(int(c.get("minutes") or 0) for c in payload.get("subject_credits") or [])
        if credit_total:
            return credit_total
        return int(config.DEFAULT_SETTINGS["default_lesson_minutes"])
    if kind == "travel_entry":
        return (
            config.TRAVEL_JOURNAL_WRITING_MINUTES
            + config.TRAVEL_JOURNAL_SOCIAL_STUDIES_MINUTES
        )
    return config.BOARD_BLOCK_MINUTES.get(kind, 30)


def format_board_minutes(total: int) -> str:
    """Whole minutes as a compact "1h 30m" / "45m" / "2h" -- the board's own
    time labels. 0 or negative reads as "0m" rather than a blank."""
    if total <= 0:
        return "0m"
    hours, minutes = divmod(int(total), 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


_BOARD_MOVE_NOTICE_KEY = "_board_move_notice"


def _board_schedule(
    schedule: Callable[[str | None], None], board_week_start: _ui.date
) -> Callable[[str | None], None]:
    """Wraps a board card's own `schedule` write with a note whenever the
    picked day lands outside the week currently on screen.

    `board_for_week` only ever returns the one week it was asked for, so a
    story moved to a date in a different week simply isn't in that result
    at all -- it doesn't render anywhere on the board a parent is looking
    at, with nothing to say where it went. It hasn't vanished; it's on
    whatever week that date belongs to now.

    This can't just call `st.toast` -- the move control that calls this
    always follows it with `st.rerun()`, and a toast fired in the same run
    that immediately reruns never reaches the browser at all (confirmed
    against this app's own Streamlit version: it silently drops). Instead
    the note is stashed in `session_state` and rendered once, as a real
    `st.info`, by `render_board_move_notice` at the top of the Board tab
    on the *next* run -- session_state is what actually survives a rerun.
    """

    def _wrapped(new_date: str | None) -> None:
        schedule(new_date)
        if not new_date:
            return
        moved_week = weekly.week_start(_ui.date.fromisoformat(new_date))
        if moved_week != board_week_start:
            when = "next week's" if moved_week > board_week_start else "an earlier week's"
            _ui.st.session_state[_BOARD_MOVE_NOTICE_KEY] = (
                f"Moved to {new_date} -- that's on {when} board, not this one. "
                "Nothing was lost; switch weeks above to see it."
            )

    return _wrapped


def render_board_move_notice() -> None:
    """Shows and clears whatever `_board_schedule` stashed on the previous
    run, if anything -- call once, near the top of the Board tab, before
    any card can queue a new one of its own."""
    notice = _ui.st.session_state.pop(_BOARD_MOVE_NOTICE_KEY, None)
    if notice:
        _ui.st.info(notice)


def render_reading_board_card(db: Database, student: dict[str, Any], *, can_edit: bool) -> None:
    """The standing "every day" reading card that sits at the top of the board.
    Unlike the day-by-day stories it isn't pinned to a weekday -- it's a daily
    placeholder that's simply on or off: while it's on (the current book has a
    pages-per-day goal) it shows here and drives his Due-today reading tile;
    the parent takes it off with one button and both disappear. On his own board
    it's read-only; the add/remove controls are the parent's (`can_edit`)."""
    from compass import reading as _reading

    book = db.current_book(student["id"])
    rate = int((book or {}).get("pages_per_day") or 0)
    if book and rate > 0:
        active = _reading.parse_reading_days(book.get("reading_days") or "")
        with _ui.st.container(border=True):
            columns = _ui.st.columns([4, 1]) if can_edit else [_ui.st.container()]
            when = (
                "every day"
                if active is None
                else ", ".join(
                    _reading.WEEKDAY_LABELS[d] for d in sorted(active)
                ) or "no days set"
            )
            if can_edit:
                columns[0].markdown(
                    f"📖 **Daily reading · {when}** · {md(book['title'])}"
                )
                # Change the daily page count right here, any time -- saves the
                # moment it changes, so his target updates on the next open.
                new_rate = columns[0].number_input(
                    "Pages per day", min_value=1, max_value=500, value=rate,
                    key=f"reading_board_rate_{book['id']}",
                )
                if int(new_rate) != rate:
                    db.update_book(book["id"], pages_per_day=int(new_rate))
                    _ui.st.rerun()
                columns[0].caption(
                    "A standing daily assignment. Tick the days it's on; untick a "
                    "day to skip reading then. It shows on his Due-today list on the "
                    "days it's on until you Remove it."
                )
                # One checkbox per weekday -- tick the days reading is assigned.
                day_cols = _ui.st.columns(7)
                current = (
                    active if active is not None else set(range(7))
                )
                picked: set[int] = set()
                for index, label in enumerate(_reading.WEEKDAY_LABELS):
                    if day_cols[index].checkbox(
                        label, value=(index in current),
                        key=f"reading_day_{book['id']}_{index}",
                    ):
                        picked.add(index)
                if picked and picked != current:
                    db.update_book(
                        book["id"],
                        reading_days=_reading.serialize_reading_days(picked),
                    )
                    _ui.st.rerun()
                elif not picked:
                    _ui.st.caption(
                        "Pick at least one day — or **Remove** to stop reading entirely."
                    )
                if columns[1].button(
                    "Remove", key="reading_board_remove",
                    help="Stop the daily reading assignment.",
                ):
                    db.update_book(book["id"], pages_per_day=0)
                    _ui.st.rerun()
            else:
                # His board: read-only, the assignment stated plainly.
                columns[0].markdown(
                    f"📖 **Read {rate} pages · {when}** · {md(book['title'])}"
                )
    elif can_edit and book:
        with _ui.st.container(border=True):
            _ui.st.markdown("📖 **Daily reading** — not on the board")
            columns = _ui.st.columns([2, 1])
            pages = columns[0].number_input(
                "Pages per day", min_value=1, max_value=500, value=20,
                key="reading_board_add_rate",
            )
            if columns[1].button("➕ Add to board", key="reading_board_add"):
                db.update_book(book["id"], pages_per_day=int(pages))
                _ui.st.rerun()
    elif can_edit:
        _ui.st.caption(
            "📖 Add a book on **Courses → English → Books** to set up daily reading."
        )


_SERIES_DAY_PREFIX_RE = re.compile(
    r"^\s*Day\s+\d+\s*(?:of\s+\d+)?\s*[:.\-–—]?\s*", re.IGNORECASE
)


def series_day_title(item: dict[str, Any]) -> str:
    """A lesson's title with a guaranteed 'Day N/M —' prefix when it belongs to
    a generated series, derived from `series_index` so every day in the series
    is labelled and in order -- not left to whatever the model happened to title
    it (some days come back with 'Day 1' in the title, some don't). A model title
    that already leads with its own 'Day N …' is stripped first so the label
    never doubles up. Not part of a series -> the plain title."""
    metadata = item.get("metadata") or {}
    raw = (item.get("title") or "Lesson").strip()
    total = int(metadata.get("series_total") or 0)
    if total <= 1:
        return md(raw)
    number = int(metadata.get("series_index") or 0) + 1
    clean = _SERIES_DAY_PREFIX_RE.sub("", raw).strip() or raw
    return f"Day {number}/{total} — {md(clean)}"


def render_board_card(
    db: Database,
    kind: str,
    item: dict[str, Any],
    *,
    today_iso: str,
    board_week_start: _ui.date,
    interactive: bool = True,
) -> None:
    """One compact card for the unified weekly board (the "Board" tab on
    `pages/14_Mission_Control.py`) -- a title, a one-line status, and the same
    shared move control every other surface already uses, right on the
    card face instead of nested inside an expander several clicks deep.
    This is the whole point of the board: one place to see and rearrange
    every subject's stories at once, not a new way of moving them.

    `kind` is one of the six values `weekly.board_for_week` tags each
    story with -- "lesson", "life_skill", "coding_module", "choice_topic",
    "project_step", "travel_entry" -- and picks which fields/db calls this
    reads. Moving a lesson to a day is never blocked, even when that day
    already holds another lesson of the same subject: two can share a day on
    purpose (a fresh lesson plus one from a prior day still awaiting his
    revision), so there is no same-day collision guard.

    `board_week_start` is the Monday of whichever week is currently on
    screen -- every move control's `schedule` write is wrapped in
    `_board_schedule` so moving a story to a date outside that week fires
    a toast saying so, rather than the card just disappearing with no
    explanation (see that function's own docstring).

    Every card wears a colored, labeled bar naming its subject (for a lesson)
    or kind (for everything else) -- see board_card_tag. The day itself is
    already unmistakable from the big colored column header, so the card's own
    color is free to encode "what is this" instead of repeating the day.

    Each story collapses into its own expander, title as the header --
    same "closed until you need it" rhythm as the Backlog panel's own
    epic sections, so a board with a dozen cards in one column reads as a
    dozen one-line rows, not a wall of open detail.

    `interactive` (default True) is what lets the exact same card serve both
    the parent's This Week Board tab and the student's own read-only Board on
    Home. False drops every parent-only affordance -- the move control (a
    parent reschedules/backlogs, he never does) and the "View full details"
    deep links into parent management tabs -- leaving just the card's own
    content and, for a lesson, the "View full lesson" dialog, which is his to
    open too. Nothing about a card's data or layout changes, so a Tuesday
    card reads identically on either board.
    """
    with _ui.st.container(border=True):
        # A colored, labeled bar across the top -- color + word together name
        # the subject (for a lesson) or kind (for everything else) at a glance,
        # collapsed or open, whichever day it sits under. See board_card_tag.
        tag_color, tag_icon, tag_label = board_card_tag(kind, item)
        # The estimate sits on the right of the always-visible tag bar (so it
        # reads whether the card is open or collapsed) -- one glance tells you
        # how heavy this block is, and the day header below sums them.
        est = format_board_minutes(board_item_minutes(kind, item))
        _ui.st.markdown(
            f'<div style="background:{tag_color}; color:#fff; margin:-1px -1px 8px; '
            f'padding:3px 9px 3px; border-radius:2px 2px 0 0; font-size:10.5px; '
            f'font-weight:800; text-transform:uppercase; letter-spacing:.06em; '
            f'display:flex; justify-content:space-between; gap:8px;">'
            f"<span>{tag_icon} {tag_label}</span>"
            f'<span style="opacity:.9; font-weight:700;">≈{est}</span></div>',
            unsafe_allow_html=True,
        )
        if kind == "lesson":
            icon = SUBJECT_ICONS.get(item["agent"], "📘")
            done = bool((item.get("metadata") or {}).get("student_done_on"))
            marker = "✅" if done else "⬜"
            with _ui.st.expander(f"{marker} {icon} **{series_day_title(item)}**", expanded=False):
                _ui.st.caption(f"{item['agent'].replace('_', ' ').title()} agent")
                status_note = {
                    "submitted": "📤 waiting on you to review",
                    "needs_revision": "↩️ sent back — waiting on him",
                }.get(item["status"])
                if status_note:
                    _ui.st.caption(status_note)
                if interactive:
                    # Parent-only: how many written pieces to expect back from
                    # this one, so a day's review load is legible at a glance.
                    handins = hand_in_summary(item.get("payload") or {})
                    _ui.st.caption(handins if handins else "📝 No written hand-ins")
                    _render_board_estimate_editor(db, kind, item)
                if interactive and item["status"] in ("planned", "needs_revision"):
                    # No collision check on the target day: a day can hold more
                    # than one lesson of the same subject on purpose (a fresh
                    # lesson plus one from a prior day still waiting on his
                    # revision, say), so moving a subject into any day is never
                    # blocked ("just dont block me moving subject into a day.
                    # there could be two in one day.").
                    render_story_move_control(
                        key=f"board_lesson_{item['id']}",
                        active=not weekly.is_backlogged(item, today_iso),
                        scheduled_for=(item.get("metadata") or {}).get("planned_for"),
                        set_active=lambda a, lid=item["id"]: (
                            db.unhold_lesson(lid) if a else db.send_to_backlog(lid)
                        ),
                        schedule=_board_schedule(
                            lambda d, lid=item["id"]: (
                                db.reschedule_lesson(lid, d) if d else None
                            ),
                            board_week_start,
                        ),
                        delete=lambda lid=item["id"]: db.delete_lesson(lid),
                    )
                _render_board_deep_link(kind, item, db=db)

        elif kind == "life_skill":
            earned = bool(item["completed_on"])
            marker = "✅" if earned else "⬜"
            label = f"{marker} {BOARD_KIND_ICONS['life_skill']} **{md(item['title'])}**"
            with _ui.st.expander(label, expanded=False):
                _ui.st.caption(item["category"])
                _render_board_detail(item.get("description"), item.get("materials"))
                if interactive:
                    _render_board_estimate_editor(db, kind, item)
                    render_story_move_control(
                        key=f"board_ls_{item['id']}",
                        active=bool(item["active"]),
                        scheduled_for=item["scheduled_for"],
                        set_active=lambda a, sid=item["id"]: db.set_life_skill_active(sid, a),
                        schedule=_board_schedule(
                            lambda s, sid=item["id"]: db.schedule_life_skill(sid, s),
                            board_week_start,
                        ),
                    )
                _render_board_deep_link(kind)

        elif kind == "coding_module":
            earned = bool(item["completed_on"])
            marker = "✅" if earned else "⬜"
            label = f"{marker} {BOARD_KIND_ICONS['coding_module']} **{md(item['title'])}**"
            with _ui.st.expander(label, expanded=False):
                _ui.st.caption(item["category"])
                _render_board_detail(item.get("description"), item.get("materials"))
                if interactive:
                    _render_board_estimate_editor(db, kind, item)
                    render_story_move_control(
                        key=f"board_coding_{item['id']}",
                        active=bool(item["active"]),
                        scheduled_for=item["scheduled_for"],
                        set_active=lambda a, mid=item["id"]: db.set_coding_module_active(mid, a),
                        schedule=_board_schedule(
                            lambda s, mid=item["id"]: db.schedule_coding_module(mid, s),
                            board_week_start,
                        ),
                    )
                _render_board_deep_link(kind)

        elif kind == "choice_topic":
            label = (
                f"{BOARD_KIND_ICONS['choice_topic']} **{md(item['title'])}** — {item['status']}"
            )
            with _ui.st.expander(label, expanded=False):
                if item["category"]:
                    _ui.st.caption(item["category"])
                _render_board_detail(item.get("description"))
                if interactive:
                    _render_board_estimate_editor(db, kind, item)
                    if item["status"] not in ("done", "declined"):
                        render_story_move_control(
                            key=f"board_choice_{item['id']}",
                            active=bool(item["active"]),
                            scheduled_for=item["scheduled_for"],
                            set_active=lambda a, tid=item["id"]: db.set_choice_topic_active(tid, a),
                            schedule=_board_schedule(
                                lambda s, tid=item["id"]: db.schedule_choice_topic(tid, s),
                                board_week_start,
                            ),
                        )
                    else:
                        _ui.st.caption("Closed out — nothing left to move.")
                _render_board_deep_link(kind)

        elif kind == "project_step":
            done = bool(item["completed_on"])
            marker = "✅" if done else "⬜"
            label = f"{marker} {BOARD_KIND_ICONS['project_step']} **{md(item['title'])}**"
            with _ui.st.expander(label, expanded=False):
                _render_board_detail(
                    item.get("description"),
                    item.get("materials"),
                    pace=_project_step_pace(item),
                )
                if interactive:
                    _render_board_estimate_editor(db, kind, item)
                    if not done:
                        render_story_move_control(
                            key=f"board_step_{item['id']}",
                            active=bool(item["active"]),
                            scheduled_for=item["scheduled_for"],
                            set_active=lambda a, sid=item["id"]: db.set_project_step_active(sid, a),
                            schedule=_board_schedule(
                                lambda s, sid=item["id"]: db.schedule_project_step(sid, s),
                                board_week_start,
                            ),
                        )
                    else:
                        _ui.st.caption("Done — nothing left to move.")
                _render_board_deep_link(kind)

        elif kind == "travel_entry":
            title = md(item["title"]) if item["title"] else "Untitled trip"
            label = f"{BOARD_KIND_ICONS['travel_entry']} **{title}** — {item['status']}"
            with _ui.st.expander(label, expanded=False):
                where = item.get("state") or ""
                if where:
                    _ui.st.caption(f"📍 {md(where)}")
                _render_board_detail(note=_TRAVEL_BOARD_PROMPTS.get(item["status"]))
                if interactive:
                    _render_board_estimate_editor(db, kind, item)
                    if item["status"] != "completed":
                        render_story_move_control(
                            key=f"board_travel_{item['id']}",
                            active=bool(item["active"]),
                            scheduled_for=item["scheduled_for"],
                            set_active=lambda a, eid=item["id"]: db.set_travel_entry_active(eid, a),
                            schedule=_board_schedule(
                                lambda s, eid=item["id"]: db.schedule_travel_entry(eid, s),
                                board_week_start,
                            ),
                        )
                    else:
                        _ui.st.caption("Completed — nothing left to move.")
                _render_board_deep_link(kind)


# --- shared weekly board day grid: parent This Week tab + student Home board ---

# The grid is a header row plus one row per subject/kind, each its own
# st.columns(5). To keep every row's five day columns lined up under the same
# day headers -- and scrolling together on a narrow screen rather than each
# row scrolling on its own -- the horizontal scroll lives on the OUTER
# container (the one keyed "..._days_row"); every inner row is forced to the
# same fixed width (5 columns x 220px, never wrapping), so they all move as
# one when the container scrolls. Column min-width also stops a long title
# from squeezing narrower than one of its own words on a laptop screen.
_WEEK_BOARD_SCROLL_CSS = """
<style>
div[class*="st-key-"][class*="_days_row"] {
  overflow-x: auto !important;
  padding-bottom: 6px;
}
div[class*="st-key-"][class*="_days_row"] div[data-testid="stHorizontalBlock"] {
  flex-wrap: nowrap !important;
  min-width: max-content !important;
}
div[class*="st-key-"][class*="_days_row"] div[data-testid="stColumn"] {
  min-width: 220px !important;
  flex: 0 0 220px !important;
}
/* Same floor height on every card so a row of them reads as one even band
   across the week, short titles and long ones alike. */
div[class*="st-key-"][class*="_days_row"] div[data-testid="stColumn"]
  div[data-testid="stExpander"] {
  min-height: 84px;
}
</style>
"""


def render_board_days(
    db: Database,
    student: dict[str, Any],
    week_start: _ui.date,
    board: dict[str, list[tuple[str, dict[str, Any]]]],
    *,
    key_prefix: str,
    interactive: bool = True,
) -> None:
    """The five Mon-Fri day columns of the weekly sprint board, for one
    already-computed `board` (from weekly.board_for_week). Shared verbatim
    between the parent's This Week Board tab and the student's own read-only
    Board on Home -- the only difference between the two is `interactive`,
    threaded straight through to render_board_card (see its docstring). The
    caller owns week selection and, on the parent side, the Product Backlog
    panel below; this is only the day grid the two have in common.

    `key_prefix` namespaces the horizontal-scroll container so two boards
    rendered in one script run (the student's this-week and next-week views,
    say) never share a container key. The colored day pills are the same
    "Sunday Funnies" palette Home's own Week grid and the parent Board use.

    Each day is its own column and its cards pack to the top of it: a header
    row of day pills, then the five day columns, each listing only the cards
    actually planned for that day, top-first. Cards within a day still sort by
    a stable subject/kind order (`_BOARD_ROW_ORDER`, so Math sits above Science
    above English...), but a day never reserves an empty slot for a subject it
    doesn't have -- reported directly: "no matter what subject are in the day,
    the list should always stay populated at the top", so a lone project no
    longer sits marooned at the bottom of its column under blank space where
    other days' subjects would line up.
    """
    days = weekly.week_dates(week_start, include_friday=True)
    today = _ui.date.today()
    today_iso = today.isoformat()

    # day_index -> [(kind, item), ...], each day's cards sorted by the stable
    # subject/kind order so a column reads Math, Science, English... top-down.
    def _row_rank(entry: tuple[str, dict[str, Any]]) -> int:
        ident = _board_identity(entry[0], entry[1])
        return _BOARD_ROW_ORDER.index(ident) if ident in _BOARD_ROW_ORDER else len(_BOARD_ROW_ORDER)

    by_day: dict[int, list[tuple[str, dict[str, Any]]]] = {}
    for day_index, day_date in enumerate(days):
        cards = list(board[day_date.isoformat()])
        cards.sort(key=_row_rank)
        by_day[day_index] = cards
    any_cards = any(by_day.values())

    _ui.st.markdown(_WEEK_BOARD_SCROLL_CSS, unsafe_allow_html=True)
    with _ui.st.container(key=f"{key_prefix}_days_row"):
        # Header row: the day pills, aligned above their own column of cards.
        header_columns = _ui.st.columns(5)
        for index, (column, day_date) in enumerate(zip(header_columns, days)):
            color = theming.PRINTED_COMIC_WEEKDAY_COLORS[index]
            with column:
                today_tag = " · Today" if day_date == today else ""
                _ui.st.markdown(
                    f'<span style="display:inline-block; padding:2px 10px 3px; '
                    f'border-radius:3px; background:{color}; '
                    f'color:{theming.PRINTED_COMIC_PAPER}; font-weight:900; font-size:15px; '
                    f'text-transform:uppercase; letter-spacing:-.01em; '
                    f'text-shadow:1.5px 1.5px 0 rgba(0,0,0,.35);">'
                    f"{day_date.strftime('%a')}</span>",
                    unsafe_allow_html=True,
                )
                # A day's own total, so a heavy day (or a suspiciously light
                # one) reads at a glance right under its date -- the sum of
                # every card's own estimate below it (see board_item_minutes).
                day_items = board[day_date.isoformat()]
                day_minutes = sum(board_item_minutes(k, it) for k, it in day_items)
                total_note = (
                    f" · ≈{format_board_minutes(day_minutes)}" if day_items else ""
                )
                _ui.st.caption(day_date.strftime("%b %-d") + today_tag + total_note)

        if not any_cards:
            _ui.st.caption("Nothing planned this week.")

        # One row of five day columns; each column stacks its own day's cards
        # from the top, so a day is never padded out with empty slots for
        # subjects it doesn't have.
        day_columns = _ui.st.columns(5)
        for day_index, column in enumerate(day_columns):
            with column:
                for kind, item in by_day.get(day_index, []):
                    render_board_card(
                        db, kind, item,
                        today_iso=today_iso,
                        board_week_start=week_start,
                        interactive=interactive,
                    )


_BOARD_BACKLOG_SCROLL_CSS = """
<style>
div[class*="st-key-"][class*="_backlog_row_"] div[data-testid="stHorizontalBlock"] {
  overflow-x: auto !important;
  flex-wrap: nowrap !important;
  padding-bottom: 6px;
}
div[class*="st-key-"][class*="_backlog_row_"] div[data-testid="stColumn"] {
  min-width: 220px !important;
  flex: 0 0 220px !important;
}
</style>
"""


def render_board_backlog(
    db: Database,
    student: dict[str, Any],
    board: dict[str, list[tuple[str, dict[str, Any]]]],
    *,
    key_prefix: str,
    board_week_start: _ui.date,
    interactive: bool = True,
    today_iso: str | None = None,
) -> None:
    """The Product Backlog panel -- every currently-parked story, any week it
    came from, grouped by epic. Shared by the parent's Mission Control board
    (interactive: the move control on each card is how a parked story gets a
    day) and Landon's read-only Home board (interactive=False -> no move
    controls, just each card's own detail and, on a lesson, the
    View-full-lesson dialog). Reported directly: from his board he should be
    able to "view full lesson for anything thats in view there. backlog or
    assigned a date."

    `key_prefix` namespaces each epic's own scroll container so the parent
    board and the student board never share a container key.
    """
    today_iso = today_iso or _ui.date.today().isoformat()

    _ui.st.markdown(_BOARD_BACKLOG_SCROLL_CSS, unsafe_allow_html=True)
    by_epic = weekly.group_backlog_by_epic(board["backlog"])
    if not sum(len(items) for items in by_epic.values()):
        _ui.st.caption("Nothing parked.")
        return
    for epic in weekly.EPIC_ORDER:
        items = by_epic.get(epic, [])
        if not items:
            continue
        icon = EPIC_ICONS.get(epic, "📘")
        with _ui.st.expander(f"{icon} {epic} ({len(items)})", expanded=True):
            with _ui.st.container(key=f"{key_prefix}_backlog_row_{epic.replace(' ', '_')}"):
                backlog_columns = _ui.st.columns(min(len(items), 4))
                for position, (kind, item) in enumerate(items):
                    with backlog_columns[position % len(backlog_columns)]:
                        render_board_card(
                            db, kind, item,
                            today_iso=today_iso,
                            board_week_start=board_week_start,
                            interactive=interactive,
                        )


# --- per-subject week view: the same day board, scoped to one agent ------------

# Same min-width-plus-scroll fix This Week's own Board tab uses (see
# pages/14_Mission_Control.py's own _BOARD_SCROLL_CSS and the README section on
# why: st.columns has no minimum width, so five equal fractions of even a
# full-width row squeeze a long title narrower than one of its own words
# has room for on a real laptop screen). Kept as its own copy rather than
# imported from that page -- a page can't import from another page in
# this app's layout -- scoped to this function's own container keys.
_SUBJECT_WEEK_SCROLL_CSS = """
<style>
div[class*="st-key-subject_week_days_row"] div[data-testid="stHorizontalBlock"],
div[class*="st-key-subject_week_backlog_row"] div[data-testid="stHorizontalBlock"] {
  overflow-x: auto !important;
  flex-wrap: nowrap !important;
  padding-bottom: 6px;
}
div[class*="st-key-subject_week_days_row"] div[data-testid="stColumn"],
div[class*="st-key-subject_week_backlog_row"] div[data-testid="stColumn"] {
  min-width: 220px !important;
  flex: 0 0 220px !important;
}
</style>
"""


def render_subject_week_tab(db: Database, student: dict[str, Any], agent: str) -> None:
    """The same This/Next week day board This Week's own Board tab already
    gives, scoped to just this one subject's own lessons -- so a parent
    checking in on Math, say, can see, move, or open a lesson in full
    detail without a separate trip to This Week. Reported directly: "shouldn't
    I still be able to go to each core curriculum tab... and also get the
    level of detail and view into lessons, kinda like the board view of
    this week and next."

    Reuses `weekly.board_for_week` and `render_board_card` verbatim -- both
    are already kind- and agent-agnostic -- so this is purely a filtered
    view over the exact same data This Week's Board tab reads, never a
    second query or a second card renderer to keep in sync. Session-state
    keys are namespaced per agent (`f"subject_week_{agent}_..."`), so
    Math's own "week to view" and Science's don't collide with each other
    or with This Week's own `board_week_picker`, even though session_state
    is shared across every page in one browser session.
    """
    key_prefix = f"subject_week_{agent}"
    picker_key = f"{key_prefix}_picker"
    if picker_key not in _ui.st.session_state:
        _ui.st.session_state[picker_key] = _ui.date.today()

    jump_columns = _ui.st.columns([1, 1, 5])
    if jump_columns[0].button("This week", key=f"{key_prefix}_jump_this"):
        _ui.st.session_state[picker_key] = _ui.date.today()
        _ui.st.rerun()
    if jump_columns[1].button("Next week", key=f"{key_prefix}_jump_next"):
        _ui.st.session_state[picker_key] = weekly.default_plan_target()
        _ui.st.rerun()

    week_start = weekly.week_start(_ui.st.date_input("Week to view", key=picker_key))
    days = weekly.week_dates(week_start, include_friday=True)
    _ui.st.caption(f"{days[0].strftime('%b %-d')} – {days[-1].strftime('%b %-d, %Y')}")

    # Any cross-week move made from here needs the same explanation This
    # Week's own Board tab gives -- otherwise a story moved from this page
    # would just vanish from view with nothing to say where it went (see
    # _board_schedule's own docstring).
    render_board_move_notice()

    board = weekly.board_for_week(db, student, week_start)
    today_iso = _ui.date.today().isoformat()

    _ui.st.markdown(_SUBJECT_WEEK_SCROLL_CSS, unsafe_allow_html=True)
    with _ui.st.container(key=f"subject_week_days_row_{agent}"):
        columns = _ui.st.columns(5)
        for index, (column, day) in enumerate(zip(columns, days)):
            color = theming.PRINTED_COMIC_WEEKDAY_COLORS[index]
            with column:
                today_tag = " · Today" if day == _ui.date.today() else ""
                _ui.st.markdown(
                    f'<span style="display:inline-block; padding:2px 10px 3px; '
                    f'border-radius:3px; background:{color}; '
                    f'color:{theming.PRINTED_COMIC_PAPER}; font-weight:900; font-size:15px; '
                    f'text-transform:uppercase; letter-spacing:-.01em; '
                    f'text-shadow:1.5px 1.5px 0 rgba(0,0,0,.35);">'
                    f"{day.strftime('%a')}</span>",
                    unsafe_allow_html=True,
                )
                _ui.st.caption(day.strftime("%b %-d") + today_tag)
                day_items = [
                    (kind, item)
                    for kind, item in board[day.isoformat()]
                    if kind == "lesson" and item["agent"] == agent
                ]
                if not day_items:
                    _ui.st.caption("Nothing here.")
                for kind, item in day_items:
                    render_board_card(
                        db, kind, item,
                        today_iso=today_iso,
                        board_week_start=week_start,
                    )

    backlog_items = [
        (kind, item) for kind, item in board["backlog"] if kind == "lesson" and item["agent"] == agent
    ]
    if backlog_items:
        _ui.st.divider()
        _ui.st.markdown(f"**📋 Backlog** ({len(backlog_items)})")
        with _ui.st.container(key=f"subject_week_backlog_row_{agent}"):
            backlog_columns = _ui.st.columns(min(len(backlog_items), 4))
            for position, (kind, item) in enumerate(backlog_items):
                with backlog_columns[position % len(backlog_columns)]:
                    render_board_card(
                        db, kind, item,
                        today_iso=today_iso,
                        board_week_start=week_start,
                    )


