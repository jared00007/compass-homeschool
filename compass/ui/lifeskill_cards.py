"""Life Skills page cards -- the catalog grid and its manager, Coding Camp
cards, and Tier-3 choice topics. All three are tabs on pages/6_Life_Skills.py.

Split out of compass.ui. Only st/date/is_parent go through `_ui`.
"""
from __future__ import annotations

import html
from typing import Any

import compass.ui as _ui
from compass import config, subjects
from compass.storage.db import Database
from compass.ui import md, render_coding_plan, render_story_move_control


LIFE_SKILL_CATEGORY_ICONS = {
    "Money": "💵",
    "Cooking": "🍳",
    "Vehicle": "🚗",
    "Communication": "💬",
    "Home": "🏠",
    "Growing Up": "🌱",
}
LIFE_SKILL_DEFAULT_ICON = "🎖️"  # any category a parent types in beyond the starter five
LIFE_SKILL_CARDS_PER_ROW = 3

# Was "Neon Pop" -- its own fixed pink/teal skin, picked before the app
# consolidated onto one theme, and never migrated when it did. Now reads
# from `compass.theme`'s own CSS custom properties (--c-border, --c-primary,
# etc.) like every other surface, so it stops clashing whenever the theme's
# palette moves. The story is always on the card; nothing here is
# click-to-reveal. A checkbox is the only thing that changes `completed_on`,
# and only the checked state changes how a card looks -- brought in via two
# *static* rules keyed off a suffix baked into each card's own container
# `key` (`..._earned` / `..._locked`) rather than one generated <style>
# block per skill, the same technique the old badge case used: a container
# `key` becomes a `st-key-<key>` class token, and `[class*=...]` matches on
# that token's substring.
_LIFE_SKILL_CARD_CSS = """
<style>
.cp-ls-tallybar {
  font-weight: 800; font-size: 15px; color: var(--c-text);
  border-bottom: 2px solid var(--c-border); padding-bottom: 10px; margin-bottom: 10px;
}
.cp-ls-tallybar .cp-ls-tally {
  font-family: var(--c-mono);
  font-size: 13px; color: var(--c-dim); font-weight: 400;
}
div[class*="st-key-ls_card_"][class*="_locked"],
div[class*="st-key-ls_card_"][class*="_earned"] {
  border-radius: var(--c-radius) !important;
  border: 1px solid var(--c-border) !important;
  padding: 14px 16px 8px !important;
  background: var(--c-panel) !important;
  box-shadow: var(--c-glow);
  position: relative;
  margin-bottom: 16px;
}
div[class*="st-key-ls_card_"][class*="_earned"] {
  border-color: var(--c-primary) !important;
  box-shadow: 0 4px 18px rgba(242, 183, 5, .25);
}
.cp-ls-seal {
  display: none; position: absolute; top: -16px; right: 14px; width: 52px; height: 52px;
  border-radius: 50%; align-items: center; justify-content: center; font-size: 19px;
  background: radial-gradient(circle at 32% 28%, var(--c-seal-highlight), var(--c-primary) 75%);
  border: 3px solid var(--c-primary);
  box-shadow: 0 0 16px rgba(242, 183, 5, .45);
  transform: rotate(12deg);
}
div[class*="st-key-ls_card_"][class*="_earned"] .cp-ls-seal { display: flex; }
.cp-ls-title { font-weight: 800; font-size: 14.5px; color: var(--c-text); padding-right: 34px; line-height: 1.3; }
.cp-ls-cat {
  font-size: 10.5px; color: var(--c-border); text-transform: uppercase; letter-spacing: .1em;
  margin: 3px 0 8px; font-family: var(--c-mono);
}
.cp-ls-story { font-size: 12.5px; line-height: 1.5; color: var(--c-text); opacity: .92; margin: 0 0 8px; }
.cp-ls-needs { font-size: 11.5px; color: var(--c-dim); margin-bottom: 2px; }
.cp-ls-needs b { color: var(--c-text); }
div[class*="st-key-ls_card_"] input[type="checkbox"] { accent-color: var(--c-primary); }
div[class*="st-key-ls_card_"] [data-testid="stWidgetLabel"] p { font-weight: 700; font-size: 12.5px; }
/* His view (render_student_life_skills): earned badges up top, then the
   skills a parent assigned him as bordered cards below. */
div[class*="st-key-ls_badge_"] {
  border-radius: var(--c-radius) !important;
  border: 2px solid var(--c-primary) !important;
  padding: 12px 10px !important;
  background: var(--c-panel) !important;
  box-shadow: 0 4px 18px rgba(242, 183, 5, .25);
  text-align: center;
  margin-bottom: 14px;
}
.cp-ls-badge-seal { font-size: 30px; line-height: 1; }
.cp-ls-badge-title { font-weight: 800; font-size: 13px; color: var(--c-text); line-height: 1.25; margin-top: 4px; }
.cp-ls-badge-cat {
  font-size: 10px; color: var(--c-border); text-transform: uppercase; letter-spacing: .08em;
  font-family: var(--c-mono); margin-top: 2px;
}
.cp-ls-badge-date { font-size: 10.5px; color: var(--c-dim); margin-top: 3px; }
div[class*="st-key-ls_assigned_"] {
  border-radius: var(--c-radius) !important;
  border: 1px solid var(--c-border) !important;
  padding: 12px 16px 6px !important;
  background: var(--c-panel) !important;
  box-shadow: var(--c-glow);
  margin-bottom: 12px;
}
.cp-ls-atitle { font-weight: 800; font-size: 14.5px; color: var(--c-text); line-height: 1.3; }
div[class*="st-key-ls_assigned_"] input[type="checkbox"] { accent-color: var(--c-primary); }
</style>
"""


def render_student_life_skills(db: Database, skills: list[dict[str, Any]]) -> None:
    """His own Life Skills surface: the badges he's already earned up top,
    then the skills a parent has assigned him below, each a bordered card in
    the same "what's on your plate" style the rest of the app uses. Not a
    checklist grid, and no move control -- choosing which skills he works on,
    and pinning them to specific days, is a parent's call on the Master list;
    his job here is to do the assigned ones and mark them done. Reported
    directly: "his activity q of assigned life task skills... badges unlocked
    up top, and below in the backlog style uniform across app, are ones i
    select for him. these can and will be assigned during the week on specific
    dates of my chosing."

    Visibility is this function's own rule (unchanged): a skill shows only if
    it's `active` (unlocked/assigned from the Master list) or already
    `completed_on` -- an earned badge stays even if a parent later re-locks it.
    Marking one done is his to do; un-marking and removing are parent actions
    on the Master list, deliberately not offered here.
    """
    visible = [s for s in skills if s["active"] or s["completed_on"]]
    if not visible:
        return
    earned = [s for s in visible if s["completed_on"]]
    assigned = [s for s in visible if not s["completed_on"]]

    _ui.st.markdown(_LIFE_SKILL_CARD_CSS, unsafe_allow_html=True)
    _ui.st.markdown(
        f'<div class="cp-ls-tallybar">🥇 <span class="cp-ls-tally">'
        f"{len(earned)} / {len(visible)} earned</span></div>",
        unsafe_allow_html=True,
    )

    if earned:
        _ui.st.markdown("**🏅 Badges earned**")
        for row_start in range(0, len(earned), LIFE_SKILL_CARDS_PER_ROW):
            row = earned[row_start : row_start + LIFE_SKILL_CARDS_PER_ROW]
            columns = _ui.st.columns(LIFE_SKILL_CARDS_PER_ROW)
            for index, skill in enumerate(row):
                icon = LIFE_SKILL_CATEGORY_ICONS.get(skill["category"], LIFE_SKILL_DEFAULT_ICON)
                with columns[index], _ui.st.container(key=f"ls_badge_{skill['id']}"):
                    _ui.st.markdown(
                        f'<div class="cp-ls-badge-seal">{icon}</div>'
                        f'<div class="cp-ls-badge-title">{html.escape(skill["title"])}</div>'
                        f'<div class="cp-ls-badge-cat">{html.escape(skill["category"])}</div>'
                        f'<div class="cp-ls-badge-date">✅ {skill["completed_on"]}</div>',
                        unsafe_allow_html=True,
                    )

    _ui.st.markdown("**📋 Assigned to you**")
    if not assigned:
        _ui.st.caption("Nothing assigned right now — your parent will add some here.")
    for skill in assigned:
        icon = LIFE_SKILL_CATEGORY_ICONS.get(skill["category"], LIFE_SKILL_DEFAULT_ICON)
        with _ui.st.container(key=f"ls_assigned_{skill['id']}"):
            when = f" · 📅 {skill['scheduled_for']}" if skill["scheduled_for"] else ""
            _ui.st.markdown(
                f'<div class="cp-ls-atitle">{icon} {html.escape(skill["title"])}</div>'
                f'<div class="cp-ls-cat">{html.escape(skill["category"])}{when}</div>',
                unsafe_allow_html=True,
            )
            if skill["description"]:
                _ui.st.markdown(
                    f'<div class="cp-ls-story">{html.escape(skill["description"])}</div>',
                    unsafe_allow_html=True,
                )
            if skill["materials"]:
                _ui.st.markdown(
                    f'<div class="cp-ls-needs"><b>You\'ll need:</b> '
                    f'{html.escape(skill["materials"])}</div>',
                    unsafe_allow_html=True,
                )
            status = skill.get("status") or config.LIFE_SKILL_ASSIGNED
            if status == config.LIFE_SKILL_SUBMITTED:
                # He's turned it in; it's a parent's call now. No badge, no
                # hours yet -- those wait on approval -- but he can pull it back
                # if he ticked it by mistake.
                _ui.st.info("⏳ Turned in — waiting on your parent to check it off.")
                if _ui.st.button(
                    "↩️ Oops — I'm not done yet", key=f"ls_unsubmit_{skill['id']}"
                ):
                    # Nothing's been logged yet (approval is what logs), so this
                    # just drops it back to 'assigned' -- reopen does exactly
                    # that and removes no hours when there are none to remove.
                    db.reopen_life_skill(skill["id"])
                    _ui.st.rerun()
            else:
                if status == config.LIFE_SKILL_NEEDS_REVISION and skill.get("feedback"):
                    _ui.st.warning(
                        f"↩️ Your parent asked for another look: {md(skill['feedback'])}"
                    )
                elif status == config.LIFE_SKILL_NEEDS_REVISION:
                    _ui.st.warning("↩️ Your parent sent this back — give it another go.")
                label = (
                    "Turn it in again" if status == config.LIFE_SKILL_NEEDS_REVISION
                    else "Mark done"
                )
                if _ui.st.button(label, key=f"ls_done_{skill['id']}"):
                    db.submit_life_skill(skill["id"])  # waits on a parent now
                    _ui.st.rerun()


def _render_life_skill_review_controls(db: Database, skill: dict[str, Any]) -> None:
    """The parent's approve / send-back / undo for one life skill, inside its
    Master-list row. Submitted -> approve it (logs the hours) or send it back
    with a note; earned -> undo it, which clears the badge and removes the hours
    approval logged (reported: "landon accidentally completed two he did not do
    but i cant figure out how to uncheck them"). A still-assigned or sent-back
    skill has nothing to act on here yet, so this stays quiet."""
    skill_status = skill.get("status") or config.LIFE_SKILL_ASSIGNED
    if skill_status == config.LIFE_SKILL_SUBMITTED:
        _ui.st.info("⏳ He marked this done — approve it or send it back for more work.")
        with _ui.st.form(f"ls_review_{skill['id']}"):
            feedback = _ui.st.text_area(
                "Feedback (shown to him if you send it back)",
                key=f"ls_feedback_{skill['id']}",
            )
            approve_col, back_col = _ui.st.columns(2)
            approve = approve_col.form_submit_button("✅ Approve", type="primary")
            send_back = back_col.form_submit_button("↩️ Send back for more work")
        if approve:
            db.complete_life_skill(skill["id"])  # sets earned + logs occ-ed hours
            _ui.st.rerun()
        elif send_back:
            db.send_life_skill_back(skill["id"], feedback)
            _ui.st.rerun()
    elif skill["completed_on"]:
        _ui.st.caption(
            "Marked done by mistake, or he needs to redo it? Undo clears the "
            "badge and takes back the hours it logged."
        )
        if _ui.st.button("↩️ Mark not done (undo)", key=f"ls_undo_{skill['id']}"):
            db.reopen_life_skill(skill["id"])
            _ui.st.rerun()
    elif skill_status == config.LIFE_SKILL_NEEDS_REVISION and skill.get("feedback"):
        _ui.st.caption(f"↩️ Sent back — you asked: {md(skill['feedback'])}")


def render_life_skill_review_card(db: Database, skill: dict[str, Any]) -> None:
    """One submitted life skill in a parent's review queue: the skill he did,
    enough detail to judge it, and the Approve / Send-back controls inline --
    so a turned-in life skill is graded in the same place and the same way as a
    turned-in lesson, no hop out to another page. Shared by Mission Control's
    review queue and reusing the same controls the master list uses, so the two
    can never drift apart."""
    with _ui.st.container(border=True):
        icon = LIFE_SKILL_CATEGORY_ICONS.get(skill["category"], LIFE_SKILL_DEFAULT_ICON)
        _ui.st.markdown(f"**{icon} {md(skill['title'])}** — *{md(skill['category'])}*")
        if skill.get("description"):
            _ui.st.caption(md(skill["description"]))
        if skill.get("materials"):
            _ui.st.caption(f"Needed: {md(skill['materials'])}")
        _render_life_skill_review_controls(db, skill)


def render_life_skill_catalog_manager(db: Database, skills: list[dict[str, Any]]) -> None:
    """The pace control: every catalog skill, active or not, one row each,
    title and status collapsed by default -- open a row for the full mission,
    materials, and credit subject before deciding whether to unlock it.
    Plain and utilitarian on purpose -- this is a parent's management view,
    not the kid-facing card grid, so it doesn't need the Neon Pop treatment
    the checklist itself has.

    An already-earned skill's checkbox still reflects and controls `active`,
    even though the checklist shows it either way (see the `active OR
    completed_on` filter at the call site) -- re-locking a finished skill
    just stops it counting toward "what's next," it never hides the badge.

    Each row also gets a date picker to assign the skill to a specific day
    -- purely a due-date, layered on top of `active`/`completed_on` rather
    than replacing either: a skill still needs unlocking to be visible at
    all, and assigning a day just adds a "do this one on Wednesday" pin on
    top of that. Left on "No specific day" (the default, and what every
    skill starts as), nothing changes from before this existed.
    """
    by_category: dict[str, list[dict[str, Any]]] = {}
    for skill in skills:
        by_category.setdefault(skill["category"], []).append(skill)

    unlocked = sum(1 for s in skills if s["active"])
    waiting = [s for s in skills if (s.get("status") or "") == config.LIFE_SKILL_SUBMITTED]
    _ui.st.caption(f"{unlocked} / {len(skills)} unlocked")
    if waiting:
        # Approving is why a parent opens this page after he's worked -- so the
        # skills waiting on that call are named up top, not left to be found by
        # opening rows one by one.
        _ui.st.warning(
            f"⏳ **{len(waiting)} waiting on your approval:** "
            + ", ".join(md(s["title"]) for s in waiting)
        )

    for category, items in by_category.items():
        _ui.st.subheader(category)
        for skill in items:
            skill_status = skill.get("status") or config.LIFE_SKILL_ASSIGNED
            if skill["completed_on"]:
                status = "✅ earned"
            elif skill_status == config.LIFE_SKILL_SUBMITTED:
                status = "⏳ waiting on you"
            elif skill_status == config.LIFE_SKILL_NEEDS_REVISION:
                status = "↩️ sent back"
            else:
                status = "🔓 unlocked" if skill["active"] else "🔒 locked"
            if skill["scheduled_for"] and not skill["completed_on"]:
                status += f" · 📅 assigned {skill['scheduled_for']}"
            with _ui.st.expander(f"{skill['title']} — {status}"):
                _render_life_skill_review_controls(db, skill)
                columns = _ui.st.columns([5, 1])
                if skill["description"]:
                    columns[0].markdown(f"**The mission:** {skill['description']}")
                if skill["materials"]:
                    columns[0].caption(f"You'll need: {skill['materials']}")
                columns[0].caption(f"Credits toward {subjects.label(skill['credit_subject'])}")
                if skill["completed_on"]:
                    columns[0].caption(f"✅ Earned {skill['completed_on']}")
                # Keyed on `skill["active"]` itself, not just the skill's id --
                # `schedule_life_skill` below can flip `active` as a side
                # effect of a *different* widget's write. A fixed key would
                # keep this checkbox's old session_state value across that
                # change (Streamlit ignores `value=` once a key already has
                # state), read the now-stale value as a fresh user click on
                # the next run, and write the lock straight back, silently
                # undoing the unlock. Folding the current value into the key
                # forces a brand-new widget -- freshly seeded from `value=`
                # -- any time `active` changes for any reason at all.
                active = columns[1].checkbox(
                    "Unlocked",
                    value=bool(skill["active"]),
                    key=f"ls_active_{skill['id']}_{skill['active']}",
                )
                if active != bool(skill["active"]):
                    db.set_life_skill_active(skill["id"], active)
                    _ui.st.rerun()

                assign = columns[0].checkbox(
                    "Assign this to a specific day",
                    value=bool(skill["scheduled_for"]),
                    key=f"ls_assign_toggle_{skill['id']}",
                )
                if assign:
                    picked = columns[0].date_input(
                        "Day",
                        value=_ui.date.fromisoformat(skill["scheduled_for"])
                        if skill["scheduled_for"]
                        else _ui.date.today(),
                        key=f"ls_assign_date_{skill['id']}",
                    )
                    if picked.isoformat() != skill["scheduled_for"]:
                        db.schedule_life_skill(skill["id"], picked.isoformat())
                        _ui.st.rerun()
                elif skill["scheduled_for"]:
                    db.schedule_life_skill(skill["id"], None)
                    _ui.st.rerun()


# --- Coding Camp: same shape as Core Life Skills, its own catalog, folded
# into the Life Skills page as a flat section (see pages/6_Life_Skills.py's
# "Coding" tab) rather than a top-level page of its own -----------------------
#
# Plain expander rows throughout, on the same reasoning
# render_life_skill_catalog_manager's own docstring gives for its half of Life
# Skills -- a v1 checklist doesn't need the Neon Pop card grid Life Skills'
# checklist has to be a real, working feature; that's a separate, later
# polish pass, not a reason to hold this back.


def render_coding_module_cards(db: Database, modules: list[dict[str, Any]], can_edit: bool) -> None:
    """The checklist itself. Takes the *full* catalog, not a pre-filtered
    list -- visibility is this function's own rule: a module shows only if
    it's `active` (unlocked from *Master list*) or already `completed_on`,
    same reasoning render_student_life_skills already gives."""
    modules = [m for m in modules if m["active"] or m["completed_on"]]
    if not modules:
        return

    by_category: dict[str, list[dict[str, Any]]] = {}
    for module in modules:
        by_category.setdefault(module["category"], []).append(module)
    done = sum(1 for m in modules if m["completed_on"])
    _ui.st.caption(f"🏆 {done} / {len(modules)} built")

    for category, items in by_category.items():
        complete = sum(1 for i in items if i["completed_on"])
        _ui.st.subheader(f"{category} — {complete}/{len(items)}")
        for module in items:
            earned = bool(module["completed_on"])
            badge = f"✅ built {module['completed_on']}" if earned else (
                f"📅 assigned {module['scheduled_for']}" if module["scheduled_for"] else ""
            )
            with _ui.st.container(border=True):
                title_col, move_col = _ui.st.columns([5, 1])
                with title_col:
                    _ui.st.markdown(f"**{md(module['title'])}**" + (f" — {badge}" if badge else ""))
                if _ui.is_parent():
                    with move_col:
                        render_story_move_control(
                            key=f"coding_{module['id']}",
                            active=bool(module["active"]),
                            scheduled_for=module["scheduled_for"],
                            set_active=lambda a, mid=module["id"]: db.set_coding_module_active(mid, a),
                            schedule=lambda s, mid=module["id"]: db.schedule_coding_module(mid, s),
                        )
                if module["description"]:
                    _ui.st.caption(md(module["description"]))
                if module["materials"]:
                    _ui.st.caption(f"You'll need: {md(module['materials'])}")
                # Visible to both of you, always -- this is the actual
                # "how to do this" content the checklist used to be missing
                # entirely, not a parent-only planning step. Generating one
                # in the first place still only happens from the Coding
                # tab's own "Plan a build guide" section (spends real API
                # cost, so parent-gated there), but once it exists, reading
                # it is exactly what he needs it for.
                plan = db.latest_coding_plan(module["student_id"], module["id"])
                if plan:
                    with _ui.st.expander("📖 How to build this", expanded=False):
                        render_coding_plan(plan["payload"])
                columns = _ui.st.columns([1, 1])
                checked = columns[0].checkbox(
                    "Mark done", value=earned, key=f"coding_done_{module['id']}"
                )
                if checked != earned:
                    db.set_coding_module_done(module["id"], checked)
                    _ui.st.rerun()
                if can_edit and columns[1].button("🗑️ Remove", key=f"coding_remove_{module['id']}"):
                    db.delete_coding_module(module["id"])
                    _ui.st.rerun()


def render_coding_module_catalog_manager(db: Database, modules: list[dict[str, Any]]) -> None:
    """The pace control -- identical shape to `render_life_skill_catalog_manager`,
    just for the Coding Camp catalog: every module, active or not, one row
    each, collapsed by default, with an unlock toggle and an optional
    assign-to-a-day date picker layered on top."""
    by_category: dict[str, list[dict[str, Any]]] = {}
    for module in modules:
        by_category.setdefault(module["category"], []).append(module)

    unlocked = sum(1 for m in modules if m["active"])
    _ui.st.caption(f"{unlocked} / {len(modules)} unlocked")

    for category, items in by_category.items():
        _ui.st.subheader(category)
        for module in items:
            status = (
                "✅ built" if module["completed_on"]
                else ("🔓 unlocked" if module["active"] else "🔒 locked")
            )
            if module["scheduled_for"] and not module["completed_on"]:
                status += f" · 📅 assigned {module['scheduled_for']}"
            with _ui.st.expander(f"{module['title']} — {status}"):
                columns = _ui.st.columns([5, 1])
                if module["description"]:
                    columns[0].markdown(f"**The idea:** {module['description']}")
                if module["materials"]:
                    columns[0].caption(f"You'll need: {module['materials']}")
                columns[0].caption(f"Credits toward {subjects.label(module['credit_subject'])}")
                if module["completed_on"]:
                    columns[0].caption(f"✅ Built {module['completed_on']}")
                # Same reasoning render_life_skill_catalog_manager's own key
                # gives: folding `active` into the key forces a fresh widget
                # any time it changes for any reason, so a stale
                # session_state value from before never writes the lock
                # straight back.
                active = columns[1].checkbox(
                    "Unlocked",
                    value=bool(module["active"]),
                    key=f"coding_active_{module['id']}_{module['active']}",
                )
                if active != bool(module["active"]):
                    db.set_coding_module_active(module["id"], active)
                    _ui.st.rerun()

                assign = columns[0].checkbox(
                    "Assign this to a specific day",
                    value=bool(module["scheduled_for"]),
                    key=f"coding_assign_toggle_{module['id']}",
                )
                if assign:
                    picked = columns[0].date_input(
                        "Day",
                        value=_ui.date.fromisoformat(module["scheduled_for"])
                        if module["scheduled_for"]
                        else _ui.date.today(),
                        key=f"coding_assign_date_{module['id']}",
                    )
                    if picked.isoformat() != module["scheduled_for"]:
                        db.schedule_coding_module(module["id"], picked.isoformat())
                        _ui.st.rerun()
                elif module["scheduled_for"]:
                    db.schedule_coding_module(module["id"], None)
                    _ui.st.rerun()


# --- choice topics: Tier 3, folded into the Life Skills page --------------------

_CHOICE_STATUS_FLOW = {
    "proposed": ("Approve", "approved"),
    "approved": ("Start", "active"),
    "active": ("Mark done", "done"),
}


def render_choice_topics_section(db: Database, student: dict[str, Any]) -> None:
    """Tier 3 -- freedom of choice. Used to be its own top-level page
    (pages/5_Choice_Topics.py); folded in here as a Life Skills tab instead,
    on the same "his to pick, light parent approval" reasoning that already
    put the two side by side -- purely a nav simplification. The underlying
    `choice_topics` table, its status flow, and its own `active` backlog
    gate are completely untouched; only where the page lives moved.
    """
    _ui.st.caption(
        "A running list he curates, with light parent approval. No prerequisite logic, no "
        "agent picking the 'optimal' next step — this is the counterweight to Tier 1's "
        "structure. Hours still count."
    )
    with _ui.st.form("add_choice", clear_on_submit=True):
        _ui.st.markdown("**Add a topic** — goes on the list for a parent to review and approve.")
        columns = _ui.st.columns([2, 1, 1])
        title = columns[0].text_input("What do you want to learn?")
        category = columns[1].text_input("Category", placeholder="e.g. coding, music, cars")
        credit_subject = columns[2].selectbox(
            "Credits toward",
            subjects.SUBJECT_KEYS,
            index=subjects.SUBJECT_KEYS.index("occupational_education"),
            format_func=subjects.label,
        )
        description = _ui.st.text_area("Anything else about it?", height=80)
        if _ui.st.form_submit_button("Add to the list", type="primary") and title.strip():
            db.add_choice_topic(
                student["id"],
                title.strip(),
                description.strip(),
                category.strip(),
                credit_subject,
            )
            _ui.st.rerun()

    topics = db.list_choice_topics(student["id"])
    if not topics:
        _ui.st.info("The list is empty. Add whatever he's into this week.")

    # Backlog vs visible to him, same gate Life Skills and lessons already
    # have, unrelated to `status` -- a proposed/approved/active topic can
    # still be parked out of his view. He never sees a backlogged topic at
    # all; a parent sees everything, with a way to move each one back and
    # forth (see the "🗄️"/"➡️" button below).
    visible_topics = (
        topics if _ui.is_parent()
        else [t for t in topics if t["active"] or t["status"] in ("done", "declined")]
    )

    for topic in visible_topics:
        with _ui.st.container(border=True):
            columns = _ui.st.columns([4, 1, 1, 1])
            badge = {
                "proposed": "🕓 proposed",
                "approved": "👍 approved",
                "active": "🔥 active",
                "done": "✅ done",
                "declined": "🚫 declined",
            }[topic["status"]]
            if not topic["active"]:
                badge += " · 🗄️ backlogged"
            category_label = f" · *{md(topic['category'])}*" if topic["category"] else ""
            columns[0].markdown(f"**{md(topic['title'])}**{category_label} — {badge}")
            if topic["description"]:
                columns[0].caption(md(topic["description"]))
            columns[0].caption(f"Credits toward {subjects.label(topic['credit_subject'])}")
            if topic["parent_note"]:
                columns[0].caption(f"Parent: {md(topic['parent_note'])}")

            # "Approve"/"Decline" are the actual review step -- he proposes,
            # a parent decides, or the "light parent approval" this page
            # promises is fiction and he's approving his own ideas. Once a
            # topic clears that step, "Start"/"Mark done" are just his own
            # progress tracking and stay open to either of you, same as a
            # Life Skills checkbox.
            awaiting_review = topic["status"] == "proposed"
            action = _CHOICE_STATUS_FLOW.get(topic["status"])
            if action and (not awaiting_review or _ui.is_parent()):
                if columns[1].button(action[0], key=f"advance_{topic['id']}"):
                    db.set_choice_status(topic["id"], action[1])
                    _ui.st.rerun()
            if awaiting_review:
                if _ui.is_parent():
                    if columns[2].button("Decline", key=f"decline_{topic['id']}"):
                        db.set_choice_status(topic["id"], "declined")
                        _ui.st.rerun()
                else:
                    columns[1].caption("Waiting on parent review")
            elif columns[2].button("Remove", key=f"remove_{topic['id']}"):
                db.delete_choice_topic(topic["id"])
                _ui.st.rerun()

            # Freedom to move a topic between Backlog and a specific day
            # whenever a parent decides -- the same shared control every
            # other story type uses. Not offered on a closed-out topic: a
            # done or declined one is already exempt from the visibility
            # filter above, so there's nothing left for this to do to it.
            if _ui.is_parent() and topic["status"] not in ("done", "declined"):
                with columns[3]:
                    render_story_move_control(
                        key=f"choice_{topic['id']}",
                        active=bool(topic["active"]),
                        scheduled_for=topic["scheduled_for"],
                        set_active=lambda a, tid=topic["id"]: db.set_choice_topic_active(tid, a),
                        schedule=lambda s, tid=topic["id"]: db.schedule_choice_topic(tid, s),
                    )

    if not _ui.is_parent():
        return

    _ui.st.divider()
    _ui.st.subheader("Log time on a choice topic")
    _ui.st.caption(
        "These hours count toward the 1,000-hour floor in full. The compliance page "
        "shows Tier 3's share against the family guideline — a warning, never a block."
    )
    # Named for eligibility-to-log, not the `active` backlog column -- a
    # backlogged topic still logs fine (a parent parking it doesn't
    # retroactively undo hours already worth logging).
    loggable = [t for t in topics if t["status"] in ("approved", "active", "done")]
    if not loggable:
        _ui.st.info("Approve a topic first and it'll show up here.")
        return

    with _ui.st.form("log_choice"):
        topic = _ui.st.selectbox(
            "Topic", loggable, format_func=lambda t: f"{t['title']} ({t['status']})"
        )
        columns = _ui.st.columns(3)
        occurred_on = columns[0].date_input("Date", value=_ui.date.today())
        minutes = columns[1].number_input(
            "Minutes", min_value=5, max_value=600, value=60, step=15
        )
        credit_subject = columns[2].selectbox(
            "Credits toward",
            subjects.SUBJECT_KEYS,
            index=subjects.SUBJECT_KEYS.index(topic["credit_subject"])
            if topic["credit_subject"] in subjects.SUBJECT_KEYS
            else subjects.SUBJECT_KEYS.index("occupational_education"),
            format_func=subjects.label,
        )
        note = _ui.st.text_input("What did he actually do?")
        if _ui.st.form_submit_button("Log hours", type="primary"):
            db.log_activity(
                student_id=student["id"],
                title=topic["title"],
                tier=config.TIER_CHOICE,
                primary_subject=credit_subject,
                minutes=int(minutes),
                subject_credits={credit_subject: int(minutes)},
                occurred_on=occurred_on.isoformat(),
                description=note,
                source="choice",
            )
            if topic["status"] == "approved":
                db.set_choice_status(topic["id"], "active")
            _ui.st.success("Logged.")
            _ui.st.rerun()


