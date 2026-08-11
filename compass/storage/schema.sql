-- Compass local storage. Single-file SQLite; no external service required.
--
-- Design notes:
--   * `activities` holds *logged* instructional time. Its `minutes` column is
--     the single source of truth for the 1,000-hour WA floor.
--   * `activity_subject_credits` holds the multi-subject tagging. Credits may
--     sum to MORE than the activity's minutes (that is the whole point of Tier
--     2 folding) — so per-subject coverage reads from here, and total
--     instructional hours read from `activities.minutes`. Never sum credits to
--     get a total; that double-counts.
--   * `lessons` holds agent output that has not necessarily happened yet.
--     Completing a lesson creates an activity + credits.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS students (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    grade             TEXT NOT NULL,
    age               INTEGER,
    interests         TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Math: mastery over the hand-authored prerequisite graph.
-- The graph itself lives in code (compass/curriculum/math_graph.py) so it is
-- versioned and auditable for compliance documentation. Only *mastery state*
-- is data.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS skill_mastery (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    skill_id    TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('not_started', 'in_progress', 'mastered')),
    score       REAL,
    assessed_on TEXT,
    notes       TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (student_id, skill_id)
);

-- ---------------------------------------------------------------------------
-- Spiderweb exploration, shared by Science and History.
-- A node is a topic; `parent_id` is the branch it grew from. Unexplored nodes
-- are the candidate pool the spiderweb strategy draws its next topic from.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS topic_web (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    agent       TEXT NOT NULL,
    topic       TEXT NOT NULL,
    rationale   TEXT NOT NULL DEFAULT '',
    location    TEXT NOT NULL DEFAULT '',
    parent_id   INTEGER REFERENCES topic_web(id) ON DELETE SET NULL,
    depth       INTEGER NOT NULL DEFAULT 0,
    explored_on TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_topic_web_pool
    ON topic_web (student_id, agent, explored_on);

-- ---------------------------------------------------------------------------
-- English: what he is currently reading, plus vocabulary spaced repetition.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS books (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    author       TEXT NOT NULL DEFAULT '',
    reading_level TEXT NOT NULL DEFAULT '',
    total_pages  INTEGER,
    current_page INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'reading'
                 CHECK (status IN ('reading', 'finished', 'abandoned')),
    started_on   TEXT,
    finished_on  TEXT,
    notes        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Leitner-box spaced repetition. box 1 = review tomorrow, escalating to box 5.
CREATE TABLE IF NOT EXISTS vocabulary (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id     INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    word           TEXT NOT NULL,
    definition     TEXT NOT NULL DEFAULT '',
    source_book_id INTEGER REFERENCES books(id) ON DELETE SET NULL,
    box            INTEGER NOT NULL DEFAULT 1 CHECK (box BETWEEN 1 AND 5),
    next_review_on TEXT NOT NULL,
    times_correct  INTEGER NOT NULL DEFAULT 0,
    times_missed   INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (student_id, word)
);

CREATE INDEX IF NOT EXISTS idx_vocab_due
    ON vocabulary (student_id, next_review_on);

-- ---------------------------------------------------------------------------
-- Generated lessons (agent output), and logged activities (actual hours).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS lessons (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    agent        TEXT NOT NULL,
    subject      TEXT NOT NULL,
    topic        TEXT NOT NULL,
    title        TEXT NOT NULL,
    strategy     TEXT NOT NULL DEFAULT '',
    rationale    TEXT NOT NULL DEFAULT '',
    payload      TEXT NOT NULL,          -- full lesson JSON as returned by the agent
    metadata     TEXT NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'planned'
                 CHECK (status IN ('planned', 'completed', 'skipped')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_lessons_student
    ON lessons (student_id, created_at DESC);

CREATE TABLE IF NOT EXISTS activities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id      INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    lesson_id       INTEGER REFERENCES lessons(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    tier            TEXT NOT NULL CHECK (tier IN ('core', 'folded', 'choice', 'life_skills')),
    primary_subject TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'manual',  -- agent key, 'manual', 'choice', 'life_skills'
    minutes         INTEGER NOT NULL CHECK (minutes > 0),
    occurred_on     TEXT NOT NULL,
    location        TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_activities_student_date
    ON activities (student_id, occurred_on);

CREATE TABLE IF NOT EXISTS activity_subject_credits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    subject     TEXT NOT NULL,
    minutes     INTEGER NOT NULL CHECK (minutes > 0),
    UNIQUE (activity_id, subject)
);

-- No index on `subject` alone: nothing ever queries credits that way. The only
-- read is `WHERE activity_id IN (...)` from list_activities, which the UNIQUE
-- (activity_id, subject) constraint's implicit index already serves. Dropped
-- rather than left in place, since an unused index still costs a write on every
-- credit inserted. `migrate()` re-runs this file on every open, so the DROP is
-- how existing databases shed it too.
DROP INDEX IF EXISTS idx_credits_subject;

-- ---------------------------------------------------------------------------
-- Tier 3 — his choice. No prerequisite logic, no agent. He curates it; the
-- parent approves. Compass only tracks it.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS choice_topics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL DEFAULT '',
    credit_subject TEXT NOT NULL DEFAULT 'occupational_education',
    status      TEXT NOT NULL DEFAULT 'proposed'
                CHECK (status IN ('proposed', 'approved', 'active', 'done', 'declined')),
    proposed_on TEXT NOT NULL DEFAULT (date('now')),
    decided_on  TEXT,
    parent_note TEXT NOT NULL DEFAULT ''
);

-- ---------------------------------------------------------------------------
-- Core life skills — parent-maintained checklist. Deliberately not agentic.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS life_skills (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    category     TEXT NOT NULL DEFAULT 'General',
    title        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    materials    TEXT NOT NULL DEFAULT '',  -- what it takes to finish -- "You'll need:" on the card
    active       INTEGER NOT NULL DEFAULT 1,  -- unlocked for the student view; parent-controlled
    credit_subject TEXT NOT NULL DEFAULT 'occupational_education',
    completed_on TEXT,
    notes        TEXT NOT NULL DEFAULT '',
    sort_order   INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Washington's annual Declaration of Intent to homeschool (RCW 28A.200.010) --
-- a once-a-year filing with the local school district, unrelated to hours or
-- subject coverage. `due_on` is the actual computed deadline date for one
-- year's filing, so a new year gets a new row rather than overwriting last
-- year's -- a family that filed for 2025 shouldn't read as "filed" in 2026.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS declarations_of_intent (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    due_on      TEXT NOT NULL,
    filed_on    TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (student_id, due_on)
);

-- ---------------------------------------------------------------------------
-- Landon's Travels -- a family travel journal, deliberately separate from
-- the Tier system for now (no hours, no subject credit). One row per trip,
-- not per state or per park: a family that returns to a favorite gets a
-- second entry, not an overwritten one. `state` is the required scope of
-- the entry; `park_key` is an optional link to a specific National Park
-- (compass.national_parks.PARKS, same string-key pattern skill_mastery.skill_id
-- uses for the math graph) for trips that included a park visit -- not every
-- trip does.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS travel_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    state       TEXT NOT NULL,
    park_key    TEXT,
    title       TEXT NOT NULL DEFAULT '',
    story       TEXT NOT NULL DEFAULT '',
    visited_on  TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_travel_entries_student
    ON travel_entries (student_id, state);
