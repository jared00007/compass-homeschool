# Compass — Homeschool Curriculum Agents

Multi-agent curriculum system for a homeschooled 8th grader (age 13), built around
two constraints treated as first-class rather than afterthoughts: **Washington
homeschool compliance** and **the student's freedom of choice**.

This is a fresh, standalone build — local SQLite, a Streamlit UI, and four
subject agents on the Anthropic API.

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

**Rule of thumb, carried through:** use the least agency that solves the problem.
Tier 3 and Core Life Skills are plain CRUD features with no agent at all, and the
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
- Duplicates merged, unknown subjects dropped, total time reconciled to the
  activity list

Every adjustment surfaces in the UI as a warning rather than happening silently.

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
parent-maintained checklist, deliberately not agentic. In practice this is where
most Health and Occupational Education coverage genuinely comes from.

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
    framework.py             LessonAgent, AgentSpec, credit normalization
    strategies.py            the four next-topic strategies
    llm.py                   Anthropic client, lesson JSON schema, error handling
    prompts.py               shared user-prompt assembly
    {math,science,english,history}_agent.py
  curriculum/math_graph.py   the hand-authored 50-node graph
  compliance/dashboard.py    WA hour/subject/tier reporting
  costs.py                   token usage → dollars, per agent and projected
  backup.py                  daily snapshots, retention, and restore
  storage/                   SQLite schema + repository
  subjects.py                the 11 WA subjects and Tier 2 folding rules
  config.py                  statutory constants vs. editable family policy
tests/                       87 tests, no API key required
```

`compass/` knows nothing about Streamlit — the agents, storage, and compliance
layers stay testable and reusable if the UI is ever replaced.

---

## Model configuration

`claude-opus-5` with adaptive thinking and `effort: high`. Lessons come back as
**structured output** against a JSON schema, so the compliance-critical fields
are guaranteed well-formed rather than parsed out of prose. Science and History
additionally get Anthropic's server-side **web search** so location-specific
lessons are grounded in real facts.

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

## Tests

```bash
python -m pytest tests/ -q      # 87 tests, ~2s, no API key needed
```

Coverage focuses where being wrong is expensive: the math graph's structure, the
compliance arithmetic, the credit-normalization guardrails, and all four
strategies' selection logic.

## Not built, on purpose

The orchestrator agent that balances the day across subjects. The design doc says
to build it only if juggling four agents' daily hour allocation actually gets
unwieldy — that's a decision to make with a term of real usage data, not now.
