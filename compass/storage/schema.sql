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
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per interest, not one free-text blob -- lets the Student Profile
-- page add/remove them individually instead of hand-editing a comma list in
-- a cramped textarea. Read by every agent's system prompt (joined back into
-- a comma-separated string via Database.interests_text).
CREATE TABLE IF NOT EXISTS student_interests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_student_interests_student ON student_interests (student_id);

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

-- `term` tags a book to a half of the school year ('first_half' /
-- 'second_half') for a family running two books, one per half, picked ahead
-- of time. Status 'upcoming' is a second-half book queued but not yet the
-- one the English agent reads from -- current_book() only ever returns a
-- 'reading' row, so an upcoming book sits inert until promote_upcoming_book
-- moves it over. Neither is required: a book added with no term and
-- status 'reading' (the old default) behaves exactly as it always has.
CREATE TABLE IF NOT EXISTS books (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    author       TEXT NOT NULL DEFAULT '',
    reading_level TEXT NOT NULL DEFAULT '',
    total_pages  INTEGER,
    current_page INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'reading'
                 CHECK (status IN ('reading', 'finished', 'abandoned', 'upcoming')),
    term         TEXT CHECK (term IN ('first_half', 'second_half')),
    started_on   TEXT,
    finished_on  TEXT,
    notes        TEXT NOT NULL DEFAULT '',
    ai_summary   TEXT NOT NULL DEFAULT '',  -- parent-drafted-with-AI blurb, shown to him
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
    -- planned: assigned, still with him. submitted: he's turned it in,
    -- waiting on a parent. needs_revision: sent back, his turn again.
    -- completed: approved and logged. skipped: a parent's call, not his.
    status       TEXT NOT NULL DEFAULT 'planned'
                 CHECK (status IN ('planned', 'submitted', 'needs_revision', 'completed', 'skipped')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_lessons_student
    ON lessons (student_id, created_at DESC);

-- Every graded attempt at a lesson's in-app quiz, not just the latest.
-- lessons.metadata.quiz_result (Database.record_quiz_result) still holds a
-- summary of the most recent attempt for the places that only ever cared
-- about "today's score" (Home, This Week, Activity Log); this is the full
-- history behind it -- how many tries, each one's score, and which
-- questions were missed on each -- which used to live only in the
-- browser's own session state and vanished the moment that session ended.
CREATE TABLE IF NOT EXISTS quiz_attempts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id       INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    student_id      INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    correct         INTEGER NOT NULL,
    total           INTEGER NOT NULL,
    passed          INTEGER NOT NULL,
    detail          TEXT NOT NULL DEFAULT '[]',  -- JSON: [{question, choices, correct_index, pick, explanation}]
    -- Wall-clock time from opening the quiz's own collapsed container (a
    -- deliberate action, unlike the lesson content around it) to submitting --
    -- NULL for an attempt where that open moment was never captured (session
    -- state lost to a refresh mid-quiz, say), not a stand-in for zero.
    duration_seconds INTEGER,
    attempted_on    TEXT NOT NULL DEFAULT (date('now')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_quiz_attempts_lesson
    ON quiz_attempts (lesson_id, created_at);

CREATE INDEX IF NOT EXISTS idx_quiz_attempts_student
    ON quiz_attempts (student_id, created_at DESC);

-- Every saved version of a writing activity's response, not just the
-- current one. lessons.metadata.writing_responses (Database.
-- save_writing_response) still holds the current text for the places that
-- only ever needed "what he's written so far" (render_lesson's read-back,
-- the assessment card); this is the version history behind it, the same
-- "never overwrite, keep every attempt" choice quiz_attempts already made.
CREATE TABLE IF NOT EXISTS writing_response_versions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id      INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    activity_index INTEGER NOT NULL,
    student_id     INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    text           TEXT NOT NULL,
    saved_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_writing_response_versions_lesson
    ON writing_response_versions (lesson_id, activity_index, saved_at);

-- ---------------------------------------------------------------------------
-- Courses -- grades 6-12 credit documentation. Sumner-Bonney Lake requires,
-- per course counted toward a diploma: a description, goals/objectives, an
-- outline, a log of instructional time (150 hours = 1 credit), completed
-- assignments/assessments, a description of how performance is assessed, and
-- a final grade (converted to Pass/Fail on the transcript). A course is a
-- named container a parent points at a slice of already-logged activities
-- (matched by subject + date range, then hand-adjustable) rather than a
-- separate place to re-enter everything -- the activities/lessons already
-- carry the assignment and assessment detail this packet needs.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS courses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id     INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    title          TEXT NOT NULL,
    credit_subject TEXT NOT NULL,
    grade_level    TEXT NOT NULL DEFAULT '',
    description    TEXT NOT NULL DEFAULT '',
    goals          TEXT NOT NULL DEFAULT '',
    outline        TEXT NOT NULL DEFAULT '',
    credit_value   REAL NOT NULL DEFAULT 1.0,
    start_date     TEXT NOT NULL,
    end_date       TEXT NOT NULL,
    final_grade    TEXT NOT NULL DEFAULT '',
    pass_fail      TEXT CHECK (pass_fail IN ('pass', 'fail')),
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_courses_student
    ON courses (student_id, start_date DESC);

CREATE TABLE IF NOT EXISTS activities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id      INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    lesson_id       INTEGER REFERENCES lessons(id) ON DELETE SET NULL,
    course_id       INTEGER REFERENCES courses(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    tier            TEXT NOT NULL CHECK (tier IN ('core', 'folded', 'choice', 'life_skills', 'projects', 'wellness')),
    primary_subject TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'manual',  -- agent key, 'manual', 'choice', 'life_skills'
    minutes         INTEGER NOT NULL CHECK (minutes > 0),
    occurred_on     TEXT NOT NULL,
    location        TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_activities_student_date
    ON activities (student_id, occurred_on);

-- No `idx_activities_course` here: a database created before Courses existed
-- has an `activities` table without the column yet, and `CREATE TABLE IF NOT
-- EXISTS` above is a no-op against it, so an index statement running in this
-- same script would fail before `_ensure_column` gets a chance to add the
-- column. Created in Python, in `migrate()`, right after that call instead.

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
    scheduled_for TEXT,  -- ISO date a parent assigned this skill to; NULL = do whenever
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
    favorite_moment TEXT NOT NULL DEFAULT '',
    would_return    TEXT NOT NULL DEFAULT '',
    visited_on  TEXT NOT NULL,
    -- The same review-gate vocabulary lessons use, not a bespoke one:
    -- 'planned' is a parent-assigned stub with no story yet, 'submitted'
    -- is waiting on a parent to review, 'needs_revision' was sent back,
    -- 'completed' is approved (and has earned its flat credit). Existing
    -- rows from before this column existed default to 'completed' --
    -- there's nothing to retroactively review about a trip already
    -- written up and sitting in the family record.
    status      TEXT NOT NULL DEFAULT 'completed'
                CHECK (status IN ('planned', 'submitted', 'needs_revision', 'completed')),
    scheduled_for TEXT,  -- ISO date a parent assigned this trip to be written up; NULL = whenever
    revision_note TEXT NOT NULL DEFAULT '',  -- parent's note when sending an entry back
    parent_feedback TEXT NOT NULL DEFAULT '',  -- parent's note when approving -- praise, not a fix request
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_travel_entries_student
    ON travel_entries (student_id, state);

-- ---------------------------------------------------------------------------
-- Check-In -- a daily feelings journal. Every check-in is its own row (a
-- second one the same day sits alongside the first rather than overwriting
-- it), a required feeling pick plus an optional note about anything at all,
-- not just school. Fully visible to a parent by design -- see
-- pages/8_Check_In.py's own banner, which tells him that plainly rather
-- than letting him assume privacy.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS journal_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    entry_date  TEXT NOT NULL,
    feeling     TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_journal_entries_student
    ON journal_entries (student_id, entry_date);

-- ---------------------------------------------------------------------------
-- Big Projects -- parent-curated, multi-step creative projects (the Lego
-- stop-motion film being the first). Distinct from Core Life Skills: a life
-- skill is one self-contained lesson, a project is a whole pipeline of
-- ordered steps that build toward one finished thing, run agile-sprint style
-- -- each step small enough to actually finish in a sitting, in a fixed
-- order because step 4 usually depends on step 3 being done.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS big_projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    vision      TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    shelved     INTEGER NOT NULL DEFAULT 0,  -- "not an interest" -- parent-only, reversible
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS project_steps (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id     INTEGER NOT NULL REFERENCES big_projects(id) ON DELETE CASCADE,
    sort_order     INTEGER NOT NULL DEFAULT 0,
    title          TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    materials      TEXT NOT NULL DEFAULT '',
    credit_subject TEXT NOT NULL DEFAULT 'occupational_education',
    -- A pace, not a deadline: a loose day range shown to set the
    -- expectation that a step is meant to take a while, on purpose --
    -- there's no due_on anywhere on this table, and that's intentional.
    min_days       INTEGER NOT NULL DEFAULT 1,
    max_days       INTEGER NOT NULL DEFAULT 1,
    completed_on   TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_project_steps_project
    ON project_steps (project_id, sort_order);

-- ---------------------------------------------------------------------------
-- District documents -- a parent's own paperwork (the district's Declaration
-- of Intent packet, its Granting Credit form, whatever else) stored right in
-- the family's own database rather than a separate uploads folder to keep
-- track of. One document per (student, category); uploading again replaces
-- it, on the theory that last year's filing packet is rarely worth keeping
-- once this year's is in hand.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS district_documents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    category     TEXT NOT NULL,
    filename     TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/pdf',
    content      BLOB NOT NULL,
    uploaded_on  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (student_id, category)
);

-- ---------------------------------------------------------------------------
-- Morning routine log -- which stretch/breathing/mindfulness routine
-- (compass/morning_routines.py) he did to start the day. One per student per
-- day: unlike Check-In, a morning routine is fundamentally a single event,
-- so a second pick the same day replaces the first rather than stacking.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS morning_routine_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    entry_date   TEXT NOT NULL,
    routine_key  TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (student_id, entry_date)
);

-- ---------------------------------------------------------------------------
-- Vocabulary review log -- a real, persisted "he reviewed his words today"
-- fact. The Concentration game itself (compass.ui.render_vocab_memory) only
-- ever tracked a streak/reviewed-count in session state, gone the moment the
-- browser session ended, so there was nothing here or on Home's own "Today"
-- checklist to confirm it actually happened, and nothing prompting him to
-- treat it as a real, completable task the way a lesson's own "I'm done for
-- today" button does. One per student per day, same shape as
-- morning_routine_log, for the same reason: a review session is one event
-- for the day, not something that stacks.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS vocab_review_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    entry_date   TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (student_id, entry_date)
);

-- ---------------------------------------------------------------------------
-- Friday plan items -- Friday is deliberately never a new-content day (see
-- compass/weekly.py), so the Week grid's Friday cell has always shown a
-- fixed Big Project + Travel Journal pairing. This is how a parent replaces
-- that fixed pairing, one Friday at a time, with any mix of the
-- standardized options in compass.ui.FRIDAY_PLAN_KINDS (or a free-text
-- 'custom' one) -- log five old trips, work the project, whatever that
-- particular Friday calls for. A Friday with no rows here still falls back
-- to the original fixed pairing, so nothing about an already-planned week
-- changes just because this table now exists.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS friday_plan_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    plan_date   TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN
                ('big_project', 'travel_new', 'travel_catchup',
                 'life_skills', 'choice_topics', 'custom')),
    label       TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_friday_plan_items_date
    ON friday_plan_items (student_id, plan_date);
