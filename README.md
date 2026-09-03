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
`run.bat --lan` prints an address to open from anything on the same wifi. Over
Tailscale instead of shared wifi, use that machine's Tailscale address on port
8501 rather than the printed one.

For his own device, turn that address into a real launcher rather than
something he has to type: in Edge or Chrome, open the address, then **⋯ menu →
Apps → Install this site as an app**. That gives him a taskbar/desktop icon
that opens straight to Compass in its own window — no address bar, no tabs.

### Starting automatically (macOS)

`./run.sh --lan` only runs while that terminal window stays open. To skip that
step entirely — Compass starts itself at login and restarts itself if it ever
crashes — run this once on whichever Mac holds `compass.db`:

```bash
./scripts/install-autostart.sh
```

Installs a `launchd` background service (`~/Library/LaunchAgents/com.compass.homeschool.plist`).
Logs land in `~/Library/Logs/Compass/` if anything needs debugging. Once
installed, **don't also start Compass by hand** — the service already holds
port 8501, and a second copy will just fail to bind it.

Check it's running: `launchctl list | grep compass`.
Undo it: `./scripts/uninstall-autostart.sh`.

### Updating

Whenever there's a new version to pull, run this instead of the manual
`cd` / `git pull` / clear caches / restart sequence — it's easy to get a step
wrong (wrong directory, a stale `__pycache__`, restarting the wrong way):

```bash
./scripts/update.sh
```

Refuses to touch anything if there are uncommitted local changes it doesn't
recognize. Otherwise: pulls, clears cached Python bytecode, restarts Compass
the right way for however it's actually running (through `launchctl` if
`install-autostart.sh` is set up, or tells you to run `./run.sh --lan`
yourself if you start it by hand each time), then checks the app actually
came back up before calling it done.

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

#### Syncing backups to Google Drive automatically

Rather than remembering to copy `backups/` anywhere, point it *at* a cloud
drive once and every automatic snapshot syncs itself from then on. With
Google Drive for desktop installed and signed in:

```bash
./scripts/setup-cloud-backups.sh
```

It finds Google Drive's local synced folder, moves any snapshots already in
`backups/` into a `Compass Backups` folder there, and replaces `backups/`
with a symlink pointing at it. Compass itself needs no changes — it already
just writes wherever `backups/` happens to point. Safe to re-run; it no-ops
if already set up, and if more than one Google account is signed in it lists
them and asks which to use.

This only syncs the point-in-time snapshots, never the live `compass.db` —
a cloud sync tool can corrupt a database file it catches mid-write, but a
finished snapshot is never written to again once it exists, so it's safe.

For real disaster-proofing, follow the **3-2-1 rule**: 3 copies of the data,
on 2 different kinds of storage, with 1 kept offsite. Google Drive syncing
covers the offsite cloud copy; periodically (quarterly, or at least at the
end of each school year) also copy `backups/` to a USB drive and store that
somewhere physically separate from the house.

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
pages/                       Math, Science, English, History, Choice Topics,
                             Life Skills, Check-In, Landon's Travels,
                             Mission Control (Review · Board · Plan · Backlog
                             · Record), Compliance, Student Profile
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
  grades.py                  pure grade arithmetic (retry weighting, weights)
  gradebook.py               reading the database into subject grades
  backup.py                  daily snapshots, retention, and restore
  storage/                   SQLite schema + repository
  subjects.py                the 11 WA subjects and Tier 2 folding rules
  config.py                  statutory constants vs. editable family policy
  theme.py                   the one fixed theme and the CSS that applies it
  fun_facts.py               fact-of-the-day for the student home view
  national_parks.py          the 63 parks + real state borders for Landon's Travels
tests/                       913 tests, no API key required
scripts/clear_lessons.py    wipe generated lessons only; hours/mastery/profile untouched
scripts/new_school_year_reset.py  wipe a finished school year's data, see below
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
Streamlit runs on its own thread. `sqlite3.threadsafety` being `3` on this build
(SQLite compiled in serialized mode) keeps any *individual* statement safe across
threads, but it doesn't cover the handful of methods that read a lesson's whole
`metadata` blob, mutate the dict in Python, and write it all back
(`set_writing_review`, `send_lesson_back`, `save_writing_response`,
`save_reading_check`, `save_writing_ai_review`, `record_assessment`,
`set_activity_collapsed`) — two of those interleaving on a parent's bounce and a
student's save landing at the same moment could have one silently clobber the
other. Those seven take `Database`'s own `self._lock` (a plain `threading.RLock`)
for the whole read-modify-write span, which is enough on its own precisely
because there's exactly one process and one shared connection — no
cross-process version column or retry logic needed. Every other write here is a
single atomic SQL statement (`json_set` included), so it was never at risk and
needs no lock.

---

## Theming

One fixed theme (Comic Book), the same for both roles, everywhere in the app.
This used to be five swappable themes with a per-person picker in the sidebar —
retired on request in favor of one consistent look nobody has to think about,
after previewing all five live and picking Comic Book. `theme.py` kept the same
`Theme` dataclass and CSS-generation mechanism; what's gone is the `THEMES` dict,
the settings-backed lookup (`theme_parent`/`theme_student`), and the sidebar
control. `THEME` is now the whole decision — one module-level instance, no
lookup.

Streamlit reads `.streamlit/config.toml` once at process start and, as of 1.61,
declares no CSS custom properties of its own — theme values are baked directly
into generated class names, so there's no variable layer to hook into. `theme.py`
works around this by declaring its own custom properties and repainting
Streamlit's surfaces through `data-testid` selectors, which are the one part of
Streamlit's DOM that's stable across releases (its own test suite depends on
them). The stylesheet is injected fresh at the top of `page_setup()`, before
anything else renders, so a page never flashes unstyled.

**The backdrop is structurally fixed, not just visually consistent.** `BACKDROP_BG`
and `BACKDROP_SIDE` are module-level constants, not fields on `Theme` — `THEME`
carries no version of its own to override them with, so `.stApp` and the sidebar
always render from the same two hex values. Every `Theme` field instead targets
the *containers*: expanders, alert banners, and `st.metric` tiles all share one
set of rules (`panel`, `panel_texture`, `border`, `glow`), so the theme only has
to say what its containers look like once. Comic Book's signature touch — the
inked page-title stroke (`heading_stroke`/`heading_fill`) — goes through the same
generic mechanism as the other, now-unused fields (`border_top`/`border_bottom`,
`top_bar`) that the original five themes used for their own signature touches;
those fields stayed on `Theme` since they're still real CSS-variable plumbing,
just no-ops for Comic Book's own values.

Two things this approach can't do, and why the shipped theme works around them
rather than fighting them:

- **Anything Streamlit renders to canvas is out of reach.** The compliance
  dataframe is a `glide-data-grid` canvas, not DOM, so CSS can only frame it —
  the cells themselves follow `config.toml`'s base theme.
- **Popovers, date pickers, and text inputs partly follow the config base too.**
  Reachable surface gets repainted; the rest falls back to whatever base
  `config.toml` set at launch. This is why `config.toml`'s base is kept in step
  with `theme.py`'s backdrop constants — the file can't change without a relaunch,
  so it has to already agree, and a mismatch here would show up as a canvas
  dataframe rendering dark against a light page around it.

**The backdrop is light**, and the primary-button text pairing is checked, not
eyeballed: a `--c-button-text` token defaults to the theme's own dark `text`,
verified against `primary` with a real WCAG contrast calculation (4.5:1, AA) —
pinned by test rather than left to whoever next changes a colour to notice.

One regression worth naming: an early build painted every `st.metric` value in
the accent colour, which made the compliance page read as a wall of alarms —
`0 / 1000 hours` in gold looked like a failure rather than an ordinary September
Tuesday. Metrics now render in the theme's text colour; the accent is reserved
for things that actually need the reader's action, kept strictly apart from
semantic colour (`good`/`warn`/`bad`) so a warning never borrows the same hue as
"here's your next lesson." Both rules are pinned by test. `st.metric` itself gets
the same container treatment as an expander — background, border, texture, and
glow — so the numbers on Home and Compliance read as distinct tiles rather than
bare text.

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

**A fully-mastered pass on Math auto-records mastery.** `render_quiz()` reads
`metadata["skill_id"]` — the same key `graph_walk`'s proposal already writes for every
Math lesson — and on a score meeting `math_mastery_percent` (default 100, deliberately
stricter than the general pass bar) calls the same `db.set_mastery(..., "mastered", ...)`
the parent's **Record mastery** form calls by hand. Passing (`quiz_pass_percent`, default
80) and being fully mastered are tracked as two separate thresholds on purpose: a passing
score under the mastery bar still shows real, encouraging feedback ("nice work, that's a
pass") plus a nudge to retry for full mastery, rather than either punishing an imperfect-
but-solid score or silently treating it as good enough to unlock the next skill. A score
under the pass bar does nothing to the mastery record either way, so a bad day never
un-masters something already recorded. Science, English, and History have no analogous
mastery concept to hook into, so their quizzes grade and show a score without a side
effect — a real check with no mechanism behind it yet, rather than force-fitting one.
Both thresholds are family policy settings, the same category as the Tier 3 guideline
percent.

## Weekly batch planning, and skipping a day for a holiday

`pages/14_This_Week.py`'s **Plan next week** tab is what keeps Monday through Thursday
sitting ready instead of a parent generating each lesson the morning of. It targets a
week (`weekly.week_start()` snaps whatever's picked to that week's Monday), then plans
each of the four subjects independently: Science/English/History get four fresh topics
via their own strategies, Math gets one skill framed across the week (`weekly.
math_stage_note`, below) since its next skill only unlocks once a real assessment gets
graded and batch-generating four calls in one sitting would just hand back the same skill
four times. Only days that don't have a lesson yet are filled in -- regenerating a
specific day on purpose is a separate button, right on that day's own card.

**Which days actually get planned is a checkbox row, not always fixed at four.** A
holiday can land on any weekday -- Labor Day's a Monday, Thanksgiving's a Thursday --
so this is Monday/Tuesday/Wednesday/Thursday checkboxes (all on by default), not a bare
day-count: a count alone can't tell "skip the first day" from "skip the last day," and a
Monday holiday needs exactly the former. Unchecking a day removes it from every
subject's target list for that pass -- shared across all four, not a separate control
per subject, since a holiday affects the whole household, not one subject's schedule.
The picker isn't persisted: it's read fresh each time the page loads and only shapes
that one generation click, the same way the Monday topic-seed text boxes already work.
A day that's deliberately left unplanned just never shows a lesson for it (same as a
weekend already does on the Week grid) -- nothing elsewhere assumes exactly four lessons
exist, so there's no separate "this day is a holiday" flag to keep in sync.

**Friday's a fifth option in that same checkbox row, unchecked by default.** Reported
directly: unchecking a holiday Monday only leaves three lesson days that week, with no
way to make up the fourth. `weekly.week_dates(start, include_friday=True)` appends
Friday to the four dates the picker already builds from; the checkbox itself defaults
to unchecked (`day.weekday() != 4`) since Friday's still the review/light day the rest
of the app assumes -- checking it in for one particular week is an explicit opt-in, not
a new default. Everything downstream already worked off `planned_for` dates rather than
a fixed Monday-Thursday assumption (`plan_day`/`plan_missing_days`, `today_subject_status`,
Home's "ready for you" roster), so a Friday lesson flows through the same gate as any
other day's -- the two places that did still assume four fixed columns needed a matching
`include_friday=True`: Activity Log's "This week's plan" board (else a Friday lesson fell
into the "scheduled for a different week" bucket, wrongly, since Friday was never one of
its column keys) and Home's week grid, which used to render *only* the Big
Project/Travel Journal light-day fallback for Friday regardless of what was actually
`planned_for` that date -- a Friday lesson now renders alongside that fallback rather
than being silently swallowed by it.

**`weekly.math_stage_note(index, total)` generalizes the parent-facing note Math
attaches to each day** ("day 2 of 4 on this same skill," escalating toward the graded
assessment on the last day) to however many days actually got checked. The ordinary
four-day case returns `MATH_STAGE_NOTES` verbatim, since its two middle days read
differently from each other ("escalate slightly" vs. "more practice, escalating
further") in a way a generic formula would flatten into one repeated sentence; only an
actually-shortened week (a holiday) falls through to the generic three-tier version --
no note on day one, escalating practice through the middle, assessment-weighted on the
last day (which can be the same day as the first, on a one-day week).

**A holiday skipped this way doesn't cost him his streak, either.** `weekly.
current_streak`/`best_streak` (see "Days in a row" below) used to read any weekday with
nothing marked done as a miss, full stop -- indistinguishable from a day he actually had
work waiting and didn't do. Two new `Database` methods give them enough to tell the two
apart without a stored "this day is a holiday" flag: `planned_days` (every date that ever
got a lesson, any subject) and `planned_weeks` (every Monday that ever got a batch-planning
pass at all). A weekday counts as a deliberate day off -- skipped, same as a weekend,
neither breaking the streak nor extending it -- only when its *week* was batch-planned but
that specific day wasn't; a day that genuinely had work waiting and got nothing done still
breaks the streak exactly as before. Both sets are empty forever for a family that never
touches This Week and generates every lesson on demand instead, which is what keeps the
streak meaning what it always did for them -- the two checks only ever start forgiving
anything once there's a real batch-planned week to compare a gap against.

## Comic panels: single column, and collapsing a card when it's done

The activity panels on a lesson (see GUIDE.md's "Comic Panels" section for the redesign
this replaced) used to pair two activities per row. That looked noisy in practice --
a video or worked example sitting next to a two-line instruction produced two very
different card heights squeezed into the same row. Activities now render one to a row,
full width, so each one takes exactly the room it needs.

In student view only, every panel -- including the writing one, right alongside its own
text box -- gets a **"✅ Mark this one done"** button that collapses it down to just its
title bar and a **"↩️ Done — tap to reopen"** button. `Database.set_activity_collapsed`
stores the collapsed indices in the lesson's own metadata, so a lesson worked across two
sittings doesn't reopen every card he already tucked away. This is deliberately just a
manual, personal reading convenience, not a real completion signal -- the same reason the
progress dots above the panels don't treat "collapsed" as "done" either -- so parent view
always shows every panel in full regardless of what's collapsed. A parent checking or
approving a lesson needs to see everything, not whatever he happened to fold away for
himself while working through it.

## Days in a row: quiet counting, comic milestones

`render_streak` (`compass/ui.py`) is the streak shown on his Home page. The old
copy appended " — your best yet!" whenever `streak >= best`, which sounds like a
one-time honor but isn't: a streak IS the record every single day once it's ever
been the longest he's had, so that condition is true on nearly every day of an
ongoing run. In practice it printed the same "your best yet!" on day 4, day 5,
day 6 of the same streak — he called it out as lame, and it was: a superlative
that fires constantly stops meaning anything.

Ordinary days now read as a plain count — `"🔥 4 school days in a row"`, with
`· best: N` appended only when the current run hasn't caught up to a past one.
Landing on a milestone (`_STREAK_MILESTONES = (3, 5, 10, 20, 30, 50)`) swaps
that line for a small comic-style callout instead — same printed-poster
palette (`theming.
PRINTED_COMIC_INK`/`_PAPER`/`_WEEKDAY_COLORS`) as the Week grid and the
first-day cover, a bordered card with a hard offset shadow and a slight tilt,
picked over balloons/snow after sampling a few directions since it's the one
that matches the rest of the app's printed-comic look. It's gated on
`today_done and streak in _STREAK_MILESTONES` — not just the count sitting on a
milestone number — so reopening the app later in the week, still at that same
milestone count from a day he already saw it, doesn't replay the celebration.

## Home page: nav buttons instead of tabs, lessons that link out

His Home page used to be `st.tabs()` (Today / This Week / Upcoming Week / Grades)
with a full-width streak banner and fun fact stacked above it, and each subject's
lesson rendered inline, in full, right there on the tab. He said it felt busy and
asked for samples before anything changed; three directions were mocked up and he
picked "nav first" — buttons at the top instead of tabs, links out to each
lesson's own page instead of the content embedded here.

**Why buttons, not `st.tabs()`.** The picked design puts shared header content —
greeting, streak, fun fact — *between* the nav row and whichever view's body is
showing. `st.tabs()` can't do that: content rendered after the call but outside a
`with tab:` block lands below the entire tab widget (bar and every panel), not
between the bar and the active one. So `active_view` is a plain
`st.session_state["home_view"]` switch instead, with a row of four `st.button`s
(📅 Today, 🗓️ This Week, 🔜 Upcoming Week, 🎓 Grades) standing in for the tab bar,
and an `if/elif` chain standing in for `with tab:` blocks.

That switch has one sharp edge worth calling out: the four buttons render in a
single left-to-right pass each script run, so a button rendered *before* the one
just clicked would otherwise still compute its own primary/secondary look from
the pre-click session-state value — one click behind (confirmed live: This Week,
then Grades, used to leave This Week looking pressed instead of Grades). The
click handler fixes this by setting `st.session_state["home_view"]` and calling
`st.rerun()` immediately, rather than also updating a local variable in place —
every button's render then reads the same, already-updated value. `tests/
test_home_nav.py` pins this down directly, including a regression test that
fails without the rerun.

**The header shrank to fit three things side by side** — greeting, streak, fun
fact each get one of three columns (`st.columns([2, 1, 1])`) instead of stacking
full-width, which is most of what "busy" meant in practice.

**Today's lesson roster is now a list of `st.page_link`s, one per subject with
something relevant today, not the lesson itself rendered inline.** Clicking one
takes him to that subject's own page for the actual activities and detail; Home
just shows what's waiting and where. `weekly.today_subject_status(lessons,
today)` picks, per subject, which single lesson (if any) belongs on that roster —
pending review outranks something due today, which outranks something finished
today, which outranks nothing at all — and returns a marker for it: ✅ approved
(passed the full parent review), 📤 submitted (turned in, waiting on a parent),
↩️ needs revision (sent back, waiting on him again), or ⬜ planned (not turned in
yet). A subject drops off the roster entirely once there's truly nothing
relevant to it today, rather than showing an empty or stale row.

**Sidebar nav links were restyled to match the parent-unlock button** he already
liked — each page link in `compass/theme.py` now gets its own bordered, panel-colored
button look, with the active page picked out in the same gold used for primary
buttons elsewhere, instead of the flat tint Streamlit's default sidebar nav uses.

Approved as one paragraph in chat ("good to go") once he'd seen the mockup match
what he'd asked for — see the Layout section above and `GUIDE.md`'s student-view
section for what the page looks like now.

## Assigning a life skill to a specific day

Life skills were previously either "unlocked" (visible on the checklist, any order,
done whenever) or not — no concept of a due date at all. A parent asked to be able to
pin a skill to a specific day, the same way a lesson gets a `planned_for`.

`life_skills.scheduled_for` (a nullable ISO date, `Database.schedule_life_skill` sets or
clears it) is that pin. Setting one also flips `active = 1` in the same call —
deliberately, not left as a separate step: a still-locked skill is invisible on the
checklist itself (`render_life_skill_cards`'s `active OR completed_on` filter), so
without this, a skill could show as "due" on Home while linking to a page that hides it
entirely. Clearing the date back to `None` does *not* re-lock it, on purpose — taking
away an already-unlocked skill as a side effect of clearing its due-date would be a
surprising thing to have happen. `Database.due_life_skills(student_id, today)` is what
Home reads: scheduled for today or earlier, not completed, still active — the `<=` and
not `==` is the same "never silently drop a miss" rule the streak and lessons already
follow, and the `active` check is belt-and-suspenders against a parent re-locking a
scheduled skill by hand afterward.

**A real bug worth noting, found only by testing this live in a browser rather than
trusting the unit tests alone**: assigning a day to a locked skill in *Master list*
correctly wrote `active = 1` to the database, but the very next rerun silently wrote the
lock straight back. The "Unlocked" checkbox on that same row renders every pass with
`key=f"ls_active_{id}"` — a fixed key means Streamlit ignores `value=` after the widget's
first mount and keeps serving its old session-state value instead. That old value (still
`False`, from before the skill got scheduled) disagreed with the freshly-read `active=1`
on the next run, and the code's own "did the user just click this?" check —
`if active != bool(skill["active"])` — read that disagreement as a real click and wrote
the lock right back. Fixed by folding the current value into the key itself
(`f"ls_active_{id}_{skill['active']}"`), which forces Streamlit to treat it as a brand
new widget — freshly seeded from `value=` — every time `active` changes for *any* reason,
not just a click on that exact checkbox. `tests/test_life_skills.py::
test_scheduling_a_locked_skill_in_the_master_list_keeps_it_unlocked` pins this down
directly; confirmed it actually fails without the fix (reverted, one assertion turned
`assert 1 == 0`, then restored).

**Follow-up, reported directly**: assigning a skill for tomorrow made it show up nowhere
at all on Home until the day actually arrived — `due_life_skills` only ever looks at
today-or-earlier, by design, so a future date just fell through the cracks entirely. Two
additions close that gap, both mirroring how lessons already handle the same situation:

* `Database.upcoming_life_skills(student_id, after)` — assigned, not-yet-due, still
  unlocked skills scheduled strictly after `after`. Home splits these into "later this
  week" / "a later week" the same way it already does for lessons planned further out
  (`planned_for > today`, split on `this_week_end`), and shows the matching hint instead
  of nothing at all.
* `Database.life_skills_for_week(student_id, week_start)` — every skill assigned inside
  that Monday-Friday span, done or not (the Week grid shows the whole week's plan, not
  just what's outstanding). `_render_week_grid` in `Home.py` renders these under each
  weekday's card, right alongside whatever lesson landed there, including Friday's own
  Big Project/Travel Journal content.

One real limit, shared with lessons: the Week grid is Monday-Friday only, so a skill
assigned to a weekend won't show on either weekly view — only the Home hint, and the due
card once its date actually arrives, will ever surface it.

## The travel journal's review gate, and assigning a trip

Requested directly: the family travel journal (`pages/9_Landons_Travels.py`) should go
through the same kind of review a lesson does, with a way to assign a trip to a specific
day ahead of time and have it roll into real Writing/Social Studies credit.

`travel_entries` gained the same three columns life_skills' scheduling got, plus one
more: `status` (`planned`/`submitted`/`needs_revision`/`completed` — the exact same
strings and meaning a lesson's own `status` column already uses, not a bespoke
vocabulary), `scheduled_for` (nullable ISO date, `Database.schedule_travel_entry`), and
`revision_note` (what a parent typed when sending one back). Existing rows default to
`completed` — nothing to retroactively review about a trip already written up and sitting
in the family record.

**Every entry with a real story now submits for review, whether or not it was ever
assigned a day.** `pages/9_Landons_Travels.py`'s add-entry form decides:
`"submitted" if story.strip() else "planned"`. `Database.approve_travel_entry` marks it
`completed` and logs its flat credit (`config.TRAVEL_JOURNAL_WRITING_MINUTES` = 30,
`config.TRAVEL_JOURNAL_SOCIAL_STUDIES_MINUTES` = 15 — a real but modest session, not an
attempt to estimate actual time spent) via `log_activity`, in the same click — approving
*is* logging the credit, exactly the same pattern lessons already use.
`Database.send_travel_entry_back(entry_id, note)` sets `needs_revision` and stores the
note; the entry stays editable and anyone (not just a parent) can revise and resubmit it.
The existing manual "Log hours" flow on the page stays available afterward for anything
that earned more than the flat default.

**Assigning a trip is a separate, optional layer on top** — mirroring life_skills'
scheduling exactly: `due_travel_entries`/`upcoming_travel_entries`/
`travel_entries_for_week` are the same three query shapes, and Home/the Week grid render
them the same way, except with the lesson-style four-marker set (⬜/📤/↩️/✅) instead of
life_skills' plain done/not-done one, since a travel entry now has the extra
`needs_revision` state to show. Leave a trip unassigned and nothing about it changes from
before this existed, other than that writing it now waits on a parent to approve.

**A real bug, found only by testing this live in a browser**: the "Assign this trip"
checkbox and its date picker were originally placed *inside* `st.form(...)`, the same
form the rest of the add-entry fields live in. Checking the box did nothing visible at
all — a widget inside a Streamlit form only reports its value when the form's own submit
button fires, so the script never reran to reveal the conditional date picker. This is
the exact class of bug the file already had a comment warning about for `park_choice`
(which lives outside the form for the same reason) — moved the assign checkbox and date
picker outside the form to match, and pinned the submit button's label to `assign_day`
(known accurately outside the form) rather than to the story text (which, being a form
field too, can't be read reactively either).

**Open picks — "assign him to pick," not a specific trip.** Requested as a follow-on:
sometimes the point isn't a parent-chosen destination, it's making him choose and write
about trips of his own. `Database.assign_open_travel_entries(student_id, count, due_date)`
creates `count` blank stubs — empty `state` and `title`, unlike a specific assignment,
which always has both. That blank pair is the whole signal `pages/9_Landons_Travels.py`
needs to tell an open pick apart from a specific one (a specific assignment always has a
title — the add form requires it before it'll save), so no extra schema was needed. Open
picks render in their own "🎯 Assigned: pick N trips of your own" section, separate from
the state/school-year groups a chosen trip belongs to; the moment he sets a real state and
title (whether or not the story's ready yet), the entry graduates out of that section into
the normal grouped list, since it's no longer un-chosen.

**Minimum word count, so an assignment can't be a one-line errand.**
`config.TRAVEL_JOURNAL_MIN_STORY_WORDS` (60) gates every path that would otherwise mark an
entry `submitted` — the add-entry form and the compose/write-it-up form alike. Falling
short doesn't discard what was typed: the entry still saves (as `planned`, with the
under-length story attached), so nothing is lost, and a warning tells him how many words
short he is. He picks "Write it up" to keep going once it clears the bar. This is the same
"downgrade, don't block" instinct as the blank-story stub case just above, extended to a
too-short one.

**Feedback on approval, and proving he actually read it.** Requested directly: a way
to leave him real feedback when approving an entry, not just a flat approve/reject.
`Database.approve_travel_entry(entry_id, feedback="")` stores it in a new
`parent_feedback` column and, unlike `revision_note`, it never blocks or changes the
review outcome -- it's praise, not a fix request. It's entered through an `st.text_area`
(not `st.text_input` -- a real bug, found live: a single-line input silently strips
multi-paragraph pasted text down to one flat line with no way back in) and rendered
through a genuine `st.markdown()` call in its own bordered container, not folded into
the same `html.escape`'d raw-HTML block the story/`revision_note` render through --
that block flattens line breaks and shows markdown syntax as literal characters instead
of rendering it. `Database.set_travel_entry_feedback(entry_id, feedback)` is the
separate path for fixing or rewording feedback on an already-`completed` entry (wired
into the existing per-entry Edit form) -- `approve_travel_entry` only ever runs once,
on a `submitted` entry, so without this there was no way back in to correct
already-lost formatting.

A `feedback_read_at` column (nullable ISO timestamp) tracks whether he's actually
acknowledged it -- explicitly, not by inference. `approve_travel_entry` and
`set_travel_entry_feedback` both reset it (and `feedback_reply`, below) to
`NULL`/`''` whenever the feedback text actually changes (comparing old vs. new
inside `set_travel_entry_feedback`, so re-saving the rest of an edit without
touching feedback doesn't re-flag something already read).
`Database.unread_travel_feedback(student_id)` is what Home's "💬 Feedback" card
queries for its 📬 entries -- `completed`, non-blank `parent_feedback`,
`feedback_read_at IS NULL`.

**Home tees it up; reading and replying both happen on the journal page.**
Raised directly: showing the feedback text itself (or a reply form) on Home
would let him answer a reply prompt with nothing to actually reply *to* on
screen -- exactly backwards from what the gate exists to prevent. So Home's
card is a roster of *links* (`st.page_link`), same shape as the Lessons roster
right above it, never the content. `Database.travel_feedback_read_today(student_id, today)`
is the other half of that roster: entries whose `feedback_read_at` falls on
today, shown with a ✅ instead of a 📬 -- mirrors `weekly.today_subject_status`
keeping an approved-today lesson on the roster rather than dropping it the
instant it's done, so replying doesn't just make the item silently vanish
with no visible confirmation it went through. Read on any other day, it drops
off Home entirely; the entry itself is the permanent record.

**A bare click isn't proof he read anything -- asked directly, and a fair point.**
The only thing that clears it is `Database.mark_travel_feedback_read(entry_id, reply)`,
and `reply` is required: `compass.ui.render_travel_feedback_reply_form` -- used only
on the entry's own card on the journal page, right where the feedback text is
actually visible -- gates it behind a short `st.text_input` -- "What's one thing
from this feedback? (in your own words)" -- checked against
`config.TRAVEL_JOURNAL_FEEDBACK_REPLY_MIN_WORDS` (4) before the click does
anything; short of that it just re-shows the form with a warning, same
"downgrade, don't block" instinct the story's own word-count gate uses. Not proof
of comprehension, but proof he was actually looking at it rather than reflexively
clicking a button -- and it gives a parent something concrete to read and judge
for themselves: the entry shows "✅ Read {date} — he said:" with his reply quoted
underneath once he's answered, "📬 Not read yet" until he does.

## Balanced card rows: a global CSS rule, not a Home-specific fix

Reported directly: a row of `st.container(border=True)` cards looks sloppy when one has
more to say than its neighbors and ends up visibly taller or shorter than the rest.
Streamlit's own `st.columns()` never stretches a bordered container to match its row
siblings — the same problem the metric-tile row on the compliance dashboard already had,
and already had a fix for (see `theme.py`'s "Metrics in the same row need to be the same
height" comment). That fix generalizes verbatim: `[data-testid="stColumn"]` becomes flex,
the element container wrapping a `stVerticalBlockBorderWrapper` gets `flex: 1`, and the
border wrapper itself (plus its inner vertical block) becomes a flex column at `flex: 1`
too — every link in that chain has to actually pass the height down, not just the
outermost one. Added as one CSS block in `theme.py`, not a per-page fix, so it applies to
every row of bordered cards anywhere in the app, including ones built after this — Home's
four-tile row is just the case that surfaced it.

## Grades

Added last, and only because the student asked to be graded. Two modules, split on the
line that makes the rules testable:

* **`compass/grades.py`** — pure arithmetic. No database, no Streamlit. The retry
  weighting, the component weighting, and the letter scale live here so each rule can be
  asserted directly rather than through a simulated page render.
* **`compass/gradebook.py`** — the querying. Reads lessons, quiz attempts, writing review
  statuses, reading checks, and the mastery map, and hands the numbers to `grades.py`.

**Best-weighted, not latest.** `quiz_score()` takes the maximum of
`raw_percent * attempt_multiplier(position)` across a lesson's attempts, where the
multiplier is 1.0 on the first try and drops by `quiz_retry_deduction_percent` per retry
down to `quiz_retry_floor_percent`. The consequence is the point: a careless retry can
never lower a grade, so nothing discourages practicing, while an 85% first try still beats
a perfect fourth attempt (capped at 70%).

**Attempt order is the meaning**, and it is the easiest thing here to get wrong.
`db.list_quiz_attempts()` returns newest-first; the deduction is positional, so
`gradebook` reverses to oldest-first before scoring. Reading it in the returned order
would silently deduct the *first* attempt and grade the retry in full — an inversion no
type checker catches, and the one behavior with a dedicated regression test
(`test_a_quiz_retry_is_deducted_in_the_order_it_was_taken`).

**Missing components redistribute, they don't zero.** `subject_grade()` drops any
component with no data and divides by the surviving weight. `SubjectGrade.graded` is
`percent is not None`, which is what lets the UI distinguish "not graded yet" from an F —
two facts a single float can't tell apart.

**The cap is a label, not a gate.** `grades.can_improve()` answers whether another attempt
could raise the banked score — false at `config.GRADED_QUIZ_ATTEMPTS`, and false once a
perfect next attempt would still land under what's banked. `ui.render_quiz` uses it to
label the retry button ("Practice again — won't change your grade") and never to disable
it. Blocking practice to protect a number would invert the whole incentive.

**One renderer, both audiences.** `ui.render_report_card(..., for_parent=)` is the only
thing that draws a grade, on his Grades tab and on the parent Home alike, so the two can't
drift. The flag changes wording and, on the parent side, adds the weight-settings pointer
and the by-hand override control below.

**Where a parent finds and edits a grade.** Reported directly: "where can i find/edit a
grading record as parent?" Grades live on the **Report card** section of the parent Home
(the same numbers as his Grades tab), and each is *computed* from what he turned in — quiz
scores, writing/reading checks, math mastery, and the assessment verdict a parent sets
while grading in **Mission Control → Review**. That covers per-assignment grading, but a
parent still needs the last word for things the app never saw (a hand-graded project) or a
bad-day score to forgive. So each subject's breakdown expander now carries a **"Set this
grade by hand"** form: `gradebook.set_override` stores a `grade_override_<subject>` setting
(plus an optional note), `gradebook._apply_override` stamps it onto the computed
`SubjectGrade` so the hand-set number wins while the computed breakdown stays visible
beneath it, and **Clear (use computed)** removes it. An override can even grade a subject
with no computed signal at all — a subject taught entirely off-app. Since there's still
only one renderer, the adjusted number and its "✏️ adjusted by parent" mark show on his
screen too.

## The submit-and-review gate

`student_lesson_view()` in `compass/ui.py` shows exactly one "current" lesson per
subject and a button: **📬 Turn it in for review**, replacing the original **I'm done
for today**. The difference is what the click does. The original button called
`db.mark_student_done()` (stamps `metadata.student_done_on`) and nothing else —
logging hours stayed a fully separate, easy-to-forget parent action, and a lesson
could sit self-reported-done for days with no signal anywhere that said so. `lessons`
now carries two more `status` values, `submitted` and `needs_revision` (CHECK
constraint rebuilt the same way `_migrate_books_allow_upcoming_status` added
`'upcoming'` — SQLite can't ALTER a CHECK in place), and `db.submit_lesson()` sets
both at once: `mark_student_done()` (unchanged, still what the streak and daily
checklist read) *and* `status = "submitted"` (the new gate).

**"Submitted" and "needs_revision" take priority over anything else for that
subject.** `student_lesson_view` checks for a lesson in either state before it even
computes what's normally due; if one exists, that's what renders — locked and
read-only with a "📤 Submitted — waiting on your parent" banner, or reopened with
the parent's feedback on top — regardless of what's been batch-planned for later
days. This is deliberate, not an oversight: the whole point is that the loop has to
close before anything new appears, even if a parent has already planned the rest of
the week. Subjects are independent, so a stuck lesson only stalls that one subject.

**`render_assessment_card` is the other half.** Its actionable form (Math's mastery
decision, the 5-band verdict, a writing activity's own approve/bounce) only renders
once `lesson["status"] == "submitted"` — before that there's nothing new for a parent
to act on. **✅ Approve & log hours** does both in the same `st.form` submit: records
the grade (`set_mastery` / `record_assessment`) *and* calls `log_activity(...,
lesson_id=...)`, which already sets `status = "completed"` — approved and completed
are the same event now, via a shared `_log_hours_for_lesson` helper reusing the same
minutes/location/subject-credit fields `log_lesson_form` collects. **↩️ Send back for
revision** calls the new `db.send_lesson_back(lesson_id, feedback)` instead: sets
`status = "needs_revision"`, stores `metadata.lesson_feedback`, logs nothing. If the
lesson has its own writing activity still awaiting its own approve/bounce, the
lesson-wide decision waits (`writing_all_approved` gate) — otherwise a parent would
see two different "send it back" buttons for the same lesson at once. Bouncing a
writing activity on its own calls `send_lesson_back` too (with no lesson-level
feedback text — that activity already carries its own).

**"Turn it in" itself is gated on readiness**, not just clickable at any time:
`_lesson_ready_to_submit()` requires the quiz taken (if the lesson has one) and every
writing activity at least submitted, and disables the button with an explanation
(`st.button(..., disabled=not ready)`) rather than letting him turn in unfinished
work. Life Skills, Choice Topics, and Big Projects never go through any of this —
`student_lesson_view` is only ever called from the four graded subject pages, so
their lessons stay exactly as self-reported and parent-logged as they always were.

A skipped lesson (`status: "skipped"`) is excluded from "current" outright — there's
no reason to hand him a lesson the parent already called off.

**Activity Log's "To review" tab reflects all three open states.** `to_review` is now
`status in ("planned", "submitted", "needs_revision")`; `history` is `("completed",
"skipped")`. "⚠️ Needs your attention now" only counts `submitted` (genuinely waiting
on the parent) plus overdue `planned` lessons — a `needs_revision` lesson is waiting
on *him*, so it gets its own quieter "↩️ Sent back — waiting on him" section instead,
visible but not flagged as needing action. `log_lesson_form` (the old, ungated
hours-only form) still renders for anything outside `gradebook.GRADED_AGENTS` — Life
Skills chiefly — but never for a graded subject, where hours only ever get logged
through the combined Approve action above.

**Migrating existing data:** `_migrate_lessons_allow_review_states()` also backfills
the one behavior change this introduces — a lesson already self-reported done
(`student_done_on` set) but still sitting in `planned` under the old rules becomes
`submitted`, landing in the new review queue instead of silently reappearing as his
current lesson once the gate goes live.

**The "To review (N)" tab-header number is a narrower count than the tab's own
contents.** Reported directly: a lesson merely `planned` for a future week — never
started, never turned in — was inflating the header even though nothing about it
needed a parent's attention; the same complaint the `other_week` caption below
already existed to soften without actually fixing. `needs_review_count` in
`pages/10_Activity_Log.py` now only sums `_needs_attention(lesson, today_iso)`
(`submitted`, or `planned` and overdue) plus `needs_revision` lessons plus
`travel_to_review` — a lesson simply scheduled for later, this week or any other,
never counts. The tab body still lists every open lesson (that part didn't change),
but now carries a "📅 This week's plan" heading over the day-by-day board making
clear it's a schedule view, not a second review queue, and the "Nothing waiting on
you right now" success banner checks the same narrower set as the header so the two
never disagree.

**Backlog: a missed lesson's whole week ending doesn't leave it "overdue" forever
— it drops out of his view entirely, into a parent-only holding area.** Requested
directly: a parent wants explicit control over when a missed assignment reappears,
not to have it silently pile up as "overdue" on his own Home/subject page indefinitely.
`weekly.is_backlogged(lesson, today)` is the whole mechanism — true once a `planned`
lesson's own week (`week_start(planned_for)`) has fully ended, computed live off the
two date fields every lesson already carries, no new status value and no scheduled
job needed to "roll it over" at week's end. `weekly.due_lessons()` (shared by Home's
roster and every subject's own page) now excludes anything backlogged, so it's not
just sorted to the bottom of "overdue" — it's indistinguishable from a lesson that was
never generated, exactly the same way a batch-planned *future* lesson is already
invisible to him until its day arrives. This mirrors that existing precedent rather
than inventing a new one: the parent controls the reveal window on both ends now, not
just the front.

Activity Log's "To review" tab gets a new **"🗄️ Backlog"** section (`_needs_attention`
was narrowed to exclude backlogged lessons, so they don't double-count there) —
the only place a backlogged lesson is still visible, parent-only, same as future
content. `Database.reschedule_lesson(lesson_id, new_planned_for)` is the release
valve: updates `planned_for` *and* `week_start` (to the new date's own Monday) on the
existing row, nothing else — no regeneration, no new API call, content and status
untouched. Getting `week_start` right matters beyond cosmetics: without it the moved
lesson would still look "this week's" to its *old* week (blocking that week's planner
from ever treating the day as missing again) while being invisible to the *new*
week's own "already covered" check, risking a second lesson getting batch-generated
for the same day — and Math's shared-skill continuation reads off whatever's already
planned for the *target* week to find its `skill_id`. The "Move to" control (on each
backlog card only — a live lesson doesn't need it) refuses the move outright, rather
than silently colliding, when the target day already has a lesson for that same agent
(`latest_per_day` would otherwise just let the newer one shadow the older one).

**A parent can also send a lesson to the backlog by hand, any day, whether it's even
due yet — not just wait for its week to quietly run out on its own.** Requested
directly: "the freedom to move stories around as I see fit," in the same agile-board
spirit the rest of this feature already borrows from. `metadata.held_back` is the
whole mechanism — a second, manual way into the exact same backlog state
`is_backlogged` already recognized for a naturally-elapsed week, checked first and
short-circuiting the date math entirely, so it works even on a lesson with no
`planned_for` at all. `Database.send_to_backlog(lesson_id)` sets it; every "planned"
lesson rendered anywhere in the To Review tab (attention, the day board, unscheduled,
a different week) gets a **"🗄️ Send to backlog"** action alongside skip/remove, since
the whole point is picking a story off wherever it currently sits, not just off one
particular list. `reschedule_lesson` clears the flag again the moment a lesson moves
to a new day, regardless of which path put it in the backlog to begin with — the
release valve is the same either way. `_review_badge` shows a distinct **"🗄️
backlogged"** badge for a `held_back` lesson rather than falling through to "overdue"
or "planned" — genuinely different information (a parent's own decision, not a date
comparison), and a lesson parked ahead of its own due date isn't overdue at all.

### His "Today" checklist

`render_today_checklist()` in `compass/ui.py`, called from `Home.py`'s student branch
above "Ready for you" — a small accomplishment list, not a second compliance record.
Three sources, all his own signals rather than anything parent-logged:

- Lessons with `metadata.student_done_on` equal to today.
- A quiz result graded today (`metadata.quiz_result.graded_on`), shown inline on its
  lesson (`quiz 9/10 (90%) 🎯` when he passed) rather than as its own row.
- Life skills with `completed_on` equal to today — either of you can check that box
  (`pages/6_Life_Skills.py`'s checklist tab isn't actually parent-gated, despite the
  page's framing), so this counts either way.

Deliberately **not** built from `db.list_activities()` — that's the parent-logged
record, which the two features above this one exist specifically to not depend on.
Basing "what did I do today" on the logged record would reintroduce the exact lag
(sometimes days) that made the home page keep showing a lesson he'd already finished.
Returns `False` when there's nothing to show, so `Home.py` only draws the divider
under it when there's actually something above to divide from.

### His own vocabulary review

Reported directly: Home's "Words to review" always linked to `pages/3_English.py`,
but the student branch there was `if not is_parent(): student_lesson_view(...);
st.stop()` — that `st.stop()` runs before the `Vocabulary` tab (or anything else on
the page) is even built, so the tab holding the actual review flow never existed for
him. "Review them" landed him on a page with nothing to review on it.

Fixing the routing wasn't enough on its own, though: the existing Vocabulary tab
shows a word *and* its definition together, with "Knew it / Missed" buttons — built
for a parent to quiz him out loud and judge the answer. Just unblocking that same
tab for him would put the definition right next to the word he's supposed to be
recalling, testing nothing.

`render_vocab_review()` in `compass/ui.py` is a separate, student-facing flow instead:
word only, a `Show definition` reveal, then he grades himself (`✅ I knew it` / `❌ I
missed it`), writing to the same `db.record_vocabulary_review()` the parent-facing tab
already calls. Nothing writes `entry["definition"]` onto the page until after he's
clicked to reveal it — same redaction reasoning `render_quiz` already relies on for
its answer key, applied to a second kind of answer this app hands out. Per-word reveal
state lives in `st.session_state[f"vocab_reveal_{entry['id']}"]`, cleared the moment
he grades himself, so the next due word starts hidden again.

Self-grading rather than parent-graded was a deliberate call, not the only option —
discussed with the user first. It's consistent with how the rest of the app already
trusts his self-report (`student_done_on`, the life-skill card's own checkbox) rather
than gating it behind the parent, even though nothing here auto-verifies a recalled
definition the way the multiple-choice quiz can auto-verify a chosen answer.

**Made "much funner" on request** — the original version rendered every due word as
its own bordered box, all stacked on the page at once (up to 25 of them), each
independently revealable. Functional, but a wall of near-identical boxes to scroll
through is exactly what reads as boring. Rebuilt around one card at a time instead:
the current card is always `due[0]` — there's no index to keep in sync, since a
graded word's `next_review_on` moves into the future and it simply drops out of
`due` on the next render, so `due[0]` is naturally the next card. Three metrics
above the card (`🔥 Streak`, `✅ Reviewed`, `Left today`) turn it into a session with
visible momentum rather than an open-ended list. A correct answer plays a toast
picked from `VOCAB_STREAK_HYPE` ("Boom!", "Crushed it!", ...) below `VOCAB_STREAK_ON_FIRE`
(5) and `st.balloons()` at or above it; a miss resets the streak (but not
`vocab_best_streak` — a bad answer doesn't erase what he'd already earned this
session) with a low-key "you'll get it next time" rather than anything that reads as
scolding. Clearing the whole due list gets its own `st.balloons()` payoff screen
instead of the same flat "Nothing due" message a session that never opened the page
would see. None of this touches scoring or the Leitner schedule — `vocab_streak`,
`vocab_best_streak`, and `vocab_reviewed_count` are purely session-local, never
written to the database.

Verified interactively against a running instance: watched the streak metric climb
through three correct answers, confirmed the deck correctly advanced to the next
card each time without an explicit index, and drove a full four-word deck to
completion to see the actual balloons-plus-summary screen fire, not just trust that
the code path existed.

### A second review mode: Trading Cards (by way of Memory Match)

This mode has been through three builds. Started as a click-word-then-click-definition
two-column mode, suggested mid-conversation as a "what about." Rebuilt on "boring...
make it fun" into a session-streak-and-balloons version of the same two-column mechanic.
Rebuilt again, more drastically, into **Memory Match** — a face-down tile grid, the
classic card-pairing game — after three rough concept mockups (a two-column card reskin,
an arcade HUD layer, this memory-grid concept) were shown as a standalone clickable HTML
preview and Memory Match plus the HUD idea is what got picked. Then reverted back to the
two-column mechanic entirely — this time explicitly styled as **Trading Cards**, the
concept that had originally lost the vote — on direct feedback: "it doesn't let the
student see the match. it just goes away immediately." A face-down memory game is
supposed to make you work to remember what's where; a *matched* pair disappearing the
instant it resolves gives nothing to actually see or remember it by, which undercut the
whole premise rather than being a minor rough edge.

**The mechanic, restored.** `render_vocab_match()` shows two columns — shuffled words on
the left, shuffled definitions on the right, all visible at once, nothing face-down.
Click a word to select it, click a definition to check it. A correct match stays
resolved and drops out of the active list, same as it always did; a wrong guess clears
the selection and lets him try again. Nothing here ever has to vanish to make the game
work, because there's no board position to remember — that's the actual, structural
difference from Memory Match, not just a styling change.

**Scoring matches the flashcard flow exactly, restored along with the mechanic.** A word
matched on the first guess counts as "knew it"; a word that took a wrong guess first
still counts as "missed it" once it's eventually matched — same
`db.record_vocabulary_review()` semantics the flashcard flow and the parent-facing tab
use. (Memory Match's build had a deliberately different rule here — a mismatch there was
mostly spatial-memory noise, not a real vocabulary gap, so it only ever recorded a win.
That divergence doesn't apply anymore since Memory Match itself is gone; Trading Cards
never needed it in the first place.) The session **streak** still shares
`vocab_streak` / `vocab_best_streak` / `vocab_reviewed_count` with `render_vocab_review()`,
so switching between Flashcards and Trading Cards mid-session carries momentum forward,
and it still breaks the instant a wrong guess happens rather than waiting for the
eventual correct match.

**The Arcade HUD survived the revert, on purpose.** The round timer, the `st.progress()`
completion bar, and the persisted `vocab_best_round_seconds` personal record were liked
independently of Memory Match's mechanic, so dropping the tile-grid didn't mean dropping
those — they're layered on Trading Cards' rounds exactly the way they were on Memory
Match's.

**A real regression surfaced by testing this properly rather than trusting the ported
code.** The round-freshness check that decides "should this round reshuffle" compared
every word in `round_ids` against the current `due` pool — but a word he'd *just*
matched drops out of `due` immediately (`record_vocabulary_review` moves its
`next_review_on` into the future), which that check couldn't distinguish from "this word
was reviewed somewhere else and the round has gone stale." The practical effect: every
single match silently restarted the whole round on the very next render, so
`vocab_match`'s `resolved` set could never hold more than one word at a time and the
progress bar could never show more than "0 / N" or "1 / N." Caught by actually clicking
through a full multi-word round in a real browser and watching the progress bar fail to
accumulate, not by reading the code. Fixed by checking only the *unresolved* remainder of
the round against the due pool, rather than the round's original full membership —
a word he already matched doesn't need to still be "due" for the round to still be
valid. Pinned with `test_matching_one_word_does_not_reset_the_rest_of_the_round`.

Verified interactively against a running instance both times: the first build's
mismatch/Continue flow and correct-scoring path both checked out with Playwright before
the "goes away immediately" complaint arrived; after the revert, a full three-word round
was played through in the browser specifically to watch the progress bar actually
accumulate (2 / 3, not resetting to 0 / 2) before calling the regression fixed, plus
confirmed final DB state (`box` advanced on all three words) and a genuine
`vocab_best_round_seconds` record written.

**Also found along the way, unrelated to this feature but caught while testing it in a
real browser:** the installed Streamlit's `use_container_width` argument logs a
deprecation warning whose own stated removal date (2025-12-31) had already passed
relative to this session. Since `requirements.txt` pins no upper bound on `streamlit`,
a future `pip install` could land on a version where the old argument is a hard error,
not a warning. Migrated all 13 call sites across `compass/ui.py` and
`pages/9_Compliance.py` to `width="stretch"` (confirmed against the installed version's
own docstring, not guessed) rather than leaving it as a ticking time bomb for whoever's
machine happens to `pip install` next. This survived the mechanic revert since it was
never specific to Memory Match.

### Replacing the review mode entirely: multiple choice

Whatever tile/card mechanic was current at any point above, all of them shared the same
underlying weakness: matching two already-visible things (or flipping a face-down pair)
mostly tests spatial memory -- where was that card, which column had that word -- and a
"win" never actually required recalling a definition cold. On direct feedback that the
game "def not a good product," `render_vocab_memory()` (the Concentration build that had
been current) was replaced outright with `render_vocab_quiz()`: one word on screen at a
time, four possible definitions below it, pick one, get graded immediately. The three
decoys come from his own *other* vocabulary words' real definitions rather than an
invented distractor -- no AI call needed, and a decoy that's a real definition of a real
word he's also learning is a more honest test than a made-up one anyway.

Same `db.record_vocabulary_review()` call either way, so the Leitner schedule underneath
means the same thing regardless of which review mode came before it. The session
`vocab_streak` / `vocab_best_streak` / `vocab_reviewed_count` carried over unchanged. The
round timer and `vocab_best_round_seconds` personal-best did not survive this one --
there's no natural "round" left to time once review is sequential, one word at a time,
rather than a whole board cleared at once.

**A wrong pick's reveal is the actual teaching moment**, so a picked answer stays on
screen -- the real definition marked correct, his own wrong pick marked plainly -- until
he clicks "Next word," rather than auto-advancing. That created its own version of the
Trading Cards regression above: the word he'd just answered drops out of `vocabulary_due`
immediately regardless of right or wrong (same `next_review_on`-moves-forward behavior),
so a naive "is the current word still due" check reset the whole quiz state on the very
next render -- before the reveal ever had a chance to show. Fixed by keying the reset
check on whether a word is actually mid-reveal (`picked` is set) rather than on `due`
membership at all; a mid-reveal word keeps rendering regardless of what `due` says, the
same lesson Trading Cards' own regression already taught, applied to a new mechanic.

## Printing a lesson

There are two places to get a lesson as a `.docx` (`compass/export.py`):

1. **Right after generating one** — a **Download as Word doc** button sits next to
   the on-screen render in the shared `generate_and_log` loop (`compass/ui.py`). This
   only exists for the lesson currently held in that page's session state, so it's
   gone the moment you navigate away or reload — Streamlit session state doesn't
   survive either.
2. **Activity Log → To review** (`pages/8_Activity_Log.py`) — loaded from the
   database rather than session state, each with its own download button. Shows
   unlogged lessons by default; tick "Also show completed and skipped lessons" to
   reach an older, already-logged one. This is the durable one: it's there whether
   the lesson was generated this session or three weeks ago.

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
keyed by student and due date so each year gets its own row).

## Starting a new school year

```bash
python3 scripts/new_school_year_reset.py
```

Wipes the previous school year's working data so the app opens clean for the
next one, without touching anything that isn't tied to a single year. Takes
a safety snapshot first (the same `compass.backup.snapshot` mechanism behind
automatic backups), prints exactly what it's about to touch, and asks for a
typed `YES` before writing anything.

Cleared: generated lessons, logged activities and their subject credits,
saved books and vocabulary, the travel journal, math mastery progress, the
Science/History "topics already explored" history, course/credit records,
the Check-In feelings journal, and the morning routine log. Life Skills keep
their curated list — only `completed_on` resets, so nothing he already
learned needs re-adding.

Left alone: the student profile, Big Projects (long-term projects are
explicitly meant to carry across a summer), Tier 3 Choice topics,
declarations of intent, and uploaded district documents — none of those are
a single year's assignments, so clearing them isn't this script's call to
make.

## Big Projects: chunking a new project into steps with AI

Every Big Project's steps used to be entirely hand-authored — either typed in one
at a time on the Add/manage tab, or seeded from the fixed `BIG_PROJECT_CATALOG` in
`compass/storage/db.py`. Requested directly, to lower the barrier for a parent's own
project idea: **✨ Chunk this project into steps with AI**, on the Checklist tab,
turns a project's title and vision alone into an ordered list of steps in that exact
same shape (`title`, `description`, `materials`, `credit_subject`, `min_days`,
`max_days`) — `compass.agents.project_chunker.generate_project_steps` is a single
on-demand model call, modeled directly on `course_summary.py` rather than the daily
Tier 1 `LessonAgent` framework: chunking is occasional, not a recurring per-day call,
so it doesn't need a next-topic strategy or a review gate. Saved to the `lessons`
table under its own agent key purely for the Costs page (never shown to the student —
Home's roster only ever queries the four core agent keys, so this one is already
invisible there with no extra exclusion needed, same reasoning `course_summary`'s own
call already relies on).

**Offered only while a project has zero steps, on purpose — there's deliberately no
"regenerate" story here.** A project with any steps at all already has real state
worth not silently clobbering: a parent's own hand-written step, a step Landon's
already checked off. Reconciling an AI rewrite against that safely is a genuinely
different, harder feature; restricting this to a blank project sidesteps the whole
question; nothing existing is ever at risk of being overwritten. `credit_subject` is
drawn from the full `SUBJECT_KEYS` enum, unlike Life Skills' own narrower per-skill
allowed set — a project's steps routinely span several different subjects across one
plan (writing the story, building the set, editing the film), so there's no single
subject to narrow against the way one skill has. The prompt includes one real step
from `BIG_PROJECT_CATALOG` as a few-shot voice/detail-level example (never content to
reuse) so the draft reads like the starter catalog's own steps — concrete
instructions, a materials list, an observable "before you move on" bar — rather than
generic advice.

**A step's own Backlog vs. To Do, same flow as a lesson's own Backlog.** Requested
directly: "the freedom to move stories around," this time for a project's individual
steps, not just lessons — a parent moves any step between Backlog (parked, parent-only)
and To Do (committed to the plan, visible to Landon) at will. `project_steps.active`
is the whole mechanism, mirroring `life_skills.active` almost exactly (a catalog skill
locked from the student view until a parent unlocks it): `Database.
set_project_step_active(step_id, active)` flips it, and every render site (the
Checklist tab's own step list, the "up next" pick, the First Day blurbs,
`big_project_status_text`) filters to `active OR completed_on` — a step already
finished stays visible regardless, same reasoning `set_life_skill_active` gives for
never touching `completed_on`.

One real difference from Life Skills' default: `add_project_step`'s own `active`
parameter defaults to **`False`**, not `True` — a freshly added step, by hand or from
the AI chunker's own insertion loop, starts in Backlog, not immediately committed.
Requested directly, true Kanban-style: nothing lands in the current plan until a
parent explicitly pulls it there. The one deliberate exception is the starter
catalog (`BIG_PROJECT_CATALOG`) — `_insert_big_project` writes its rows directly
rather than through `add_project_step`, so a starter project's steps keep coming in
already-visible, exactly as they always have; extending Backlog-by-default to the
catalog too was out of scope for what was actually asked. The column's own SQL-level
default is `1`, the opposite of the Python parameter's — that's not an inconsistency,
it's protecting every step that already existed before this column did, so an
already-visible step never retroactively vanishes into the Backlog the moment a
family updates.

Landon still checks off any visible step freely (unchanged — steps were never
hard-locked, same parity as Life Skills), and an already-done step never offers "Send
to backlog" (checking a box he's finished off and hiding it from him would be a
strange thing to let happen by accident).

**Choice Topics gets the same Backlog gate, not a table merge with Life Skills.** Both
are parent-curated lists a student pulls stories from, which reads at first glance like
the same feature — but they diverge in enough places (Life Skills' four-tier compliance
accounting, its own `active`/`held_back` semantics already wired through grading; Choice
Topics' lighter propose/approve/decline flow with no tier accounting at all) that
actually merging the tables and their logic would mean reconciling two different review
models rather than lining up one gate. So only the gate moved over: `choice_topics.active`
mirrors `life_skills.active` and `project_steps.active` exactly — `Database.
set_choice_topic_active(topic_id, active)` flips it without touching `status`,
`decided_on`, or `parent_note`, and the page's own topic list filters to `active OR
status in ("done", "declined")` (a closed-out topic stays visible regardless of where
it's parked, the same "never hide a finished thing" rule the other two gates use). New
topics default `active=True`, matching Life Skills' own default rather than Big
Project steps' backlog-by-default one — Choice Topics never hid anything from Landon
before this, so nothing should suddenly disappear the day the column ships.

**Landon's Travels folds in as its own Big Project — a folder around it, nothing about
the travel journal itself changes.** Requested directly, framed as "essentially a
travel log" that should sit inside Big Projects rather than as its own separate nav
item — but a real merge (moving `travel_entries` rows into `project_steps`) would have
meant giving up its own review-gate direction (a trip is *his* to write, a step is
either of yours to check off), its flat per-entry credit instead of a project's
per-step one, and the assign-a-trip/open-pick scheduling model entirely. None of that
was asked for — "nothing changes... no changes at all" was explicit — so the link is
purely organizational: a new `big_projects.kind` column (`'steps'`, the default every
existing project already migrates in as, or `'travel_log'`) marks a project that has no
`project_steps` rows at all and never will. `Database.ensure_travel_log_project
(student_id)` creates the one `kind='travel_log'` row, found by `kind` rather than by
title so a parent renaming it later can't spawn a duplicate. Its Checklist-tab card
renders a trip-count summary and a link out to the real Travels page instead of a step
list or the "chunk this into steps with AI" offer, and it's deliberately excluded from
both the "add a step" project picker and the "work on this one this year" pick — the
latter assumes an active project has steps with a next one due, which is never true for
a travel log; Travel Journal keeps running on its own assignment schedule regardless of
what's "active" among the step-based projects. Photo uploads and a printable trip
read-out were floated as a future idea, not built here — this pass is just the folder.

**Both then got pulled out of the top-level sidebar entirely.** After seeing the two
features above live, the follow-up ask was explicit: "choice and life skills are the
same and the travel journal is really a big project... i want a consolidation of side
bar menus." So `pages/5_Choice_Topics.py` is gone outright — its full UI (add-topic form,
list, backlog toggle, log-time form) moved into `compass.ui.render_choice_topics_section`
and now renders as a **"Student's Choice"** tab on the Life Skills page, right next to
*Checklist*. `pages/9_Landons_Travels.py` stays a real, unchanged page (embedding its
map/review-gate UI inline was judged too big a lift for a nav cleanup), but
`Database.ensure_travel_log_project` is now called unconditionally from `page_setup()`
on every page load — the Travel Log project is just always there from the very first
launch, no button to click. Both pages' sidebar links are hidden unconditionally (for
both of you, not just for him) via a small CSS rule in `compass.ui._hide_folded_in_nav`,
the same mechanism `_hide_parent_only_nav` already used, just not gated on `is_parent()`
this time. Every other entry point into either feature (Home's cards, the Friday plan
picker, the Travel Log card's own link) was repointed rather than left dangling.

**Two entry links: a student one and a parent one.** Requested directly: "the current
one remains unchanged and will be the student only link, but it loses the option to
login as parent. that parent link will be a new entry point ... for me only." It's one
Streamlit app with two front doors, told apart by a query string. The plain URL is
Landon's — with a PIN set it opens in student view and shows **no** parent-unlock
control at all (`compass.ui._mode_control` returns early before rendering it), so there's
nothing to type a PIN into and nothing hinting the parent view exists. The parent's own
bookmark carries `?view=parent`; `compass.ui.parent_entry_requested()` (session-sticky,
so it survives the reruns and page-nav that drop the query string) is the one gate that
reveals the unlock box. This is UX separation layered on top of the real gate, not the
gate itself — every piece of parent content is still `is_parent()`/`parent_only()`-checked
and PIN-verified, so the query string only decides whether the unlock box is *shown*, never
whether access is *granted*. Mission Control, Compliance, Courses, Student Profile, and
Model Costs stay in `_PARENT_ONLY_PAGES`, hidden from the student sidebar as before.

**A consolidated Backlog tab on Activity Log — every item type's "what's parked or
still left," in one place.** Requested directly: a parent needs a clean view across
item types, not just lessons — "Landon did the first two legs of Lego film, backlog
would clearly show what's left." A new **🗄️ Backlog** tab groups three sections:
lessons already in `lesson_backlog` (hoisted out of the "To review" tab's own
computation so both places share one filter instead of two), every non-shelved,
non-travel-log Big Project's remaining steps — backlogged *and* to-do-but-not-done
together, since a parent describing "what's left" means both — grouped by project
title with an inline "Move to To Do" action, and backlogged Choice Topics with their
own inline "Un-backlog" action. Life Skills is deliberately **not** a fourth section:
its own "backlog" is the 161-entry master catalog, most of it locked by design (a
pace-control menu you release from at your own speed, not situational parking), and
its own Master List tab already is the right view for that — listing all of it here
with individual buttons would just bury the small, situational sections this tab is
actually for. A lesson already in Backlog is no longer duplicated as a full card
inside "To review" too (rendering the same lesson through `_render_review_card` twice
on one page collided on that helper's own widget keys, since Streamlit's key
namespace isn't scoped per tab) — just a one-line count pointing at the new tab.

Building this surfaced a real, unrelated pre-existing bug: `_backfill_big_project_catalog`
and `seed_big_projects` both treated "this student has *any* `big_projects` row" as "the
starter catalog was already seeded, so top up what's missing" / "so don't seed again."
Once `ensure_travel_log_project` started creating that one automatic row on every
family's first page view, both checks fired immediately, for everyone — the starter
catalog would get silently injected on the very next reload even though nobody clicked
anything, and the seed button itself would permanently stop doing anything from day one.
Both are now scoped to `kind = 'steps'` rows only, the same fix applied everywhere else
this session that a raw `list_big_projects()`/truthiness check meant "you have a real
project" before the Travel Log row existed to complicate that.

**Upload a Word doc instead of typing a written response.** Some kids would rather
write in Word than in a browser text box. Every written-response activity now shows
an `st.file_uploader` ("...or upload a Word doc instead", .docx only) right above the
existing text box -- the text box stays; the upload just refills it with the doc's
extracted text (`compass.export.extract_docx_text`, built on the `python-docx`
dependency already used for the export direction) rather than opening a second,
separate review path. Every check downstream -- the word-count/requirements gate in
`check_writing`, the AI "check my work" pass, parent review -- reads that same
`response` string, unchanged, whichever way the words got there. A non-.docx upload
(wrong format, corrupted file) raises `DocxExtractionError` with a plain "that doesn't
look like a valid Word file" message instead of a raw traceback. The upload widget has
to run, and on a change rerun, *before* the text area is instantiated on the same
script pass -- Streamlit refuses a `session_state` write to a widget's own key once
that widget has already appeared in the current run, which is also why re-uploading
the same file doesn't loop: the extracted text is only written (and the page only
rerun) when it actually differs from the box's current value, so a response he's
since edited by hand doesn't get silently clobbered by the file staying "uploaded"
across reruns. Considered and skipped for now: spreadsheet upload (a worksheet isn't
prose, so there's nothing for the AI check to read) and a live Google Sheets link
(Compass has no OAuth story for reading a real Sheet).

**Coding Camp -- a new track, same shape as Core Life Skills throughout.** Requested
directly: "code camp, code games, code use cases for a teenager to make it fun." Rather
than a new kind of feature, it reuses the exact pattern Core Life Skills already
established -- its own table (`coding_modules`, same columns as `life_skills`), its own
starter catalog (`CODING_MODULE_CATALOG` in `compass/storage/db.py`, ~18 modules across
four categories -- games, automating something annoying, things worth showing off, how
computers actually work), the same active/backlog gate, the same schedule/due model,
and the same "parent decides, no agent picks the next module" reasoning. Every catalog
module is framed around something he'd actually want to build or show off (a
choose-your-own-adventure text game, a script that cleans up a messy downloads folder, a
personal website about something he's into) rather than an abstract exercise. Most
credit `occupational_education` (career-relevant technical skill, same subject Life
Skills' own catalog leans on); a few that are really about visual design credit
`art_and_music` instead, and one about working with a real spreadsheet of data credits
`math`. Originally lived at `pages/17_Coding.py`, deliberately without a "plan a
session" AI agent tab (unlike Life Skills) -- v1 was the checklist itself,
with an agent and a fold into Life Skills' own page following later (see
"Coding Camp folds into Life Skills" further down). `render_coding_module_cards` and
`render_coding_module_catalog_manager` in `compass/ui.py` use plain bordered
containers/expanders rather than Life Skills' own custom "Neon Pop" card-grid CSS --
a deliberate scope cut for a v1, not a design downgrade, on the same reasoning
`render_life_skill_catalog_manager`'s own docstring already gives for its half of Life
Skills ("plain and utilitarian on purpose").

Two migrations were needed to let this exist safely on a database that predates it:
`activities.tier` had a CHECK constraint listing every valid tier, and SQLite can't
ALTER a CHECK constraint in place, so `_migrate_activities_allow_coding_tier` rebuilds
the table with `'coding'` added -- same shape as the original
`_migrate_activities_allow_projects_tier` rebuild, just careful to also declare and
copy `course_id` (which didn't exist when that first rebuild was written) so an
existing family's course tags survive it. `coding_modules` itself needs no migration at
all -- it's a brand-new table, and `CREATE TABLE IF NOT EXISTS` in `schema.sql` covers
that on its own.

Building this also surfaced a real, unrelated pre-existing bug in the sidebar itself:
Streamlit's native "View N more" collapse toggle -- which the nav-consolidation pass
(above) unconditionally hid for the student view, on the theory that hiding the
parent-only pages would always leave the rest fitting without it -- stopped being true
the moment the page count grew past Streamlit's own collapse threshold. Adding Coding
Camp pushed it over: Quizzes and Coding both silently became unreachable for him, since
the one thing that would have revealed them (the toggle) was itself hidden by our own
CSS. `compass.ui._hide_parent_only_nav` no longer touches that toggle at all, regardless
of page count.

## One shared control for moving any "story" around the board

Requested directly: a single, consistent way to move any in-progress item --
a lesson, a Big Project step, a Choice Topic, a Life Skill, a Coding Camp
module -- to a specific day, or to Backlog, from a control that lives right
on the item's own card everywhere it renders, replacing the handful of
scattered buttons (`🗄️ Send to backlog`, `➡️ Move to To Do`, an inline
reschedule date input) each surface used to have its own version of.

`render_story_move_control` in `compass/ui.py` is the one implementation:
a small `st.popover` (📅, or the assigned date, or `🗄️ Backlog` once
backlogged) holding two controls -- an "Assign to a specific day" checkbox
plus date picker, and a "Send to backlog" checkbox. It takes `active`/
`scheduled_for` plus two callables (`set_active`, `schedule`) rather than a
db object directly, so every item type wires its own two db calls in and the
control itself stays ignorant of which table it's touching. Assigning a day
always unlocks (`active = 1`) as a side effect -- the same
`schedule_life_skill` pattern already established -- but clearing the date
does not re-lock; taking away an already-unlocked item just because its date
got cleared would be a surprising side effect nobody asked for.

Two item types didn't have a day to assign at all before this: `project_steps`
had an explicit "no due_on anywhere on this table, and that's intentional"
comment in `schema.sql`, since a step's pace was meant to be relative
(`min_days`/`max_days`), not a calendar date -- a deliberate design this
request explicitly overrode. Both `project_steps` and `choice_topics` gained
a `scheduled_for TEXT` column (via `_ensure_column`) and their own
`schedule_project_step`/`schedule_choice_topic` methods, identical in shape
to `schedule_life_skill`.

Lessons don't fit the same `active`/`scheduled_for` shape as cleanly -- a
lesson always has *some* `planned_for` (there's no "unscheduled" state the
way a Life Skill or Choice Topic has), and backlog only ever comes back out
through picking a new day (`reschedule_lesson`, which clears `held_back` as
a side effect), never through a bare "un-backlog, keep the old day" move.
`render_story_move_control` handles this with two extra, opt-in parameters:
`show_backlog_toggle=False` for lessons wires the un-backlog-without-a-date
case through `set_active(True)` rescheduling to today instead, and
`validate_schedule` lets a caller reject a specific date before it's written
(shown as an inline error, popover left open) -- the one place this is
needed is the lesson picker's existing "don't let two lessons from the same
agent land on the same day" collision check, which used to disable the
inline Move button and now runs as this callback instead.

Wired into: Big Project step rows (`pages/7_Big_Projects.py`, both the To Do
and Backlog lists), Choice Topics rows (`render_choice_topics_section`),
Life Skills and Coding Camp checklist cards (`render_life_skill_cards`/
`render_coding_module_cards` -- additive there, since neither had a per-card
backlog control before, only Master List did), and lesson review cards
(`_render_review_card` in `pages/10_Activity_Log.py`, now offered everywhere
a lesson is still `planned`, not only in the dedicated Backlog tab). Master
List (Life Skills/Coding Camp) keeps its own separate unlock-toggle-plus-date-picker
UI as-is -- it serves the distinct "release this from the master catalog"
purpose, a parent-only curation view the per-card control was never meant to
replace.

One easy-to-miss detail: the popover's label collapses to a single emoji
(`📅` alone, no "Move" text) when there's nothing to report yet -- this
control sits in a narrow top-right corner of a card grid (three cards to a
row on Life Skills' Checklist tab), and a two-word label wraps into an
unreadable single-character-per-line sliver at that width. The other two
states (an assigned date, or `🗄️ Backlog`) already read fine there on their
own; a `help=` tooltip on the popover covers the icon-only case.

## Big Projects: a branching "choose your path" mode

Requested directly, as an integration question about a hypothetical
Occupational Education agent: "flow of potential choose your own experience
for Landon... option to flow from prior legs of choose." What actually
shipped is narrower and more concrete -- not a new agent, but a second mode
for the Big Projects feature that already existed: alongside an ordinary
`'linear'` project (one fixed, ordered sequence of steps), a project can now
be `'choice'` (`big_projects.mode`) -- a branching tree instead, where
finishing a step reveals whichever steps branch off of it as the next set of
paths to pick between, rather than there being exactly one next step.

The tree lives on `project_steps.parent_step_id`, a nullable self-reference
(`ON DELETE CASCADE`, so removing a step also removes whatever branches off
of it, the same way removing a whole project already cascades to its
steps). `NULL` means "a starting option" on a choice-mode project; it's
simply unused on an ordinary linear one, where `sort_order` alone still
decides the sequence. Both columns are new, added via `_ensure_column` for
databases that predate them -- `mode` defaults to `'linear'` (exactly what
every pre-existing project already was) and `parent_step_id` defaults NULL.
Following the precedent `big_projects.kind`'s own migration already set: no
CHECK constraint on the ALTER-added `mode` column (SQLite's CHECK-on-ALTER
support is the kind of thing not worth relitigating per column), enum
validation enforced in Python instead -- `add_big_project` raises on an
unrecognized mode, the same way `set_lesson_status` already does for its own
enum.

Three small pure functions in `pages/7_Big_Projects.py` do the actual tree
logic, all pulled from a project's full step list rather than a dedicated
query:

- `_step_chain(steps)` -- the path actually taken so far: starting from the
  roots (`parent_step_id is None`), follow whichever child at each level is
  completed, stopping the moment no completed child is found there. A
  sibling branch never picked just never enters the chain -- it isn't
  deleted or hidden, it simply isn't part of the story so far.
- `_step_choices(steps, tip_id)` -- what's on offer next at the current tip
  of that chain (or at the roots, if nothing's finished yet): unlocked
  (`active`), not already done. A still-backlogged sibling doesn't show up
  as a pick; a parent unlocks it first, same as any other story.
- `_render_choice_steps(steps)` renders the chain as a plain read-only
  checklist, then the offered choices as cards in the same shape the linear
  rendering already uses (a "Done" checkbox, an expander, the shared
  `render_story_move_control`) -- branching only changes what's *offered*,
  never who's allowed to check something off or move it around.

The Checklist tab branches on `project["mode"]` early (`is_choice`): a
choice-mode project gets `_render_choice_steps` plus its own Backlog
listing instead of the fixed-order render loop, skips the progress bar
(there's no single "N of M" to divide by when steps a path never took were
never really part of the plan -- just a running "X steps completed so
far"), and never offers the AI project-chunker button (it only ever drafts
one fixed sequence, never a branching tree -- a choice project's steps are
always hand-built). Backlog rows get a parenthetical -- `(branches from
"Write the script")` or `(a starting option)` -- so a parent can tell which
branch an unlocked-but-not-yet-offered step belongs to before pulling it in.

Add / manage grew two small, targeted additions rather than a new form: a
"How should this one flow?" radio when adding a project, and, only when the
selected project is `'choice'`, a "Branches off of" selectbox (every
existing step in that project, plus "Start of the project") when adding a
step to it. That selectbox reads the *currently selected* project inside the
same `st.form` the picker itself lives in -- accurate once the form is
actually submitted, the same acknowledged limitation the Log Time tab's own
`credit_subject` default already lives with (its docstring explains why:
good enough to scope a dropdown's options, not something written to the
database).

## Coding Camp folds into Life Skills; This Week gets sprint-board freedom

Three small, related changes, all requested off screenshots of the app in
actual use rather than planned up front.

**Bug: the move control was showing up for the student on two surfaces it
was never meant to.** `render_story_move_control` (the shared top-right
popover documented above) is a parent-only tool everywhere else it's wired
in -- Big Projects, Choice Topics, lesson review cards all wrap the call in
`if is_parent():`. `render_life_skill_cards` and `render_coding_module_cards`
didn't, and a screenshot showed Landon's own Life Skills checklist offering
him a "send to Backlog" control that was supposed to be parent-only. Both
call sites now check `is_parent()` before rendering the control, matching
every other surface; regression tests assert no `move_ls_*`/`move_coding_*`
widget key exists in a student-view render.

**This Week's "Plan next week" tab gets the same move control as everything
else.** The original design let a parent regenerate a single already-planned
day or replan the whole week, but offered no way to just move a lesson to a
different day or send it back to Backlog once it existed -- "I want to be
able to plan his next week like sprint planning almost." Each per-lesson
expander in the Plan-next-week tab now renders `render_story_move_control`
right after the lesson body, wired to the same `db.reschedule_lesson` /
`db.send_to_backlog` pair every other surface uses, with a
`validate_schedule` closure that blocks moving a lesson onto a day another
lesson from the *same agent* already occupies (checked against every lesson
for that student, not just the target week, so a collision in a different
week is still caught). Offered for every agent including math -- unlike the
existing single-day "Regenerate", which stays math-excluded because math's
four days share one derived skill_id that a plain day-move never touches.

**Coding Camp folds into Life Skills as a "Coding" tab, not a rollup into Big
Projects.** Asked directly whether Coding should roll up to the Big Projects
board "in a sense" -- the shape doesn't fit: Big Projects is multi-week,
big Project steps that unlock each other; Coding Camp is a same-shape sibling
of Core Life Skills, a flat catalog of independent, pick-any-day modules.
Life Skills was the better home. `pages/17_Coding.py` is deleted outright;
its checklist, Log Time, Master List, and Add-a-module sections now live as
a new "Coding" tab on `pages/6_Life_Skills.py`, alongside Checklist,
Student's Choice (the earlier Choice Topics fold-in). Coding's own
sub-sections render as stacked `st.divider()`-separated blocks rather than a
nested tab strip -- AppTest's `at.tabs` returns every tab across every
nesting level as one flat list with no nesting information, so a nested
"Log time"/"Master list" pair would be ambiguous against Life Skills' own
outer tabs of the same name even though Streamlit itself renders nested tabs
fine. `_FOLDED_IN_PAGES` grew a third entry so the sidebar keeps hiding it.

**Coding Camp gets its own "plan a session" agent -- a build guide written
to the student, not the parent.** Every other subject agent (`life_skills`
included) writes for the parent, who runs the session. Coding is different:
Landon builds the module himself, so `compass/agents/coding.py` generates a
build guide addressed directly to him -- concepts explained before he needs
them, step-by-step instructions with short code examples, common mistakes,
a concrete "done looks like" bar, and stretch goals. Parent-only
`subject_credits`/`parent_note` aside, the guide is visible to both viewers:
`render_coding_plan` renders it inside a "📖 How to build this" expander
directly on the (both-parent-and-student-visible) checklist card via
`db.latest_coding_plan`, since a build guide a student never sees defeats
its own purpose. Generation itself ("Plan a build guide") stays behind
`is_parent()` on the Coding tab, matching how life_skills' own session
planner works -- only the finished guide is shared.

**Home.py's four quick-glance tiles become three.** With Choice Topics
already living inside the Life Skills page and Coding now doing the same,
keeping them as separate Home tiles stopped making sense. The standalone
"⭐ Choice Topics" tile is gone; the Life Skills tile picks up a
`⭐ N on Student's Choice` caption and a `💻 N coding module(s) due` caption
alongside its existing due-count, so one tile now surfaces all three without
losing any of the information the fourth tile carried.

## Closing three more move-control gaps

A full audit of every surface `render_story_move_control` touches (or
should) turned up three more real gaps, closed in the same pass:

**A lesson sent back for revision can now be rescheduled or backlogged
too, not just a `planned` one** -- `needs_revision` is still an open story
(he's meant to redo it, and a parent might genuinely need to push that
redo to a later day), so `_render_review_card` in
`pages/10_Activity_Log.py` now offers the move control there as well.
Fixing this also surfaced a real latent bug it depended on: `_needs_attention`
didn't explicitly exclude `needs_revision`, so an overdue sent-back lesson
could satisfy both the "needs your attention" filter and the "sent
back" filter at once, rendering the same lesson's card twice in the same
page (`_render_review_card` isn't safe to call twice for one lesson --
`st.download_button`'s `key` collides) and crashing the page outright.

**Big Project steps can now be reordered.** `add_project_step` only ever
appended (`MAX(sort_order)+1`), so changing which step comes next in a
linear project's fixed sequence meant deleting and re-adding every step
after it. `db.move_project_step(step_id, direction)` swaps `sort_order`
with whichever sibling currently sits immediately before/after it in
`list_project_steps`' own ordering, exposed as a new "Reorder steps"
section (↑/↓ buttons) on the Add/manage tab -- deliberately separate from
the move control, which handles a day or Backlog, never sequence.

**Travel Journal entries get full move-control parity.** Previously a
trip's day could only ever be set once, at creation (`schedule_travel_entry`
via the add-a-trip form) -- there was no way to reschedule an already-assigned
trip, or park it in Backlog, the way every other story type already could.
A new `travel_entries.active` column (mirroring `life_skills.active`),
`db.set_travel_entry_active`, and the shared move control wired into each
entry (excluded once `completed`, same as a finished Big Project step)
close that gap; `due_travel_entries`/`upcoming_travel_entries` now respect
the new flag the same way `due_life_skills` already does, and a backlogged
entry is hidden from Landon's own view on `pages/9_Landons_Travels.py`
the same way a backlogged skill disappears from his checklist.

Also fixed in the same pass: `render_story_move_control`'s own popover
label used to check `scheduled_for` before `active`, so a story backlogged
after already being assigned a day kept showing its stale date instead of
"🗄️ Backlog" -- none of the `set_active`/`send_to_backlog` implementations
clear the scheduled date, so this was possible for every story type, not
just lessons. The label now checks `active` first.

## A unified weekly Board -- every subject's stories, one week, one place

Requested directly, off a walkthrough of the app in real use: "I don't think
this UI flow is architecturally sound... let's talk about this in an agile,
epic, sprint, story setup." The shared move control (above) already let a
parent send any story to Backlog or a specific day, but reaching it meant
navigating into whichever subject's own page a story lived on, then several
clicks deep into a nested expander -- a different page per subject, a
different depth per surface. The fix isn't a new way of moving a story
(that mechanism was already right); it's putting every subject's stories on
one page, so rearranging the week doesn't mean a tour of five different
pages.

`pages/14_This_Week.py` gains a new first tab, "📋 Board": a week picker
(defaulting to the current week, not "next week" the way Plan next week
does -- this is the page for rearranging a week already underway) and six
columns -- Monday through Friday plus a single global Backlog -- with every
story type rendered as a compact card, the move control right on the card
face this time, not nested inside an expander.

`compass.weekly.board_for_week(db, student, week_start)` is the aggregator:
it gathers lessons, life skills, coding modules, choice topics, big project
steps, and travel entries for one week and buckets each into its own day or
into `"backlog"`. Three new `_for_week` db methods needed adding to cover
the story types that didn't already have one (`coding_modules_for_week`,
`choice_topics_for_week`, `project_steps_for_week` -- the last needs an
actual join, since `project_steps` has no `student_id` of its own, only
`project_id -> big_projects.student_id`), mirroring `life_skills_for_week`'s
existing shape rather than inventing a new pattern.

The Backlog column runs as two passes, not one: first, anything scheduled
*within* the target week that's since been backlogged (so it shows only in
Backlog, never also under a day that no longer means anything); second, a
global sweep of every *other* currently-parked story regardless of which
week -- or no week at all -- it originally belonged to, the same "a single
pool, not sprint-scoped" behavior every subject's own Backlog section
already gives. The one thing that pass had to guard against on purpose:
life_skills/coding_modules are pre-seeded from a ~150-entry starter catalog,
the vast majority of it sitting `active=0` from the moment it's seeded
simply because it was never unlocked -- not because a parent ever parked
it. Naively including every inactive catalog row would drown the board in
clutter that was never really "backlog" in the sprint sense; the fix is a
`scheduled_for IS NOT NULL` filter on just those two types' global sweep --
a row a parent has never touched has never been given a day either, so
this cleanly separates "untouched catalog" from "actually parked."

`render_board_card` in `compass/ui.py` is the one place every story type's
card gets rendered -- a title, a one-line status, and the exact same
`render_story_move_control` call every other surface already uses,
including the same same-agent-same-day collision guard for lessons. Nothing
about *how* a story moves changed; only where a parent has to go to do it.

**"This week"/"Next week" quick-jump buttons**, added right after shipping
the above: the Board's own date picker technically already covered any
week, but reaching next week's board meant hand-picking a date -- exactly
the wrong friction right when it matters most, the moment after a Friday
planning session generates next week's lessons and a parent wants to see
them laid out and rearrange them immediately. The two buttons write
straight into the date_input's own `session_state` key and rerun, so the
jump lands in one click; "Next week" targets the same Monday
`weekly.default_plan_target()` already computes for Plan next week itself,
so the two tabs agree on what "next week" means without either one having
to ask the other.

## The Board becomes a Product Backlog panel + sprint board

A direct follow-up complaint: "this UI flow is not architecturally
sound... let's talk about this in an agile, epic, sprint, story setup."
Three sample layouts were sketched first -- epic swimlanes (one row per
subject), a Backlog-panel-plus-board split, and a sprint-health dashboard
-- and the second was picked, specifically because it's built for the
moment right after a Friday planning session: generate next week's
content, then rearrange it, without leaving the tab.

The Board tab's old sixth "🗄️ Backlog" day-column is gone. In its place:
a `st.columns([1, 3])` split -- a **Product Backlog** panel on the left,
grouped into a `st.expander` per epic (Math, Science, English, History,
Life Skills, Big Projects -- `weekly.EPIC_ORDER`), and the Mon-Fri board
on the right, unchanged except for losing that sixth column. Each epic's
expander is collapsed only because it's empty (skipped entirely, actually
-- an epic with nothing parked doesn't render a row at all); one with
items defaults open, directly requested ("I like how science, math,
english, history are collapsible/expandable").

Every backlog card in the panel is rendered with the exact same
`render_board_card` call the day columns already use -- "assign" isn't a
new action, it's the same shared move-control popover (pick a day, or
leave it in Backlog) opened from a new location. No new write path.

Two small additions make the grouping possible, both pure reshapes of
data `board_for_week` already computes -- no new queries:

- `weekly.epic_for(kind, item) -> str` -- which epic a story belongs to.
  A lesson keys off its own `agent` (both `life_skills` and `coding`
  fold into the Life Skills epic, matching the page they already share);
  every other kind has one fixed epic.
- `weekly.group_backlog_by_epic(backlog) -> dict[str, list]` -- takes
  `board_for_week`'s own flat `"backlog"` list (already every currently
  parked story, any week it came from -- the two-pass sweep documented
  above) and buckets it by epic. "All stories I put into the backlog"
  was already true of that list before this change; grouping it by epic
  is the only thing that's new.

## The Board's day columns get real color, and every card collapses

A direct reaction to seeing the real thing running, next to the sample
mockups: "my layout is really different than the sample... I want the
color day cards," followed by "I want each assignment to be collapsible
too." Two changes, both to `render_board_card` and the day-column loop in
`pages/14_This_Week.py`:

**Colored day cards.** Each day header is now the same colored pill Home's
own Week grid already uses (`theme.PRINTED_COMIC_WEEKDAY_COLORS` --
Mon red, Tue orange, Wed blue, Thu green, Fri purple -- the "Sunday
Funnies" palette, not a new invented one), and every card in that column
gets a matching thin color strip across its top via `render_board_card`'s
new `accent_color` param. The Product Backlog panel's own cards pass no
`accent_color` -- they don't belong to a day, so nothing there should
imply one.

**Every card collapses into an expander**, title as the header -- the
same "closed until you need it" rhythm the Backlog panel's epic sections
already had, now applied one level deeper, story by story, requested
directly off the example of a specific lesson card ("Positive, Negative,
Repeat: All Four Integer Operations"). A card's status line, category,
and its move control now live inside the expander body rather than
always-visible on the card face -- a day with several stories reads as a
handful of one-line rows, not a wall of open detail, matching what
already worked well for the epic groupings.

## The Board stops wrapping titles mid-word on a real laptop screen

A screenshot of the actual running app -- not the wide monitor a mockup
gets built on -- showed titles breaking mid-word ("Operatio ns", "Showdo
wn", "Pressur e"): "we need to make this better, the viewing is terrible
here." The `st.columns([1, 3])` split from the previous section put the
Product Backlog panel and the five-day board side by side, so each day
column only ever got a sliver of the page; even after making both
sections full-width (board on top, Backlog below, stacked instead of
side by side), a follow-up "improve it to the maximum" stress-test at a
realistic 1280px laptop width reproduced the same wrapping -- five equal
`st.columns(5)` fractions of even a full-width row still squeezes a long
title narrower than one of its own words has room for. `st.columns` has
no minimum-width floor; it just keeps dividing evenly as the viewport
shrinks.

The fix borrows the same move Trello and Jira make: give each column a
fixed minimum width and let the *row* scroll horizontally instead of
letting columns keep shrinking. Both the day board and each epic's
backlog-card row are wrapped in `st.container(key=...)` (`"board_days_row"`,
`"backlog_row_<epic>"`), and a `_BOARD_SCROLL_CSS` block targets them by
that key -- the same `div[class*="st-key-..."]` pattern Home.py and the
Life Skills page already use to scope custom CSS to one Streamlit
container. One wrinkle the first pass missed: Streamlit renders each
`st.columns()` call inside an extra `stLayoutWrapper` div, so a `>`
direct-child selector never matches the actual `stHorizontalBlock` --
the CSS has to reach it as a descendant, not a child. With that fixed,
each column gets `min-width: 220px; flex: 0 0 220px` and the row gets
`overflow-x: auto; flex-wrap: nowrap`, both `!important` (Streamlit's own
emotion-cache class sets the competing `flex` value). Titles now wrap at
word breaks, never mid-word, at any viewport width -- a narrow window
scrolls the board sideways instead of crushing it.

## Every board card links back to its own full content

"Can the stories actually be a link to the main page that holds the content
of said activity? ... I expand it to view and there's a link that takes me
to the content on the [subject] page for a deeper review." Each of
`render_board_card`'s six kinds now ends its expander body with a
`st.page_link` to wherever that story's real content already lives, via a
new `_BOARD_DEEP_LINK` table (page, link label, the tab that content sits
under -- `st.tabs` can't be pre-selected from a URL, so the destination tab
is named in a caption underneath rather than jumped to automatically).

The literal reading of the request -- a lesson links to its own subject
page (Math, Science, English, History) -- turned out to be the wrong
target: those four pages are pure planning tools (a "Plan a lesson" form,
a mastery grid, a coverage graph); none of them render an already-planned
lesson's actual content. That content -- objectives, materials, activities,
the answer key -- already renders in full via `render_assessment_card`,
inside Activity Log's own "To review" tab (every lesson that's `planned`,
`submitted`, or `needs_revision` lands there). So every lesson card links
there instead, regardless of subject. The other five kinds do have a real
content view on their own subject page already: `life_skill`,
`coding_module`, and `choice_topic` all link to Life Skills' Checklist tab;
`project_step` and `travel_entry` (folded into Big Projects, same as
everywhere else in the app) both link to Big Projects' Checklist tab.

## A story moved across weeks says so, instead of just vanishing

"I moved two math lessons from backlog to their own dates, 9/2 and 9/3, and
they have disappeared" -- followed by a sharper restatement once the cause
was clear: nothing generated should ever be able to vanish; backlog and
sprint movement should only ever *relocate* a story, never lose it.
Nothing was lost here -- `reschedule_lesson` never deletes a lesson row,
and `board_for_week` only ever renders the one Monday-anchored week it's
asked for, so a story moved onto a date in a *different* week correctly
leaves the board a parent is currently looking at. It reappears the
moment they switch to that week (the `board_week_picker` date input, or
the This/Next week buttons) -- Activity Log's own "To review" tab already
had a safety net for exactly this ("1 more lesson also scheduled, for a
different week... change the date above to see them"), the lesson just
had no equivalent voice on the Board itself, at the moment of the move.

`render_board_card`'s move control now wraps every kind's `schedule`
write in a new `_board_schedule` helper (`compass/ui.py`): compare the
picked date's own Monday against `board_week_start` (now threaded through
`render_board_card` from both of `pages/14_This_Week.py`'s call sites),
and if they differ, say so. The first attempt used `st.toast` -- wrong,
and confirmed wrong by a minimal isolated repro against this app's own
Streamlit version (1.61.1): a toast fired in the same script run that
immediately calls `st.rerun()` (which the move control always does right
after) never reaches the browser at all, toast queue and all. The fix
instead stashes the message in `st.session_state`, which *does* survive a
rerun, and `render_board_move_notice()` -- called once, near the top of
the Board tab, before any card can queue a new one -- pops and renders it
as a real `st.info`, then clears itself so it never lingers into a run it
doesn't belong to.

## ...except the actual bug was the "Send to backlog" checkbox silently resetting the date

The notice above turned out to be treating a symptom, not the disease --
a screenshot of the parent's real screen showed the two moved lessons
genuinely gone from *every* view: not on the target week's board, not in
its Backlog panel, not even under Math's own "Fill in missing days" list
for that week. A live reproduction of their exact steps found it:
`render_story_move_control`'s "Send to backlog" checkbox still read
*checked* right after picking a real day in the same popover (its own
`value=not active` reflects the pre-pick snapshot until the date-pick's
own rerun settles), reading like a leftover step that still needed
unchecking. For every other story kind that's harmless -- `active` is
its own stored column, untouched by scheduling. For a lesson it wasn't:
`set_active(True)` -- the checkbox's own un-check action -- called
`db.reschedule_lesson(lid, date.today().isoformat())`, silently
overwriting whatever day was just picked back to *today*. Today is a
weekend far more often than a weekday, and `board_for_week` only ever
renders Monday-Friday -- so the lesson landed on a day the board never
shows at all, while no longer counting as backlogged either (its week
hadn't "ended" yet). Invisible everywhere, by design, once both actions
landed in sequence -- confirmed with a script that replays exactly that:
pick a day, then toggle the checkbox, and check where the lesson lands.

The fix is a new `Database.unhold_lesson(lesson_id)`, the actual
counterpart `send_to_backlog` needed all along: it clears `held_back`
and leaves `planned_for`/`week_start` completely alone. All three
lesson move controls in the app (the Board, This Week's "Plan next
week" tab, and Activity Log's own review cards) now call it instead of
`reschedule_lesson(lid, date.today())` for the checkbox's un-checked
state -- `reschedule_lesson` stays exactly what it always was: the tool
for a parent *deliberately* picking a new day, never an implicit
side effect of un-backlogging one.

## No story can fall off the board entirely, for any kind, ever

"Fix this so it never happens again. All stories should survive movement
across the boards" -- the reactivate-checkbox fix above closed the one
path that had actually bitten a real lesson, but it was one instance of a
wider structural gap: `board_for_week`'s own placement logic could drop
*any* of the six story kinds, silently, whenever its scheduled date
landed on a day the board simply doesn't track.

Two separate holes, found by tracing every kind through the aggregator,
not just lessons:

- `_place_scheduled` (the day-vs-backlog router every kind funnels
  through) fell through both of its branches for a date that wasn't
  "backlogged" *and* wasn't one of the five rendered weekday columns --
  a Saturday or Sunday, most plausibly. Not placed on a day, not counted
  as backlogged, not anywhere. Fixed by making Backlog the fallback:
  `if backlogged or day_iso not in board: board["backlog"].append(...)`.
- For the five non-lesson kinds, the hole goes a layer deeper: each
  one's own `X_for_week` query filters `scheduled_for BETWEEN week_start
  AND week_start + 4 days` (Monday-Friday) -- a weekend date never
  matches *any* week's version of that range, so it never even reaches
  `_place_scheduled` to be caught by the fix above. The "every other
  currently-parked story" second pass didn't help either -- it only
  ever looked for `active == False`, and a story stuck this way is
  still `active` (nobody backlogged it on purpose). Fixed with a new
  `_stuck_on_an_untracked_weekday(scheduled_for)` helper, OR'd into all
  five second-pass conditions alongside `not active` -- a story lands in
  Backlog if it's genuinely parked *or* if its own date makes it
  permanently unfindable any other way.

One more inconsistency turned up during this pass: `schedule_travel_entry`
was the only one of the five `schedule_X` methods that didn't also set
`active = 1` when assigning a date -- meaning a backlogged trip needed an
extra, separate un-backlog step the other four kinds didn't. Brought in
line with `schedule_life_skill`/`schedule_project_step`/etc.

## The backlog checkbox becomes two one-way buttons

A direct follow-up once the disappearing-lesson bug's real cause was
clear: "when an item is in backlog, the action item shouldn't be uncheck
send to backlog... it should be like assign back to a date and then date
calendar selection." The single `st.checkbox("Send to backlog", value=not
active)` a story's move control used to show was the actual UI root of
the reactivate bug above -- reading the *same* checkbox as "send to
backlog" when active and "take out of backlog" when not is exactly the
kind of control where the direction of a click reads ambiguous, and for
lessons specifically, un-checking it used to carry a real destructive
side effect (silently overwriting a just-picked day).

`render_story_move_control` now shows a `st.caption("🗄️ Currently in
the Backlog.")` plus two mutually-exclusive, always one-directional
buttons instead of the one bidirectional checkbox: **🗄️ Send to
backlog** only appears when the story is active, **↩️ Take out of
Backlog** only when it isn't. Picking a new day in "Assign to a specific
day" already takes a story out of the backlog on its own for every kind
(each one's own `schedule` write does this now, travel entries included
after the fix above) -- "Take out of Backlog" exists only for
reactivating *without* also changing the day. Neither button can be
misread as doing the opposite of what it says.

## "View full lesson" becomes a dialog, not a broken link

Reported directly: "the navigation for next weeks board, go to full
lesson, doesnt actually work." It couldn't have -- `st.page_link` can only
ever open a page on its *first* tab, with no way to request another one.
Life Skills' and Big Projects' own Checklist tab happen to each be their
page's first tab, so their "View full details" links were never actually
broken; a lesson's link was the one real exception, since Activity Log's
"To review" tab is its *third* one (behind "The record" and "Log
something manually"). Every click landed on an empty, unrelated log
view, regardless of which week the lesson was on -- confirmed live by
reproducing the exact click path on a real next-week lesson.

Rather than reorder Activity Log's own tabs (which would just move the
same "only the first tab is reachable" problem, not fix it, and would
change the page's landing tab for every other visitor too), a lesson's
"🔍 View full lesson" is now a button that opens an `st.dialog` right on
the Board -- `render_lesson(item["payload"], lesson_id=item["id"])`
rendered inline, in the same "plain" layout (objectives, materials, an
expander per activity, and the assessment/answer-key section *only when
the viewer is a parent*) `render_lesson` already gives everywhere else.
No navigation, no tab to land on wrong -- works identically for a lesson
on this week's board or next week's, which is exactly what a same-page
modal sidesteps by never leaving the page at all. The other five kinds'
own `_BOARD_DEEP_LINK` page_links are untouched -- their destination tabs
really were already correct.

**The dialog respects who's looking.** The Board isn't parent-only --
Landon has his own read-only copy on Home (`interactive=False`), and the
"View full lesson" dialog is offered there too so he can actually read
what's planned. That dialog used to force `render_lesson(...,
for_parent=True)` and unconditionally offered a whole-lesson "🖨️ Print to
PDF" download, so opening one of his own board lessons showed him the quiz
answer key and the assessment mastery criteria -- reported directly: "on
landons board, his stories hold the answer keys? that is for parent
only?" It is. The dialog now leaves `for_parent` unset so `render_lesson`
falls back to `is_parent()` -- the same gate his normal subject-page
lesson view already uses, hiding the answer key and assessment from him --
and the PDF button (which carries the *whole* lesson, answer key included)
is wrapped in `if is_parent():`, so it never appears on his side at all.
On the parent's own This Week board (`parent_unlocked`) both the answer
key and the PDF are still right there, since planning is what that board
is for.

## Each core subject gets its own "This week" board

Follow-up once the dialog fix above landed: "shouldnt i still be able to
go to each core curriculum tab like math, english, science, history etc
and also get the level of detail and view into lessons... kinda like the
board view of this week and next." Math, Science, English, and History
each gained a new first tab, **"This week"**, alongside their existing
"Plan a lesson" and subject-specific tabs.

`render_subject_week_tab(db, student, agent)` in `compass/ui.py` reuses
`weekly.board_for_week` and `render_board_card` verbatim -- the exact
same aggregation and card rendering the Board tab uses -- filtered down
to `kind == "lesson"` and that one agent. This was a deliberate choice
over building a second lesson-rendering path: any future fix to the
Board's own behavior (the weekend-stuck-story fix, the dialog fix, the
move-control redesign, all above) applies here automatically, with
nothing to keep in sync by hand.

Each subject page's week view has its own "This week"/"Next week" jump
buttons and its own date picker, namespaced per agent
(`subject_week_{agent}_picker`, etc.) so Math's and Science's own pickers
never collide with each other or with the Board tab's own
`board_week_picker` -- all sharing one `st.session_state`, since that's
scoped to the browser session, not the page. The "View full lesson"
dialog and the move control (send to backlog / take out of backlog /
assign to a specific day) work identically here as they do on the Board,
since they're the same `render_board_card` call underneath.

## "Send to backlog" drops out of Big Project steps and Travel entries

Reported directly against a screenshot of the exact popover: "this action
shouldnt be send to backlog, i should be able to push this to any date this
week or next week. just assign to date." A project step's own move control
is sequential and up-next-driven, not a flexible weekly board -- parking an
active step mid-plan never had a real use, and the button read as the only
offered action when picking a new day (which already reschedules the
moment it's picked, no confirm click needed) was the actual point.

`render_story_move_control`'s existing `show_backlog_toggle` parameter
already covered this per caller -- `pages/7_Big_Projects.py`'s active-step
call sites (the choice-mode "choose this" step and the linear mode's
visible/up-next steps) now pass `show_backlog_toggle=False`, and
`pages/9_Landons_Travels.py`'s own entry move control does too ("same
thing with travel log," reported directly, right after). Both pages' own
already-backlogged sections (Big Projects' `Backlog` list) keep the
default -- "Take out of Backlog" still makes sense there. The Board tab's
own project_step/travel_entry cards are untouched, so backlogging either
kind from the sprint board still works exactly as before.

## Assigning a random trip keeps the Travel Journal portfolio growing

A follow-up in the same breath: "i need the ability to send off writing
assignment at random to keep that project going. end goal is a portfolio
of travel entries with landon notes/summary." Unlike the existing "Assign
him to pick & write up" (a blank stub -- he picks the state himself), the
new **🎲 Assign a random trip** button on the journal tab decides the
destination itself: `national_parks.random_unvisited_prompt` picks a real
state (sometimes paired with one of its National Parks) he hasn't logged a
trip for yet, falling back to any state at all once everything's visited
so the button never comes up empty. The new entry gets a real title (the
park's name, or "A trip to <state>") and a due date one week out, so it
renders exactly like a parent-assigned specific trip -- "📝 Not written
yet," ready for him to write the story -- rather than another open pick he
has to name himself first.

## The student gets the parent's Board, read-only

Reported directly: "this board view for parent... this week and next week...
needs to be in the student view... replaced, with a 'board' button that
contains this week and next. just like the parent view... obviously not
including the review this week and plan this week options. those are parents
only."

The parent's This Week Board tab and the student's Home Board now render
through one shared `ui.render_board_days(...)`: the five Mon-Fri columns of
`weekly.board_for_week`, each card via `render_board_card`. The only
difference is a single `interactive` flag threaded into `render_board_card` --
False on the student side drops every parent-only affordance (the
reschedule/backlog move control, and the "View full details" deep links into
management tabs), leaving just the cards and, on a lesson, the "View full
lesson" dialog, which is his to open too. Nothing about a card's data or
layout changes, so a Tuesday card reads identically on either board.

On Home, this folded the old separate **This Week** + **Upcoming Week** week
grids (and their ~180 lines of bespoke "Sunday Funnies" grid rendering) into
one **Board** nav view with a This-week / Next-week toggle, matching the
parent's own. Review-this-week and Plan-next-week stay parent-only on the
This Week page, exactly as before.

## The Backlog's Big Projects section becomes collapsible per project

Reported directly against the old flat rendering: "theres a huge list of
things i cant click on and cant tell what they are... should just be
collapsible list of what each project is made up of. detail. ability to
expand, review." Each project is now its own collapsible expander ("🎬
<title> — N left"), and each remaining step inside is a bordered card
carrying its real detail (the step's description, its materials, the subject
it credits) plus the same move-control popover every other story type uses --
instead of a wall of identical grey captions with a single tiny button. (The
step cards are bordered containers, not `render_board_card`'s own expander:
the move-control popover is safe inside an expander, and this keeps each
step's detail visible the moment the project's open rather than one more
click deep.)

## Life Skills: no more checklist; his view is badges + assignments

Reported across two messages: "we dont need a checklist. lets redo this. all
skills sit in the master list. coding no changes" and "landons view of core
life skills... his activity q of assigned life task skills... badges unlocked
up top, and below in the backlog style uniform across app, are ones i select
for him. these can and will be assigned during the week on specific dates."

The parent's **Checklist** tab is gone. Every skill lives in the **Master
list**, which is where a parent unlocks one and pins it to a specific day
(that surface already had the unlock + assign-a-day controls). Removing the
checklist grid also removed the squished date-button that lived in its narrow
per-card move-control column -- the reported "fix this bug with the date
button... should match growing up."

His own Life Skills view (`ui.render_student_life_skills`) is now: the
**badges he's earned** up top (gold-bordered chips, icon + title + earned
date), then **Assigned to you** below -- the skills a parent unlocked/assigned
him, each a bordered card in the same "what's on your plate" style the rest of
the app uses, carrying its detail (description, materials), its scheduled day
when one's been pinned, and a single **Mark done** checkbox. Un-marking and
removing are parent actions on the Master list, deliberately not offered on
his view. Coding Camp is unchanged.

## Future weeks: page the board several weeks out

Reported directly: "i also think i want to start thinking about future weeks,
going out a few weeks and being able to schedule this out quite a bit... levels
up this app to more sustainable." The scheduling machinery already reaches any
future date -- the move control's date picker takes any day, and "Plan next
week" takes any target week -- so what was missing was *visibility* into those
further-out weeks.

Both boards now page a week at a time rather than only jumping this/next. His
Home Board became a forward pager (**◀ Earlier / This week / Later ▶**, "Earlier"
disabled at this week) that captions the week it's showing ("the plan for 2
weeks out…"), so he can look as far ahead as a parent has planned. The parent's
This Week Board keeps its This-week / Next-week jumps and free date picker, and
gains **◀ Prev / Next ▶** arrows to step through the weeks between without
typing a date.

## Every board card is color-coded by what it is

Reported directly: "the days are easy to tell difference with the colors. for
the lessons under the days, we have the small icons... was hoping for something
better." The day is already unmistakable from the big colored column header, so
each card's own color was free to mean *subject/kind* instead of repeating the
day. Every board card now wears a small colored, labeled bar across its top --
color + icon + word together (**MATH** indigo, **SCIENCE** green, **ENGLISH**
orange, **HISTORY** rust, **LIFE SKILL** teal, **CODING** violet, **CHOICE**
gold, **BIG PROJECT** magenta, **TRAVEL** cyan) -- so what a card *is* reads at
a glance, collapsed or open, whichever day it sits under. Driven by
`ui.board_card_tag` (a lesson keys off its agent, every other kind off the
kind), so the whole board, the per-subject week views, and the Product Backlog
all speak one color language. Replaced the old per-card day-color strip, which
just repeated the column header.

## The board is a subject x day grid, aligned into rows

Reported directly: "can we get better formatting here... so we see each subject
as straight across the week all even in a line?" The day board is now a
subject x day matrix rather than per-day stacks: a header row of day pills,
then one row per subject/kind that has anything that week, each row the same
five day columns in a fixed order (Math, Science, English, History, then the
elective kinds). So a subject reads as one straight line across the week and
lines up cell-for-cell with every other; an empty cell just leaves its
fixed-width column blank, holding the alignment. Every card carries a floor
height so a row of them reads as one even band. The horizontal scroll lives on
the outer container (not each row), so on a narrow screen every row scrolls
together and stays aligned under its day headers. Both boards (parent This Week
and Landon's Home) share this via `render_board_days`.

## Print any lesson to PDF

Reported directly: "i need a print to pdf of each activity itself." The app
already built a clean `.docx` per lesson; this adds a matching **🖨️ Print to
PDF** next to it, so a parent can print any single lesson for paper work or the
record. `export.lesson_to_pdf` renders the same sections the Word export does
(title, overview, objectives, materials, activities, assessment, quiz answer
key, parent notes, credit) with reportlab, embedding a bundled Unicode font
(`compass/assets/fonts/DejaVuSans*`) so curly quotes and accents come out right
and there's **no LibreOffice dependency** -- just `pip install reportlab`.
Generation is deferred behind a callable (like the .docx button), so
a page listing many lessons never builds every PDF on each rerun.

Prose keeps its shape: `lesson_to_pdf` splits every multi-paragraph field
(overview, an activity's instructions and worked example, the assessment, parent
notes) on blank lines into real, separate paragraphs and turns single newlines
into line breaks (`_pdf_split_blocks`). Reported directly: "it turns paragraphs
into blurbs and lossing the structure of assignment" -- reportlab otherwise
collapses every newline to one space, flattening a structured writing prompt
into a single run-on block.

`lesson_to_pdf` takes a `parent` flag that gates exactly the sections
`render_lesson` gates. The parent cut (the default) has everything above; the
**student cut** (`parent=False`) drops the assessment, quiz answer key, parent
notes and subject credit, leaving just the lesson itself -- overview,
objectives, materials, activities. So the "🖨️ Print to PDF" button shows up
wherever a full lesson does, on either side: the Activity Log's per-lesson card
and the just-generated lesson (parent), and the board's "View full lesson"
dialog for both -- the parent gets the whole thing, and Landon gets his clean
redacted copy of his own board lesson (reported directly: "i also want to see
print to pdf from landon, students board... since its text is a bit different
and doesnt contain the answer key and parent stuff"). The redaction is proven
in `tests/test_export.py` by the student cut of a lesson coming out materially
smaller than the parent cut of the same lesson.

## "This Week" becomes "Mission Control"

Reported directly: "for the parent tab 'this week' dont think thats names
appropriatley. That function is the main planner." It is -- Friday review plus
planning several weeks ahead from one screen is the app's main planning
surface, not a this-week-only view. The page file is now
`pages/14_Mission_Control.py` (Streamlit takes the sidebar label from the
filename), titled **🚀 Mission Control**, and `_PARENT_ONLY_PAGES`'s nav-hide
slug and Home's "see **Mission Control**" pointers moved with it. Nothing about
what the page *does* changed -- only its name.

## Board cards carry their own detail, on both boards

Reported directly against Landon's board: "life skill and big project arent
loading in the board correctly with the lesson or steps." On his read-only
board (`interactive=False`) every parent-only affordance is stripped -- the
move control and the "View full details" deep link -- which had left a
life-skill card showing only its category and a project-step or travel card
opening to a completely empty body. `_render_board_detail` now renders what a
card actually *is* -- the skill/step's own `description` and `materials`, a
step's pace, a trip's status prompt -- inside the expander regardless of
`interactive`, so the content he's meant to read is on both boards while the
planning controls stay parent-only above it.

## Per-card time and a per-day total on the board

Reported directly: "i want to see at the block level, the total time for each
and quick sum of total for the day in the board views to ensure balance and not
too heavy or too light days." `board_item_minutes(kind, item)` gives each story
a minutes estimate -- a lesson's own `estimated_minutes` (else the sum of its
activities' minutes, else its credited minutes), a travel entry's writing +
social-studies credit, and a round, tunable per-kind block
(`config.BOARD_BLOCK_MINUTES`) for the rest, which carry no stored duration.
Every card wears its own estimate on the right of its colored tag bar (`≈45m`),
visible open or collapsed, and each day's header sums the cards beneath it
(`Aug 31 · ≈2h 15m`) -- one glance tells a parent whether a day is packed or
light. They're estimates for balancing a week, shown with a `≈`, never a claim
of exact time; the block defaults live in one config dict to tune.

**And the estimate is editable, sprint-points style.** Reported directly: "can
we just make that value editable by parent... just like point scorng in
sprints." Each of the six board story types gained a nullable `estimate_minutes`
column (added by `_ensure_column`, so every existing row keeps its old
behavior), and every board card on the *parent* side carries a compact "⏱️
Estimate (min)" number input, pre-filled with the card's current effective
estimate. Saving a number stores the parent's own override
(`db.set_board_estimate`); setting it to 0 clears back to the default.
`board_item_minutes` reads that override first, so the card's tag and the day's
total both re-sum from the parent's number on the next run -- the day header is
the balance dial. The editor is parent-only (`interactive`); Landon's board
still just shows the estimates, never edits them.

## The board and Home agree about today; the date is on Home

Reported directly against Landon's board: "there is not assigned work today for
landon on the board but his home screen shows different?" The cause was a real
split between two views of "today." A lesson generated **on the fly** from a
subject page carries no `planned_for`/`week_start`, so `weekly.board_for_week`
placed it on no day column -- yet Home's own daily roster still listed it,
because `due_lessons` treats an undated open lesson as due right now. So Home
showed today's work while the board's Today column sat empty.

Two coordinated fixes close the gap. First, at the source: an on-demand lesson
is now **scheduled for today the moment it's generated**
(`db.schedule_lesson_today_if_unscheduled`, called from `generate_and_log`), so
it's genuine today-scheduled work -- it lands on the board's Today column by the
normal day-placement path and shows on Home's roster, the same day, because it
finally has a day. A no-op once a lesson already has one, so it never overrides
a batch-planned schedule. Second, as a safety net for any lesson that predates
that (already sitting undated in the database), `board_for_week` also surfaces
still-open, undated lessons on today's column (newest-per-subject, to match
Home's one-row-per-subject roster) -- but only when today is actually one of the
five day columns on screen, so a past or future week's board still shows that
week's own plan. Between the two, whatever counts as today's work on Home is
the same as what's on the board's Today. The student board's caption dropped its
old "generated on the fly still shows up on Today, not here" hedge, since that's
no longer true. (After pulling these changes, restart the app so a running
instance picks them up.)

And, reported in the same breath: "on the home screen, can we add the date for
landon to see somewhere." His greeting now carries the full weekday + date
(`📅 Tuesday, September 1, 2026`) right under "Hi Landon 👋", so he always knows
what day it is and which day's work he's looking at.

## Landon's board is where he does the work, not just sees it

Two reports, one surface. First: a writing activity on his board "should be a
text input box for that writing assignment and upload file." Second: from his
board he should "view full lesson for anything thats in view there. backlog or
assigned a date... just view the full lesson but without the parent answr keys."

The "View full lesson" dialog on his board is now the interactive student
lesson, not a read-only peek. In student view it hands `render_lesson` the
`db`/`lesson_id`/`metadata`/`student` (and the comic layout, so activities open
rather than hide in a collapsed expander), so a writing activity shows its real
response box + Word-doc upload + "Save draft"/"Submit for review" right there —
the same flow the subject page has always had, now reachable from the board.
It stays student-safe throughout: `render_lesson` still gates the assessment and
quiz answer key on `is_parent()`, and the Print-to-PDF button hands him the
redacted cut. The parent's own board keeps the plain preview (with the answer
key), since `db` is passed only in student view.

And the board now shows the **Product Backlog** on his side too — a read-only
"📋 Not scheduled yet" section under the day grid (shared `render_board_backlog`,
`interactive=False`), so a parked lesson is in view with its own View-full-lesson
button, not just the ones pinned to a day. `render_board_backlog` is the same
helper the parent's Mission Control board uses, factored out of that page so both
boards render the backlog one way.

## Little daily delights on his Home

Once the compliance "shell" was solid, the ask turned to fun: "what are little
things i could put in there for his day to make this fun." A first batch of
quick wins, all on his Today view, all low-stakes flavor rather than another
assignment:

- **A rotating, on-theme greeting** under his name (`compass.daily`), leaning
  into the compass/navigation theme — "New day, new territory," "Let's chart
  the course."
- **A week progress gauge** at the top — "⚡ 3 of 8 lessons done this week —
  keep it rolling!" — reading his own `student_done_on` signal so it fills in
  the moment he finishes something, not when a parent logs hours.
- **A 🧠 Brain Break card** at the bottom: a riddle he guesses before tapping
  "Reveal the answer," the word of the day (with a "use it in a sentence"
  nudge), and a history flashback.
- **Confetti** (`st.balloons()`) the first time each day he's cleared his part
  of the day's lessons — every subject either approved or turned in — fired
  once per day, session-gated.

All the content rotates deterministically by date (same pattern as the fun
fact): the same pick holds all day so it doesn't shuffle on a rerun, and
changes morning to morning, with no external API. The history entries are
deliberately a rotating set of real, well-known moments framed as a
"flashback" rather than pinned to the exact calendar date — that would need
365 date-accurate events and invite errors. The lists live in `compass/daily.py`
and are one edit to extend. The **fun fact of the day** now rides in that same
Brain Break card (reported: "move it and just add it to the brain break
container") rather than a standalone header card.

## XP, levels, and a travel passport

The next tier of fun turns what he already does into visible progress:

- **XP + a level bar** (`compass.xp`) — everything he finishes earns points (a
  finished lesson, a passed quiz, a life skill or coding module, a written-up
  trip, a choice topic, a mastered math skill), summed **live from his own
  completion signals** rather than a stored score, so it can never drift and
  never waits on a parent to log hours. A rank climbs the compass/explorer theme
  (Rookie Navigator → Scout → Pathfinder → … → Legend of the Map) and a bar
  fills toward the next level. It sits as a top banner across every Home view,
  paired with his streak; all point values and the level span are tunable in
  config.
- **XP has a cost, and unlocks real rewards.** Asked directly whether he should
  *lose* XP for returned work and earn rewards ("movie night, ice cream sundae
  party") for a high cumulative total — both, made concrete. Every time a lesson
  is sent back for a redo docks `XP_SENT_BACK_PENALTY` (per bounce, counted off
  the feedback trail), the one thing that costs XP; the total is floored at zero
  so a rough patch reads as "start climbing," never as a negative. The penalty is
  deliberately modest (about half a lesson's worth) and shown factually on the
  card ("−10 XP from lessons sent back — nail it the first time"), a real
  consequence rather than a scolding. `XP_REWARDS` is a ladder of cumulative-XP
  milestones (movie night → sundae run → sleepover → sundae party → a day trip);
  the XP card shows the next one and how far off it is, plus what's already
  unlocked. The app only tracks the milestones — the parent decides when to
  actually deliver the reward. `xp.rewards_for_total`/`xp.next_reward` compute it.
  The `XP_REWARDS` config is only the *default* ladder: a parent edits the whole
  list — thresholds, emoji, names, add/remove rows — in a live table on the
  parent Home ("🎁 XP rewards he can unlock", `render_xp_reward_editor`), saved to
  the `xp_rewards` setting via `xp.set_reward_ladder` and read back by
  `xp.reward_ladder` (which falls back to the config defaults if the setting is
  empty or malformed). The student XP card reads the same ladder, so an edit is
  what he sees next load; **Reset to defaults** clears it back to config.
- **A 🗺️ Travel Passport** — the Travel Journal already tracks which states and
  national parks he's visited; `render_travel_passport` surfaces it as a
  filling-in collection ("2 of 50 states explored · 2 parks stamped", a stamp
  icon per park). Shown only once he has any travel entries, so it never sits
  empty, and it nudges him to write up an assigned-but-unfinished trip to earn
  its stamp.

## Grading in place, and one parent hub

The parent's review kept getting rebuilt toward the same goal: read his actual
work and his response together, then approve it or push it back, without
hunting. Three moves got it there.

**The review is inline (`render_lesson_review`).** The old review card showed
the overview and his answers but never the lesson body, and split the lesson
from the grading controls so a parent scrolled between them. Now the whole
lesson renders the way his own screen renders it — every activity, its
instructions and questions, answer key still held back — and directly under
each activity sits the submission it produced: his written response in a boxed
"✍️ What he turned in" panel, the quiz with his answers against the key (the
ones he missed open on their own), and the Approve / Send-back controls. One
read, top to bottom. `render_assessment_card` split into
`_render_writing_review_controls` + `_render_final_grade_decision`, which the
new renderer composes; `_render_activity_body` grew a `review_owns_response`
flag so content renders without repeating the response the controls now own.

**Finishing his last piece turns the lesson in.** Submitting a writing
response or taking the quiz each only moved its own piece; the lesson only
reached the review queue via a separate button that was easy to miss. Now
whichever piece he finishes last auto-submits the whole lesson, once the same
readiness gate the manual button uses reads it as complete
(`_maybe_auto_submit_lesson`).

**Mission Control is the one parent hub.** Review, planning, backlog, and the
hours record lived on two pages; the review, backlog, and record all fold into
Mission Control now (`pages/10_Activity_Log.py` retired). It opens on a
**Review** tab: a single prioritized queue — turned-in work open and ready to
grade, then quieter overdue / sent-back / still-planned sections — with the old
five-column schedule board dropped from review (rearranging days is the
**Board** tab's job). **Backlog** (lessons, big projects, choice topics) and
**Record** (the hours ledger + manual logging) are its own tabs. The page test
is `tests/test_mission_control_review.py`.

## Making the basics harder to skip

Three changes aimed at a student who skims the prompt, skips half the asks,
and hands in rushed mechanics.

**A math answer isn't prose.** The lesson schema lets an activity be tagged as
a written response with word/sentence requirements; the generator sometimes
put those on a numeric-answer math step, so `check_writing`'s sentence rule
rejected `42` until he typed a stray `42.` to make it count as a sentence. On
submit for a math lesson, only the not-blank check runs now
(`compass/ui.py`), fixing existing and future lessons.

**A self-check gate on the asks.** A writing activity can carry a `checklist`
-- the prompt's discrete parts broken out ("Answer all three questions", "Give
an example"). His screen renders each as a checkbox and "Submit for review"
stays locked until every one is ticked, so each requirement is something he
had to see and acknowledge, not read past. Ticks persist
(`checklist_checked` in metadata; `Database.set_activity_checklist`). The
generator emits the list when a prompt asks for more than one thing; the
parent's review shows the parts and which he ticked. This is the deterministic
half of a "did he do all of it" check -- an AI coverage verifier (confirming a
ticked box was actually done) is the natural next layer, alongside the grader.

**Coach-only grammar/structure help.** `writing_checks.writing_hints` flags the
mechanical basics he skips -- capital letters, run-on sentences, a missing end
period, lowercase "I" -- as gentle hints under the box, instantly and with no
AI call; a paragraph activity also offers a "how to structure it" shape. None
of it blocks a submission -- deeper feedback stays "Check my work" and the
parent's review.

## Tests

```bash
python -m pytest tests/ -q      # 1186 tests, ~150s, no API key needed
```

Coverage focuses where being wrong is expensive: the math graph's structure, the
compliance arithmetic, the credit-normalization guardrails, and all four
strategies' selection logic.

One environment note lives in `tests/conftest.py`: an autouse fixture stubs
`render_first_day_celebration` out for every Home-page AppTest (except
`test_ui.py`, which drives the celebration directly). The "Issue #1" first-day
cover fires on the actual first day of the school year and `st.stop()`s the rest
of Home -- exactly as intended -- but `school_year_bounds()` returns "the year
containing today," so on a machine whose clock happens to sit on that start date
the cover would otherwise intercept every AppTest that opens Home and hide the
content those tests assert on. The fixture pins Home to its steady state (cover
already seen), which is what those tests mean to exercise.

## Not built, on purpose

The orchestrator agent that balances the day across subjects. The design doc says
to build it only if juggling four agents' daily hour allocation actually gets
unwieldy — that's a decision to make with a term of real usage data, not now.
