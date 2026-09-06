"""The once-a-year "Issue #1" first-day-of-school celebration.

Split out of compass.ui. Only st/date/is_parent go through `_ui`.
"""
from __future__ import annotations

from typing import Any

import compass.ui as _ui
from compass import theme as theming
from compass.storage.db import Database
from compass.ui import md


_FIRST_DAY_INK = theming.PRINTED_COMIC_INK
_FIRST_DAY_PAPER = theming.PRINTED_COMIC_COVER_PAPER
_FIRST_DAY_CARD_PAPER = theming.PRINTED_COMIC_PAPER
# Same four of the five "Sunday Funnies" week-grid colors (compass_week's own
# red, index 0, is reserved for the masthead's own shadow, below) -- just in
# blue/green/gold/purple order rather than Home's Mon-Fri order, to suit this
# feature's own blurb layout. Deliberately the same fixed printed-poster
# palette, not theme.py's own themed `Theme` tokens, same reasoning as that
# styling: a printed comic page doesn't re-theme itself for the room it's
# read in.
_FIRST_DAY_COLORS = (
    theming.PRINTED_COMIC_WEEKDAY_COLORS[2],
    theming.PRINTED_COMIC_WEEKDAY_COLORS[3],
    theming.PRINTED_COMIC_WEEKDAY_COLORS[1],
    theming.PRINTED_COMIC_WEEKDAY_COLORS[4],
)
_FIRST_DAY_WINDOW_DAYS = 14
_FIRST_DAY_CARD_CSS = f"""
<style>
div[class*="st-key-first_day_cover"] {{
  background: {_FIRST_DAY_PAPER};
  border: 4px solid {_FIRST_DAY_INK};
  border-radius: 4px;
  box-shadow: 10px 10px 0 0 {_FIRST_DAY_INK};
  padding: 28px 26px 20px;
  position: relative;
  margin: 4px 0 22px;
}}
div[class*="st-key-first_day_cover"]::before {{
  content: "";
  position: absolute;
  inset: 0;
  border-radius: 4px;
  pointer-events: none;
  opacity: .12;
  background-image: radial-gradient(circle, {_FIRST_DAY_INK} 1.6px, transparent 1.8px);
  background-size: 10px 10px;
}}
div[class*="st-key-first_day_blurb_"], div[class*="st-key-first_day_toc_"] {{
  background: {_FIRST_DAY_CARD_PAPER};
  border: 3px solid {_FIRST_DAY_INK};
  border-radius: 4px;
  padding: 10px 14px;
  box-shadow: 5px 5px 0 0 {_FIRST_DAY_INK};
  margin-bottom: 12px;
}}
</style>
"""


def render_first_day_celebration(db: Database, student: dict[str, Any]) -> bool:
    """A one-time "Issue #1" comic-cover celebration on the actual first day
    of the school year. Sampled three visual directions and picked this one
    before building -- matches the Week grid's own Sunday Funnies styling
    on purpose, same fixed printed palette rather than theme.py's tokens.

    Shown once: tracked by comparing this year's computed start date
    (school_year_bounds) against whichever start date was last celebrated,
    not by the literal calendar day, so opening the app a few days late
    still gets the moment instead of silently missing it forever -- as
    long as it's within _FIRST_DAY_WINDOW_DAYS of the real start. school_year_bounds
    always returns a start <= today (it's "the year containing today"), so
    that alone can't tell us whether the year *just* started or started
    months ago -- the window check is what actually gates this to "the
    first day" instead of "any day before it's dismissed."

    "See what's inside" flips to _render_first_day_contents -- a real table
    of contents (every Big Project, choice topic, life skill, and the travel
    log so far), tracked in st.session_state so it survives the rerun that
    button click causes. "Let's go!" dismisses from either side.

    Returns whether it actually rendered, so the caller can st.stop() --
    this is meant to be the whole page that render, not a banner stacked
    above the usual one.
    """
    year_start, _ = db.school_year_bounds()
    if db.get_setting("first_day_celebrated_start", "") == year_start:
        return False
    days_since_start = (_ui.date.today() - _ui.date.fromisoformat(year_start)).days
    if not (0 <= days_since_start < _FIRST_DAY_WINDOW_DAYS):
        return False

    if _ui.st.session_state.get("first_day_view") == "contents":
        _render_first_day_contents(db, student, year_start)
        return True

    first_name = student["name"].split()[0]
    book = db.current_book(student["id"])
    upcoming = db.upcoming_book(student["id"])
    project = db.active_big_project(student["id"])

    _ui.st.markdown(_FIRST_DAY_CARD_CSS, unsafe_allow_html=True)
    _ui.st.title("COMPASS")
    _ui.st.caption(f"A {md(student['name'])} Production")

    with _ui.st.container(key="first_day_cover"):
        _ui.st.markdown(
            f'<div style="font-weight:900; font-size:13px; letter-spacing:.05em; '
            f'color:{_FIRST_DAY_COLORS[0]};">ISSUE №1</div>',
            unsafe_allow_html=True,
        )
        _ui.st.markdown(
            f'<div style="font-weight:900; font-size:44px; line-height:.95; '
            f'color:{_FIRST_DAY_INK}; text-shadow:3px 3px 0 #e14b3a; margin:2px 0 12px;">'
            "THE FIRST DAY!</div>",
            unsafe_allow_html=True,
        )
        _ui.st.markdown(
            f"**Grade {student['grade']} starts now, {first_name} — "
            "let's see what this year's made of.**"
        )

    blurbs: list[tuple[str, str, str]] = []
    if book:
        text = f"**{md(book['title'])}**"
        if upcoming:
            text += f" — with **{md(upcoming['title'])}** queued up for the second half."
        else:
            text += " — he's mid-book, and English picks up exactly where he left off."
        blurbs.append(("THIS ISSUE:", _FIRST_DAY_COLORS[0], text))
    if project:
        next_step = next(
            (s for s in db.list_project_steps(project["id"]) if s["active"] and not s["completed_on"]),
            None,
        )
        text = f"His **{md(project['title'])}**"
        text += (
            f" — {md(next_step['title'])}, whenever he's ready to dive in."
            if next_step
            else " — every step done so far!"
        )
        blurbs.append(("GUEST-STARRING:", _FIRST_DAY_COLORS[1], text))
    blurbs.append((
        "ALSO IN THIS ISSUE:",
        _FIRST_DAY_COLORS[2],
        "**Landon's Travels** — new stamps in the journal whenever the next trip happens.",
    ))
    blurbs.append((
        "NEXT ISSUE:",
        _FIRST_DAY_COLORS[3],
        "New worlds in Science, new eras in History, and Math's next level — all waiting.",
    ))

    columns = _ui.st.columns(2)
    for index, (eyebrow, color, text) in enumerate(blurbs):
        with columns[index % 2], _ui.st.container(key=f"first_day_blurb_{index}"):
            _ui.st.markdown(
                f'<div style="font-weight:900; font-size:12px; letter-spacing:.03em; '
                f'color:{color};">{eyebrow}</div>',
                unsafe_allow_html=True,
            )
            _ui.st.markdown(text)

    peek_col, go_col = _ui.st.columns(2)
    with peek_col:
        if _ui.st.button("📖 See what's inside →", key="first_day_peek", width="stretch"):
            _ui.st.session_state["first_day_view"] = "contents"
            _ui.st.rerun()
    with go_col:
        if _ui.st.button("Let's go! →", key="first_day_go", type="primary", width="stretch"):
            db.set_setting("first_day_celebrated_start", year_start)
            _ui.st.rerun()

    return True


def _render_first_day_contents(db: Database, student: dict[str, Any], year_start: str) -> None:
    """The "table of contents" flip side of the first-day cover -- real
    detail instead of counts: a from-the-parents note first (this is his
    first year of homeschooling, and what's expected of him), then
    literally every book ever added, no status filter at all (unlike
    current_book()/upcoming_book(), which are about picking *the one* the
    English agent reads from right now -- this is "what's on his list for
    the year," a different question, and internal reading-progress
    bookkeeping shouldn't hide a book from it), every Big Project with its
    actual objective, every choice topic and life skill with its
    description, and the travel log's real entries. Two explainer
    sections (Check-In, Morning Routine) carry no per-student data at all
    -- they exist purely so he knows what those two daily habits are and
    what's expected, since the rest of Home introduces them by name
    without ever spelling that out. Choice Topics, Life Skills, and Travel
    are explicitly labeled examples -- their content is either a starter
    catalog or just whatever's logged so far, not a fixed or complete
    assignment list, and the label is there so he doesn't mistake one for
    the other. Three more explainer sections (Where Everything Lives, How
    Your Lessons Work, How The Week Comes Together) round out the same
    "orient him to the app" job as Check-In/Morning Routine -- every other
    feature here got its own explainer, but the core daily subjects and
    the app's own shape never did until now. Reachable only from the
    cover's "See what's inside" button.
    """
    student_id = student["id"]
    books = db.list_books(student_id)
    # Excludes the automatic Travel Log project (see
    # Database.ensure_travel_log_project) -- it's not a pick among these in
    # the sense this table of contents means, and it's always there from
    # day one regardless of what's actually "on deck" for the year.
    projects = [
        p for p in db.list_big_projects(student_id)
        if not p["shelved"] and p["kind"] != "travel_log"
    ]
    active_project = db.active_big_project(student_id)
    choice_topics = [
        t for t in db.list_choice_topics(student_id) if t["status"] not in ("done", "declined")
    ]
    life_skills = [s for s in db.list_life_skills(student_id) if s["active"] and not s["completed_on"]]
    travel = db.list_travel_entries(student_id)

    _ui.st.markdown(_FIRST_DAY_CARD_CSS, unsafe_allow_html=True)
    _ui.st.title("COMPASS")
    _ui.st.caption("Inside This Issue")

    if _ui.st.button("← Back to the cover", key="first_day_back"):
        _ui.st.session_state["first_day_view"] = "cover"
        _ui.st.rerun()

    sections: list[tuple[str, str, str]] = []

    sections.append((
        "💛 FROM YOUR PARENTS",
        _FIRST_DAY_COLORS[3],
        "This is your first year of homeschooling. It's a big change — and we "
        "believe in you. This is going to be a great year.\n\n"
        "Here's what we're hoping for: **take your time** with each lesson, "
        "actually **read what's given to you**, and **give it your all**. Each "
        "lesson comes with explanations, examples, and videos built in — so if "
        "something doesn't click, check there first before getting stuck.\n\n"
        "Try your hardest. Grow. That's the whole goal this year.",
    ))

    sections.append((
        "🧭 WHERE EVERYTHING LIVES",
        _FIRST_DAY_COLORS[0],
        "Down the left side: **Math, Science, English,** and **History** are "
        "your daily subjects. **Choice Topics, Life Skills,** and **Big "
        "Projects** are yours to steer. **Check-In** and **Landon's Travels** "
        "round it out. **Home** is where your day actually starts — that's "
        "where everything shows up.",
    ))

    sections.append((
        "📖 HOW YOUR LESSONS WORK",
        _FIRST_DAY_COLORS[1],
        "Math, Science, English, and History each get their own lesson, built "
        "just for you — not a worksheet pulled from a textbook. Open the "
        "subject, read through it, and work through the activities. Some come "
        "with a video, some with practice problems, some with a project. Take "
        "your time, but take it seriously — this is the real work of the "
        "year.",
    ))

    sections.append((
        "🗓️ HOW THE WEEK COMES TOGETHER",
        _FIRST_DAY_COLORS[2],
        "Lessons don't appear out of nowhere — they get planned ahead of time "
        "and show up on **Home** when it's time for them. Some weeks "
        "everything's ready to go by Monday; other times a new one lands the "
        "night before. Either way, Home is where you check each morning to "
        "see what's next.",
    ))

    if books:
        term_notes = {
            "first_half": " — first half of the year",
            "second_half": " — second half of the year",
        }
        items = []
        for book in books:
            marker = "⭐ " if book["status"] == "reading" else ""
            byline = f" by {md(book['author'])}" if book["author"] else ""
            term_note = term_notes.get(book["term"], "")
            item = f"{marker}**{md(book['title'])}**{byline}{term_note}"
            if book["ai_summary"]:
                item += f"  \n{md(book['ai_summary'])}"
            items.append(item)
        text = "\n\n".join(items)
    else:
        text = "No book started yet — the first pick is still ahead."
    sections.append(("📚 THIS YEAR'S BOOKS", _FIRST_DAY_COLORS[0], text))

    if projects:
        items = []
        for project in projects:
            is_active = bool(active_project and project["id"] == active_project["id"])
            marker = "⭐ " if is_active else ""
            item = f"{marker}**{md(project['title'])}**"
            item += f"  \n{md(project['vision'])}" if project["vision"] else "  \nNo objective set yet."
            if is_active:
                steps = db.list_project_steps(project["id"])
                next_step = next((s for s in steps if s["active"] and not s["completed_on"]), None)
                if next_step:
                    item += f"  \nNext up: {md(next_step['title'])}"
            items.append(item)
        text = "\n\n".join(items)
    else:
        text = "Nothing picked yet — Big Projects is wide open."
    sections.append(("🎬 BIG PROJECTS ON DECK", _FIRST_DAY_COLORS[1], text))

    sections.append((
        "💬 CHECK-IN",
        _FIRST_DAY_COLORS[2],
        "Once a day, pick how you're feeling and add a note if you want to. "
        "**Your parents can read it** — no secrets, just an honest heads-up on how "
        "things are going. There's no wrong answer, and no grade on it either.",
    ))

    sections.append((
        "🧘 MORNING ROUTINE",
        _FIRST_DAY_COLORS[3],
        "A few minutes of stretching, breathing, or a quick mindfulness moment to "
        "start the day feeling good, before anything else. Pick whichever one "
        "sounds good that morning.",
    ))

    if choice_topics:
        items = ["*A few examples — see Choice Topics to add whatever you're curious about.*"]
        for topic in choice_topics[:6]:
            item = f"**{md(topic['title'])}**"
            if topic["description"]:
                item += f"  \n{md(topic['description'])}"
            items.append(item)
        text = "\n\n".join(items)
    else:
        text = "Nothing on deck yet — Choice Topics is wide open."
    sections.append(("⭐ THINGS HE WANTS TO LEARN (EXAMPLES)", _FIRST_DAY_COLORS[0], text))

    if life_skills:
        items = ["*A few examples from the catalog — see Life Skills for the whole list.*"]
        for skill in life_skills[:6]:
            item = f"**{md(skill['title'])}**"
            if skill["description"]:
                item += f"  \n{md(skill['description'])}"
            items.append(item)
        text = "\n\n".join(items)
    else:
        text = "None unlocked yet."
    sections.append(("🛠️ LIFE SKILLS UNLOCKED (EXAMPLES)", _FIRST_DAY_COLORS[1], text))

    if travel:
        items = ["*A few examples so far — see Landon's Travels for the whole log.*"]
        for entry in travel[:4]:
            item = f"**{md(entry['title'] or entry['state'])}** ({md(entry['state'])})"
            if entry["story"]:
                item += f"  \n{md(entry['story'])}"
            items.append(item)
        if len(travel) > 4:
            items.append(f"...and {len(travel) - 4} more stamped so far.")
        text = "\n\n".join(items)
    else:
        text = "No stamps yet — the first trip of the year starts the log."
    sections.append(("🗺️ LANDON'S TRAVELS SO FAR (EXAMPLES)", _FIRST_DAY_COLORS[2], text))

    for index, (eyebrow, color, text) in enumerate(sections):
        with _ui.st.container(key=f"first_day_toc_{index}"):
            _ui.st.markdown(
                f'<div style="font-weight:900; font-size:12px; letter-spacing:.03em; '
                f'color:{color};">{eyebrow}</div>',
                unsafe_allow_html=True,
            )
            _ui.st.markdown(text)

    if _ui.st.button("Let's go! →", key="first_day_go_from_toc", type="primary", width="stretch"):
        db.set_setting("first_day_celebrated_start", year_start)
        _ui.st.rerun()


