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
                             Activity Log, Compliance, Student Profile
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
drift. The flag changes wording and adds a pointer to the weight settings; it never
changes a number.

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

## Tests

```bash
python -m pytest tests/ -q      # 964 tests, ~70s, no API key needed
```

Coverage focuses where being wrong is expensive: the math graph's structure, the
compliance arithmetic, the credit-normalization guardrails, and all four
strategies' selection logic.

## Not built, on purpose

The orchestrator agent that balances the day across subjects. The design doc says
to build it only if juggling four agents' daily hour allocation actually gets
unwieldy — that's a decision to make with a term of real usage data, not now.
