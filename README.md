# Compass — Homeschool Curriculum Agents

Multi-agent curriculum system for a homeschooled 8th grader (age 13), built around
two constraints treated as first-class rather than afterthoughts: **Washington
homeschool compliance** and **the student's freedom of choice**.

This is a fresh, standalone build — local SQLite, a Streamlit UI, and four
subject agents on the Anthropic API.

**New here?** Read [GUIDE.md](GUIDE.md) — the parent-facing guide to how it works day to day.
**Testing before the school year?** [TESTING.md](TESTING.md) — 78 checks, in the order that finds problems soonest.

## Running it

**Daily use — no terminal required.**

- **macOS** — double-click `Compass.command` (first time: right-click → Open)
- **Windows** — double-click `run.bat`
- **Linux** — `./run.sh`

On first launch it asks for an Anthropic API key and writes it to `.env` itself
(mode 600, gitignored). Press Enter to skip — everything except lesson
generation works without one, and you'll be asked again next time.

To set the key up in advance instead, create `.env` next to the launcher
containing one line. It's a plain text file with no extension — watch for
editors silently appending `.txt`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

The launcher creates its own virtualenv, installs dependencies on first run,
loads the key, and opens the browser. Leave the window open while using it;
Ctrl-C stops it.

**On another device** (his tablet, a second laptop) — `./run.sh --lan` or
`run.bat --lan` prints an address to open from anything on the same wifi.

### macOS: "Apple could not verify Compass.command"

macOS quarantines anything downloaded through a browser, so Gatekeeper blocks the
launcher. It returns on every fresh ZIP download, because the new copy carries a
new quarantine flag.

Clear it once — **the folder path must be on the same line**:

```bash
xattr -dr com.apple.quarantine /path/to/compass-homeschool
```

After that the launcher clears the flag itself on every start, so it won't come
back even if you re-download later.

**The structural fix is to stop downloading ZIPs.** Files from `git clone` or
GitHub Desktop are never quarantined, and updates become one button instead of a
re-download plus copying `.env` and `compass.db` across.

**From a terminal**, if you prefer:

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...      # or: ant auth login
streamlit run Home.py
```

Everything except lesson generation works without an API key: the compliance
dashboard, activity log, math graph, choice topics, and life skills are all local.

### Backups

The year's logged hours are the family's documentation of instruction, and they
live in one SQLite file. Compass snapshots it **once per calendar day on first
open**, keeps every snapshot for 30 days, then keeps the first of each month
indefinitely. **Compliance → Backups** shows the state, takes one on demand,
downloads any snapshot, and restores one.

Snapshots use SQLite's backup API rather than a file copy — copying a database
with an open connection can capture a torn write. Restore writes *into* the live
connection for the same reason, and always snapshots the current state first, so
a mistaken restore is itself undoable.

Snapshots sit in `backups/` next to `compass.db` and are gitignored. **Copy that
folder somewhere off this machine** — a cloud drive or a USB stick. A daily
snapshot on the same disk does not survive losing the disk.

---

## Why four agents instead of one

Each core subject has genuinely different "what's a good next lesson" logic.
Forcing them into one prompt means compromising all of them, so the thing that
differs is factored out into a pluggable strategy and everything else is shared:

```
        system prompt template  +  tool config  +  next-topic strategy
        └──────────── shared framework ────────────┘  └── the only difference ──┘
```

| Agent | Strategy | How it picks the next lesson |
|---|---|---|
| **Math** | `graph_walk` | Walks a hand-authored 50-node prerequisite graph. A skill unlocks only when every prerequisite is *demonstrably mastered*. Ties break toward the strand that's furthest behind. |
| **Science** | `spiderweb` | Branches outward from a topic or a location. Each lesson proposes 2–4 new branches that become the pool the next lesson draws from. Uses web search to ground lessons in real local specifics. |
| **History** | `timeline` | Least-covered era on a fixed 15-era scope — *unless* the family's current location has a genuine historical connection, which takes priority. |
| **English** | `reading_tied` | Anchored to the book he is actually reading, with Leitner spaced-repetition vocabulary. Refuses to run without a current book rather than falling back to generic passages. |

Strategies are **deterministic and offline** — no model call. A strategy decides
*what* to teach; the model call decides *how*. That means the home page can show
what all four agents would do next for free, and strategy logic is unit-testable.

Science and History share a `web_nodes` table: each lesson consumes one open node
and grafts its 2–4 proposals on as children, so the frontier widens over time. The
parent can override the pick (`node_id` input), seed an unrelated thread without
disturbing the existing frontier, or dismiss a node — children are re-parented via
`ON DELETE SET NULL` rather than cascading, since a grandchild topic is still a
good lesson.

**Rule of thumb, carried through:** use the least agency that solves the problem.
Tier 3 has no agent at all. Core Life Skills has no *strategy* — the parent picks
the skill, and the model is only asked how to teach the one they picked. The
orchestrator agent was deliberately not built.

---

## Washington compliance

WA requires instruction across **11 subjects** and **1,000 instructional hours/year**
(~180 days). One arithmetic rule governs the whole dashboard:

> **Total hours** come from `activities.minutes` — real elapsed time.
> **Per-subject hours** come from `activity_subject_credits` — multi-subject credit.
> **These do not reconcile, and are not supposed to.**

A 60-minute waterfall field study can legitimately credit 60 min science, 25 min
writing, and 15 min art. That's Tier 2 folding, and it's how eleven subjects get
covered without running eleven subjects. But it's still *one hour of the student's
life*, and the 1,000-hour floor counts hours of his life. Summing credits to get a
year total would inflate the record by ~60% — the kind of error that looks fine on
a dashboard and falls apart under review. There's a test pinning this.

### Keeping the agents honest

The model returns `subject_credits` directly into the compliance record, so the
framework polices every claim before it's persisted:

- Credits outside the agent's allowed scope are **dropped** (a math lesson can't
  bill itself as art appreciation for drawing a graph)
- Credits exceeding the lesson length are **capped**
- A missing primary-subject credit is **added**
- The **secondary credits are scaled to sum to no more than the lesson length**,
  proportionally, so the whole lesson can never credit more than 2× its own duration
- Duplicates merged, unknown subjects dropped, total time reconciled to the
  activity list

Every adjustment surfaces in the UI as a warning rather than happening silently.

The secondary-sum cap came out of live testing too. Each individual claim passed —
a 60-minute history lesson credited history 60, social studies 22, reading 18,
writing 15, art 12, language 8 — but nothing was adding them up, so the lesson
billed 135 minutes of coverage for an hour of work (2.25×). Per-credit caps can't
catch this; six subjects each legitimately under 60 still sum to 360. Secondary
subjects are credited for the *segment* that earns them, segments live inside the
lesson, so their sum is bounded by the lesson. The prompt says so and
`_normalize()` enforces it.

The prompt-level rule is stricter than the code-level one, and it was tightened
after live testing caught the Math agent billing 5 minutes of *language* for
"restating the definition in his own words" and 10 minutes of *occupational
education* because a worked example used game-modding keybindings. Both are the
primary instruction described in another subject's vocabulary. The rule now is:
**name the activity and the artifact it produces, or don't claim the credit** —
and `language` was removed from what math may claim at all. Re-testing the same
skill afterward produced a single honest math credit.

---

## The three tiers

**Tier 1 — Core (agent-planned).** The four agents above. WA-mandated, structured.

**Tier 2 — Folded in.** Reading, writing, spelling, and art/music are earned as
*byproducts* of Tier 1 output, not as separate agents. Each agent declares which
secondary subjects it may claim and must justify each claim with a specific part
of the lesson.

**Tier 3 — His choice.** A list he curates with light parent approval. No
prerequisite logic, no agent picking an "optimal next step" — that's the whole
point. Hours count in full.

**Core Life Skills.** Budgeting, cooking, vehicle maintenance, communication. A
parent-maintained checklist. In practice this is where most Health and
Occupational Education coverage genuinely comes from.

Nothing here decides *what* comes next, and that's the deliberate part. A Tier 1
agent earns its strategy by answering something the parent can't answer offhand —
what he isn't ready for in a 50-node graph, which era is least covered, which
vocabulary is due. "Budgeting or changing a tire next?" is not that question; a
model picking from a checklist would be a dropdown in a costume.

What does earn a model call is the blank page *after* that decision. `compass/
agents/life_skills.py` turns a parent-chosen skill into a runnable session — order,
timing, what to demonstrate, where to stay quiet, where it can genuinely hurt him,
an observable completion bar, and honest subject credit. It is not registered in
the agent registry, because it has no next-topic strategy to register.

Two boundaries worth naming:

- The skill's credit subject is set by the parent and is always the primary, even
  when it's outside the planner's own shortlist — the starter checklist bills
  "write a polite email" as Language, and quietly rebilling that as occupational
  education would be the silent wrong answer this track exists to avoid. The
  shortlist (health, occupational education, math, reading, writing, language,
  social studies) bounds only what the *model* adds unprompted. `science` is
  absent: cooking chemistry is a Science lesson, and letting both claim it would
  double-count.
- Plans are stored in the `lessons` table so the cost page bills them like
  anything else, but they are filtered out of the student's home page. "Demonstrate
  once, then hand him the jack and stay quiet" is written to the parent.

---

## Answers to the design doc's open questions

The three questions raised for discussion before building, and what was built:

**Where does mastery/assessment data live?** Local SQLite (`compass.db`), its own
schema. One portable file, zero setup, easy to inspect and back up.

**Hand-authored or agent-inferred math graph?** Hand-authored, in
`compass/curriculum/math_graph.py`. 50 nodes covering CCSS grade 8 (8.NS, 8.EE,
8.F, 8.G, 8.SP) plus the grade 6–7 prerequisites an 8th grader must actually hold.
It's versioned data, not model output — deterministic, and defensible as a dated
scope-and-sequence you can hand to a district. Its structure is unit-tested
(no cycles, no orphans, no unreachable nodes).

**How much should Tier 3 count toward the 1,000 hours?** Counts fully, with a
configurable soft guideline (default 20%). WA mandates no split, so this is a
family policy call and the dashboard treats it as a warning, never a block. The
warning is proportional and waits for ≥10 logged hours — an absolute cap alone
would only trip around May, far too late to rebalance.

---

## Layout

```
Home.py                      Streamlit entry — dashboard
pages/                       Math, Science, English, History, Compliance,
                             Choice Topics, Life Skills, Activity Log
compass/
  agents/
    framework.py             LessonAgent, AgentSpec, generation pipeline
    credits.py               the one credit-policing implementation
    video.py                 verifying a claimed video against real search results
    quiz.py                  verifying/grading the self-graded quiz
    strategies.py            the four next-topic strategies
    llm.py                   Anthropic client, lesson JSON schema, error handling
    prompts.py               shared user-prompt assembly
    life_skills.py           teaching plans for parent-chosen skills (no strategy)
    {math,science,english,history}_agent.py
  curriculum/math_graph.py   the hand-authored 50-node graph
  compliance/dashboard.py    WA hour/subject/tier reporting
  compliance/declaration.py  Declaration of Intent due-date/filed tracking
  school_calendar.py         shared annual MM-DD date arithmetic
  costs.py                   token usage → dollars, per agent and projected
  backup.py                  daily snapshots, retention, and restore
  storage/                   SQLite schema + repository
  subjects.py                the 11 WA subjects and Tier 2 folding rules
  config.py                  statutory constants vs. editable family policy
  theme.py                   the five themes and the CSS that applies one
tests/                       251 tests, no API key required
scripts/clear_lessons.py    wipe generated lessons only; hours/mastery/profile untouched
```

`compass/` knows nothing about Streamlit — the agents, storage, and compliance
layers stay testable and reusable if the UI is ever replaced. `theme.py` is the one
exception that talks CSS, and it talks *only* CSS — no Streamlit imports, so it's
still unit-testable.

The four agent pages are deliberately thin. Everything past "which skill / which
branch / which book" runs through `ui.generate_and_log()`, one shared
generate → review → log loop. That consolidation is a correctness measure more
than a tidiness one: the redaction in `render_lesson` and the warnings from
credit and video normalization are the two things that must never be skipped on
any page, and four hand-maintained copies were four chances to forget one.

**Concurrency.** `get_db()` is `@st.cache_resource`, so one `Database` — and one
SQLite connection — is shared across every browser session, each of which
Streamlit runs on its own thread. That's safe here rather than merely convenient:
`sqlite3.threadsafety` is `3` on this build (SQLite compiled in serialized mode),
so the driver itself serializes access. Writes commit immediately and there are
no cross-request transactions to interleave, so parent and student can have the
app open at once without a lock of our own.

---

## Theming

Five themes (Comic Book, Arcade, Tech Tree, High-Vis, Blueprint), picked
independently by parent and student from a sidebar control on every page, stored
as two settings keys (`theme_parent`, `theme_student`) so neither view can
override the other's.

Streamlit reads `.streamlit/config.toml` once at process start and, as of 1.61,
declares no CSS custom properties of its own — theme values are baked directly
into generated class names, so there's no variable layer to hook a runtime picker
into. `theme.py` works around this by declaring its own custom properties and
repainting Streamlit's surfaces through `data-testid` selectors, which are the one
part of Streamlit's DOM that's stable across releases (its own test suite depends
on them). The stylesheet is injected fresh at the top of `page_setup()`, before
anything else renders, so a page never flashes the previous theme.

**The backdrop is structurally fixed, not just visually consistent.** `BACKDROP_BG`
and `BACKDROP_SIDE` are module-level constants, not fields on `Theme` — no theme
instance carries its own version to override them with, so `.stApp` and the
sidebar always render from the same two hex values regardless of which theme is
active. Every `Theme` field instead targets the *containers*: expanders, alert
banners, and `st.metric` tiles all share one set of rules (`panel`, `panel_texture`,
`border`, `glow`), so a theme only has to say what its containers look like once.
A few themes layer on a signature touch through the same generic mechanism —
Arcade's two-tone top/bottom border (`border_top`/`border_bottom`), High-Vis's
hazard-chevron top bar (`top_bar`), Comic Book's inked page-title stroke
(`heading_stroke`/`heading_fill`) — each expressed as a CSS variable that defaults
to a no-op for the other four themes, rather than per-theme conditionals in `css()`.

Two things this approach can't do, and why the shipped themes work around them
rather than fighting them:

- **Anything Streamlit renders to canvas is out of reach.** The compliance
  dataframe is a `glide-data-grid` canvas, not DOM, so CSS can only frame it —
  the cells themselves follow `config.toml`'s base theme.
- **Popovers, date pickers, and text inputs partly follow the config base too.**
  Reachable surface gets repainted; the rest falls back to whatever base
  `config.toml` set at launch. This is why `config.toml`'s base is kept in step
  with `theme.py`'s backdrop constants — a runtime picker can't change this file,
  so it has to already agree, and a mismatch here would show up as a canvas
  dataframe rendering dark against a light page around it.

**All five themes moved off a dark backdrop to a light one.** `BACKDROP_BG`/
`BACKDROP_SIDE` and every theme's `panel` went from near-black to a warm,
bright off-white — `config.toml`'s `base` moved from `"dark"` to `"light"` in
the same change, so the canvas dataframe stays in step rather than reading as
a leftover dark tile. The one thing this broke, and had to be fixed
deliberately rather than by eye: the primary-button rule used to print button
text in `--c-panel`, which was a safe pairing back when panel meant "dark" —
button text on a bright primary background was effectively dark-on-bright
either way. With panel now light on every theme, that rule would have printed
near-white text on a bright accent colour, close to unreadable. The fix is a
new `--c-button-text` token, defaulting to the theme's own dark `text`; a
WCAG contrast check (not eyeballing) found two themes where the default still
fails against their own `primary` — Arcade's magenta clears only 3.7:1 with
dark text, Blueprint's red only 2.8:1 — so those two override `button_text` to
white instead of lightening `primary` itself, which is also the page's accent
and heading colour elsewhere. All five clear 4.5:1 (AA), pinned by test rather
than left to whoever next changes a colour to notice.

One regression worth naming: an early build painted every `st.metric` value in
the theme's accent colour, which made the compliance page read as a wall of
alarms — `0 / 1000 hours` in Blueprint's red looked like a failure rather than an
ordinary September Tuesday. Metrics now render in the theme's text colour;
the accent is reserved for things that actually need the reader's action, kept
strictly apart from semantic colour (`good`/`warn`/`bad`) so a warning never
borrows the same hue as "here's your next lesson." Both rules are pinned by test.
`st.metric` itself did get a container treatment in the round that added the other
four fields — background, border, texture, and glow, same as an expander — so the
numbers on Home and Compliance read as distinct tiles rather than bare text.

---

## Model configuration

`claude-opus-5` with adaptive thinking and `effort: high`. Lessons come back as
**structured output** against a JSON schema, so the compliance-critical fields
are guaranteed well-formed rather than parsed out of prose. All four agents get
Anthropic's server-side **web search** — Science and History use most of it to
ground location-specific lessons in real facts, and all four use a little of it
to look for a real supplementary video (see below).

Server-side refusal fallbacks are enabled by default (`fallbacks: "default"`), so
a safety-classifier decline gets re-served by the recommended fallback model
rather than surfacing an error to a parent. If a key or platform doesn't support
that beta, the request transparently retries on the standard path.

### What it costs

Every generation records its own token usage, and **Compliance → What the agents
cost to run** turns that into dollars — spend to date, cost per lesson, a
per-agent breakdown, and a straight-line year projection (withheld until there
are at least 5 lessons, since a forecast off two is noise).

Measured on live generations (Opus 5, `effort: high`), not estimated:

| Agent | Cost/lesson | Time | Output tokens |
|---|---|---|---|
| Math | ~$0.17 | ~85 s | ~5,900 |
| English | ~$0.20 | ~110 s | ~7,400 |
| Science | ~$0.27 | ~3.5 min | ~7,100 + web search |
| History | ~$0.42 | ~6 min | ~9,900 + web search |

Measured before every agent could search for a supplementary video (see below).
Math and English now carry a search or two of their own — call it another cent
per lesson, usually less since one search is normally enough.

A full school year lands around **$60–120** depending on how often you generate
fresh rather than reusing a lesson across sessions.

The cost driver is **output tokens, not web search** — lessons come back far
richer than a first estimate suggests (full answer keys, per-item mastery
criteria, primary-source excerpts). Search adds only 2–3 queries per lesson.
History is the outlier on both cost and time because it does the most sourcing.

**Generation is slow — plan lessons ahead, not at the kitchen table.** History
can take six minutes. That's the model doing real research, but it is not an
interactive experience.

Rates live in `compass/costs.py` and are the only thing to edit when pricing
moves. The web-search per-query rate is the least certain number in that file;
verify it against the pricing page before trusting a projection built on it.

The biggest lever is `DEFAULT_EFFORT` in `compass/config.py` — thinking is about
half the output tokens, so `high` → `medium` cuts the year roughly 30%. Prompt
caching is *not* a meaningful lever here: output dominates the bill, and the
cached system prompt is only ~1,200 tokens.

---

## Supplementary videos

All four Tier 1 agents may propose one video per lesson — something to actually
see or hear the topic, not just read about it. Math and English didn't have web
search at all before this; they now get a small budget (`max_web_searches: 2`)
for it. Science and History keep their existing 6-query budget, which now covers
both location grounding and the video.

**The risk this exists to manage:** asked to "find a video," a model will, if
trusted at face value, return a plausible title, channel, and URL that correspond
to nothing real. A dead or wrong link is a minor annoyance; a fabricated one that
happens to resolve to something unrelated is worse than no suggestion. So a
claimed video is accepted only if all three hold:

1. **Its URL matches a real search result from this generation.** `llm.py`
   collects every URL a `web_search_tool_result` block actually returned;
   `compass/agents/video.py` accepts nothing else. Matching is by extracted
   YouTube video ID rather than exact string equality — a model told to "copy
   the URL exactly" still reliably adds a timestamp, drops `www.`, or swaps
   `http` for `https`, none of which changes which video it is, and an exact
   match would reject real, search-found videos over punctuation. A title,
   channel, and URL that sound right but trace back to no real search result at
   all are indistinguishable from a confident fabrication, so they're rejected
   the same way — reset to "no video found," never surfaced half-verified.
2. **That URL is on a small allowlist of hosts** (`youtube.com`, `youtu.be`,
   `m.youtube.com`) **a parent already knows how to preview.** A real,
   search-verified link to an unknown site still isn't something this app will
   vouch for. Widening this list is a deliberate choice for a family to make, not
   a default.
3. **Its claimed channel is on that subject's own vetted list**
   (`TRUSTED_CHANNELS` in `video.py`) — Math gets Khan Academy, Math Antics, and
   Mashup Math; Science adds Crash Course, SciShow, Bozeman Science, and National
   Geographic; English and History add Crash Course and TED-Ed. This check is
   honest about its limits: Anthropic's search results hand back a title and URL,
   not a verified uploader, so `channel` is still the model's own claim, not
   something independently confirmed. What actually narrows the risk is upstream
   — the prompt directs the model to search *by channel name* ("Khan Academy
   two-step equations," not just "two-step equations"), so a real search
   naturally surfaces that channel's own uploads — and this check closes the
   loop by rejecting anything claiming a channel outside the list, real video or
   not. A cryptographic guarantee here (looking up the video's actual channel ID
   via the YouTube Data API) would mean a new API key, quota, and dependency for
   a family homeschool app; this project has consistently chosen the least
   infrastructure that solves the problem, so that's deliberately skipped unless
   a family wants it.

Every rejection surfaces as a warning, the same pattern as credit normalization —
a silent downgrade would be worse than not checking at all.

**Rendered to both parent and student.** Unlike the answer key, a verified video
is meant for him directly — there's nothing left to redact once it's passed both
checks above. The parent's copy carries one extra line the student's doesn't:
Compass verifies the video itself, not what YouTube recommends once it ends.

## The in-app quiz

Every lesson, from every agent, ends with `quiz`: three to five multiple-choice
questions the student takes himself and gets graded on the spot, alongside the
existing free-text `assessment` the parent administers. Two things had to be true
for this to be worth building rather than just another free-text field: the model's
questions had to be structurally trustworthy before they reach a grading UI, and
the correct answer had to be genuinely unreachable before he answers — not just
hidden behind CSS.

**Structural verification (`compass/agents/quiz.py`).** The JSON schema enforces
types, not invariants across fields — nothing stops the model from returning
`correct_index: 4` for a four-choice question, or three choices instead of four.
Either one wouldn't just look wrong, it would silently break grading: a correct
answer that can never be selected. `verify_quiz()` drops any question that fails a
structural check (question text, exactly four non-empty choices, `correct_index`
a genuine `int` in range — explicitly rejecting `bool`, which is a subtype of `int`
in Python) rather than trusting the shape, the same anti-hallucination posture
`credits.py` and `video.py` already take toward the rest of a lesson's claims.

**The correct answer is never sent to the browser before he submits — architecturally,
not by convention.** Streamlit reruns the whole page from the server on every
interaction; `ui.render_quiz()` simply never reads `correct_index` into a widget or
a string until *after* `st.form_submit_button` has fired. There's no answer for a
browser dev-tools inspection to find early, because the ungraded branch of the code
never puts it on the page — the same reasoning `render_lesson`'s parent/student
redaction already relies on. A `user-select: none` rule on the quiz's container
(`st.container(key=...)`, a CSS class Streamlit itself provides) adds a second,
much weaker layer against copying a question out to search for it — real friction,
the same honestly-caveated kind as the PIN, not something that stops a determined
kid with dev tools open.

**A pass on Math auto-records mastery.** `render_quiz()` reads `metadata["skill_id"]`
— the same key `graph_walk`'s proposal already writes for every Math lesson — and on
a passing score calls the same `db.set_mastery(..., "mastered", ...)` the parent's
**Record mastery** form calls by hand. A failing score does nothing to the mastery
record either way, so a bad day never un-masters something already recorded. Science,
English, and History have no analogous mastery concept to hook into, so their quizzes
grade and show a score without a side effect — a real check with no mechanism behind
it yet, rather than force-fitting one. The pass bar (`quiz_pass_percent`, default 80)
is a family policy setting, the same category as the Tier 3 guideline percent.

## The student's own "I'm done for today"

`student_lesson_view()` in `compass/ui.py` shows exactly one "current" lesson per
subject and a button: **✅ I'm done for today**. Clicking it calls
`db.mark_student_done()`, which stamps `metadata.student_done_on` (via the same
`json_set` pattern `record_quiz_result` already used — no schema migration needed,
since `metadata` is already a JSON column). The lesson then drops out of "current"
and into a **Past lessons** picker below it — a selectbox, not a list of expanders,
because `render_lesson` already opens its own expanders for activities and video, and
Streamlit doesn't allow nesting one expander inside another.

**This is deliberately a second, separate signal from `status`.** `status` (planned →
completed) only changes when the parent logs actual hours through `log_lesson_form`
— that's the compliance-relevant fact, tied to real minutes and subject credits.
`student_done_on` is just "he says he's finished," and touches nothing else: not
hours, not credits, not the compliance record. A lesson can be `student_done_on`-set
and still `status: "planned"` indefinitely if the parent hasn't logged it yet — the
two states aren't supposed to reconcile, same as the total/per-subject hours split
elsewhere in this app. Activity Log's "Generated lessons" tab surfaces that gap as a
small note (`🎓 He marked this done on ... — not logged yet.`) rather than letting it
pass silently.

A skipped lesson (`status: "skipped"`) is excluded from "current" outright — there's
no reason to hand him a lesson the parent already called off.

## Printing a lesson

There are two places to get a lesson as a `.docx` (`compass/export.py`):

1. **Right after generating one** — a **Download as Word doc** button sits next to
   the on-screen render in the shared `generate_and_log` loop (`compass/ui.py`). This
   only exists for the lesson currently held in that page's session state, so it's
   gone the moment you navigate away or reload — Streamlit session state doesn't
   survive either.
2. **Activity Log → Generated lessons** (`pages/8_Activity_Log.py`) — every lesson
   ever generated, loaded from the database rather than session state, each with its
   own download button. This is the durable one: it's there whether the lesson was
   generated this session or three weeks ago.

Both produce the same `.docx`, containing everything the parent view shows —
activities, materials, assessment, mastery criteria, the quiz answer key, subject
credits — because reading an assessment off a laptop screen while scoring a paper
worksheet is exactly the friction this exists to remove.

Both are deliberately parent-only exports: `generate_and_log` and every Tier 1 page
gate their caller behind `is_parent()`, and the Activity Log page gates its entire
body behind `parent_only()` at the top, so nothing in `export.py` re-checks who's
asking — same trust boundary as the on-screen assessment it mirrors, not a new one.

**The `data` passed to `st.download_button` is a callable (`functools.partial`), not
already-built bytes.** The Activity Log page can list up to 50 lessons at once, and
every widget interaction anywhere on that page triggers a full Streamlit rerun —
building all 50 `.docx` files (~50ms each) on every keystroke elsewhere on the page
would be real, needless lag. A callable defers that work until the specific button is
actually clicked. This is why `requirements.txt`'s streamlit floor is `>=1.52.0`
rather than the previous `>=1.40.0` — that's the version deferred `data` callables
shipped in, and the app has no other reason to require anything newer.

`python-docx` is a pure-Python dependency (its one transitive dependency, `lxml`,
ships prebuilt wheels for macOS/Windows/Linux), so this doesn't add anything to the
"needs a terminal and a build toolchain" side of the ledger the launcher scripts are
built to avoid.

### The launcher bug this surfaced

Adding `python-docx` exposed a real bug in `run.sh`/`run.bat`: dependency install was
gated on `import streamlit, anthropic` succeeding, so a machine with an existing
`.venv` from before this change never got the new package — `ModuleNotFoundError` on
launch. That check would have silently skipped *any* dependency added after someone's
first setup, not just this one. Fixed by always running
`pip install -r requirements.txt` on every launch rather than guessing from two
hardcoded package names; already-satisfied installs are fast, so there's no real cost
to just asking every time.

## Writing for a 13-year-old

The prompt splits student-facing content from parent-facing content structurally
(`compass/ui.py`'s `render_lesson` gates `assessment`, `parent_notes`, and
`subject_credits` behind `if parent:`; everything else renders unconditionally), but
until this pass it never told the model *how* to write for the audience that split
implies. `title`, `overview`, `learning_objectives`, `activities`, `materials`, the
video's `why`, and every `quiz` question are all rendered to the student exactly as
written, so `BASE_SYSTEM_PROMPT`'s new "Writing for a 13-year-old" section asks for
short sentences, plain words over precise-sounding ones, second person, and a casual,
direct voice — and reuses `{interests}` a second time in the prompt so examples can
draw on what he's actually into, not just topic selection.

**Fixed alongside it:** the schema and prompt both used to describe `overview` as
written *for the parent* ("Two or three sentences for the parent: what this covers and
why now"), which was simply wrong — `render_lesson` has never gated `overview` behind
`if parent:`, so it was reaching the student the whole time in an adult register with
nothing asking it not to be. That's now corrected in both the JSON schema description
and the prompt, pinned by a regression test that fails if the old phrasing comes back.

## Declaration of Intent and school-year countdowns

Washington also requires a once-a-year filing with the local school district (RCW
28A.200.010) — a paperwork deadline that has nothing to do with instructional hours
or subject coverage, which is exactly why `compass/compliance/declaration.py` is a
separate module from `dashboard.py` rather than another field on `ComplianceReport`.
A family perfectly on pace for 1,000 hours can still be about to miss this deadline.

**Getting "overdue" right took a second pass.** The obvious implementation — roll the
due date forward to next year the instant it passes, the same way the first-day-of-
school countdown works — is wrong here specifically: a missed filing would silently
turn into a calm 350-day countdown instead of staying a visible problem. So
`declaration_status()` computes the deadline as *this calendar year's* occurrence of
the configured date, full stop — no early rollover. That single date then does three
things depending on state: still in the future → a countdown; passed and unfiled →
stays flagged overdue, for the rest of that year; passed and filed → reads as done.
The transition to next year's date happens automatically once the calendar itself
turns over, not on any special-cased timer. `compass/school_calendar.py` holds the
shared MM-DD arithmetic (`date_in_year`, `next_annual_date`) both this and the
school-year-start countdown are built on.

**The filing link is never guessed.** Washington has roughly 300 school districts,
each running its own process — there's no single state URL Compass could point to
correctly, so `declaration_url` starts empty and is only ever whatever the family
pastes into Compliance → Declaration of Intent themselves.

Shown on the Home page: the parent gets the Declaration banner (with a **Mark as
filed** button that writes straight to a small `declarations_of_intent` table,
keyed by student and due date so each year gets its own row) and, in both parent and
student view, a plain countdown to the first day of school.

## Tests

```bash
python -m pytest tests/ -q      # 251 tests, ~5s, no API key needed
```

Coverage focuses where being wrong is expensive: the math graph's structure, the
compliance arithmetic, the credit-normalization guardrails, and all four
strategies' selection logic.

## Not built, on purpose

The orchestrator agent that balances the day across subjects. The design doc says
to build it only if juggling four agents' daily hour allocation actually gets
unwieldy — that's a decision to make with a term of real usage data, not now.
