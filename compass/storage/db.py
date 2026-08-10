"""SQLite storage layer.

One `Database` object wraps a connection and exposes typed-ish repository
methods. Every method that writes commits immediately — this is a single-family,
single-writer app, so there is no benefit to holding transactions open across UI
interactions.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Sequence

from compass import config

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# The starter life-skills checklist: (category, title, credit_subject, description,
# materials). Written, not agent-generated -- plain, casual, kid-facing, matching
# how Tier 1 lesson content is written. `materials` is the short "what you'll need"
# list the card shows under the story.
#
# Lives at module level (rather than inline in `seed_life_skills`) so
# `_backfill_life_skill_content` can share the same source of truth -- a family
# whose checklist was seeded before this text existed (or before `materials`
# existed) needs the same content, not a second copy of it that can drift.
STARTER_LIFE_SKILLS: Sequence[tuple[str, str, str, str, str]] = (
    ("Money", "Build and follow a monthly budget", "occupational_education",
     "Figure out what money's coming in and what's going out, then make a "
     "simple plan so you don't run out before the month does. Set some "
     "categories, guess your spending, then check back and see how close "
     "you got.",
     "pencil and paper (or a spreadsheet), one real month of numbers"),
    ("Money", "Open and reconcile a bank account", "occupational_education",
     "You'll open a real account (a parent's on it too) and learn to check "
     "it against your own math -- what you think you have vs. what the "
     "bank says you have. Catching the difference is the actual skill.",
     "a parent, ID, ~$20 to open with"),
    ("Money", "Understand a paycheck: gross, net, withholding", "occupational_education",
     "A paycheck has two numbers that matter: what you earned and what you "
     "actually get to keep. Work through a sample stub and figure out "
     "where the rest of it goes.",
     "a sample pay stub, a calculator"),
    ("Cooking", "Plan and cook a full meal for the family", "health",
     "Pick a meal, shop for it (or use what's in the kitchen), and cook "
     "the whole thing start to finish -- timing included, so everything's "
     "ready at the same time.",
     "a recipe, a grocery run, about 90 minutes"),
    ("Cooking", "Read nutrition labels and plan a balanced week", "health",
     "Nutrition labels look like a wall of numbers until you know which "
     "three or four actually matter. Use them to plan a week of meals "
     "that aren't just convenient -- that are actually decent for you.",
     "a few labels from the pantry, a week's meal list"),
    ("Cooking", "Kitchen safety and safe food handling", "health",
     "The stuff that keeps you from getting sick or hurt: washing hands "
     "right, not cross-contaminating raw meat, knowing when food's gone "
     "bad, and using a knife without losing a finger.",
     "a kitchen, a parent watching once"),
    ("Vehicle", "Check and top off oil, coolant, washer fluid", "occupational_education",
     "The three fluids you should check before anyone tells you your car's "
     "in trouble. Takes ten minutes and can save you a much worse day "
     "later.",
     "the owner's manual, 10 minutes, the car"),
    ("Vehicle", "Check tire pressure and change a tire", "occupational_education",
     "Two skills in one: reading a tire gauge so you know when a tire's "
     "actually low, and swapping one out on the side of the road if you "
     "have to.",
     "a tire gauge, the spare, the jack and lug wrench"),
    ("Vehicle", "Jump-start a vehicle safely", "occupational_education",
     "A dead battery isn't a big deal if you know which cable goes where, "
     "and in what order. Get it wrong and you can actually fry something "
     "-- that's why the order matters.",
     "jumper cables, a second running car"),
    ("Communication", "Write a clear, polite email to an adult", "language",
     "Emails to teachers, coaches, or businesses have their own rules -- "
     "not too casual, not stiff either, and always saying exactly what "
     "you need in the first two lines.",
     "a real email to send, 15 minutes"),
    ("Communication", "Make a phone call to schedule an appointment", "language",
     "An actual phone call, not a text. Practice saying who you are, what "
     "you need, and getting a real time booked -- without freezing up.",
     "a real place to call, your calendar"),
    ("Communication", "Introduce yourself and shake hands", "health",
     "Look someone in the eye, say your name clearly, and shake hands "
     "like you mean it. Small thing, but it's the first impression every "
     "single time.",
     "a person to practice on"),
    ("Home", "Do laundry start to finish", "occupational_education",
     "Sorting, washing, drying, folding -- the whole loop, no help. "
     "Including not turning anyone's white shirt pink.",
     "a full hamper, the washer and dryer"),
    ("Home", "Basic first aid and when to call for help", "health",
     "Cuts, burns, sprains -- what you can handle yourself, and where "
     "the line is where you stop and call 911 or a parent instead.",
     "a first aid kit"),
    ("Home", "Read a map and navigate without GPS", "social_studies",
     "Your phone dies, or you're somewhere with no signal -- can you "
     "still get where you're going with an actual map? That's the whole "
     "skill.",
     "a paper map or atlas, a real trip to plan"),
)

# Leitner intervals in days, indexed by box number (1-5).
LEITNER_INTERVALS = {1: 1, 2: 3, 3: 7, 4: 16, 5: 35}


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or config.DEFAULT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


def _row(cursor: sqlite3.Cursor) -> dict[str, Any] | None:
    row = cursor.fetchone()
    return dict(row) if row else None


class Database:
    def __init__(self, db_path: str | Path | None = None):
        self.path = Path(db_path or config.DEFAULT_DB_PATH)
        self.conn = connect(self.path)
        self.migrate()

    # -- schema ---------------------------------------------------------------

    def migrate(self) -> None:
        self.conn.executescript(SCHEMA_PATH.read_text())
        # `CREATE TABLE IF NOT EXISTS` above only covers a table's first-ever
        # creation -- a family's existing life_skills table predates the
        # `materials` column, so it needs adding here instead.
        self._ensure_column("life_skills", "materials", "TEXT NOT NULL DEFAULT ''")
        self._backfill_life_skill_content()
        for key, value in config.DEFAULT_SETTINGS.items():
            self.conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value)
            )
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        existing = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def _backfill_life_skill_content(self) -> None:
        """Fill in `description`/`materials` for starter skills seeded before
        that text existed -- `seed_life_skills` only ever runs once per
        student, so a checklist seeded in an earlier build stays blank
        forever otherwise. Matched by exact title, and only when the field is
        still blank, so a parent's own edit is never overwritten."""
        for _, title, _, description, materials in STARTER_LIFE_SKILLS:
            self.conn.execute(
                "UPDATE life_skills SET description = ? "
                "WHERE title = ? AND description = ''",
                (description, title),
            )
            self.conn.execute(
                "UPDATE life_skills SET materials = ? "
                "WHERE title = ? AND materials = ''",
                (materials, title),
            )

    # -- settings -------------------------------------------------------------

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = _row(self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)))
        if row is None:
            return default if default is not None else config.DEFAULT_SETTINGS.get(key)
        return row["value"]

    def get_int_setting(self, key: str) -> int:
        raw = self.get_setting(key)
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return int(float(config.DEFAULT_SETTINGS[key]))

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        self.conn.commit()

    # -- students -------------------------------------------------------------

    def list_students(self) -> list[dict[str, Any]]:
        return _rows(self.conn.execute("SELECT * FROM students ORDER BY id"))

    def get_student(self, student_id: int) -> dict[str, Any] | None:
        return _row(self.conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)))

    def create_student(
        self, name: str, grade: str, age: int | None = None, interests: str = ""
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO students (name, grade, age, interests) VALUES (?, ?, ?, ?)",
            (name, grade, age, interests),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_student(self, student_id: int, **fields: Any) -> None:
        allowed = {"name", "grade", "age", "interests"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        assignments = ", ".join(f"{k} = ?" for k in updates)
        self.conn.execute(
            f"UPDATE students SET {assignments} WHERE id = ?",
            (*updates.values(), student_id),
        )
        self.conn.commit()

    def ensure_default_student(self) -> dict[str, Any]:
        """First-run convenience: seed the student described in the design doc."""
        students = self.list_students()
        if students:
            return students[0]
        student_id = self.create_student(name="Student", grade="8", age=13)
        return self.get_student(student_id)  # type: ignore[return-value]

    # -- math mastery ---------------------------------------------------------

    def mastery_map(self, student_id: int) -> dict[str, dict[str, Any]]:
        rows = _rows(
            self.conn.execute("SELECT * FROM skill_mastery WHERE student_id = ?", (student_id,))
        )
        return {r["skill_id"]: r for r in rows}

    def mastered_skills(self, student_id: int) -> set[str]:
        return {
            r["skill_id"]
            for r in _rows(
                self.conn.execute(
                    "SELECT skill_id FROM skill_mastery "
                    "WHERE student_id = ? AND status = 'mastered'",
                    (student_id,),
                )
            )
        }

    def set_mastery(
        self,
        student_id: int,
        skill_id: str,
        status: str,
        score: float | None = None,
        notes: str = "",
        assessed_on: str | None = None,
    ) -> None:
        if status not in ("not_started", "in_progress", "mastered"):
            raise ValueError(f"invalid mastery status: {status}")
        self.conn.execute(
            """
            INSERT INTO skill_mastery
                (student_id, skill_id, status, score, notes, assessed_on, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(student_id, skill_id) DO UPDATE SET
                status = excluded.status,
                score = excluded.score,
                notes = excluded.notes,
                assessed_on = excluded.assessed_on,
                updated_at = datetime('now')
            """,
            (
                student_id,
                skill_id,
                status,
                score,
                notes,
                assessed_on or date.today().isoformat(),
            ),
        )
        self.conn.commit()

    # -- topic web (spiderweb strategies) -------------------------------------

    def add_web_node(
        self,
        student_id: int,
        agent: str,
        topic: str,
        rationale: str = "",
        location: str = "",
        parent_id: int | None = None,
        depth: int = 0,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO topic_web "
            "(student_id, agent, topic, rationale, location, parent_id, depth) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (student_id, agent, topic, rationale, location, parent_id, depth),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def unexplored_web_nodes(
        self, student_id: int, agent: str, location: str | None = None
    ) -> list[dict[str, Any]]:
        """Candidate next topics, location-relevant ones first, then shallowest."""
        rows = _rows(
            self.conn.execute(
                "SELECT * FROM topic_web "
                "WHERE student_id = ? AND agent = ? AND explored_on IS NULL "
                "ORDER BY depth ASC, id ASC",
                (student_id, agent),
            )
        )
        if location:
            needle = location.strip().lower()
            rows.sort(key=lambda r: 0 if needle and needle in r["location"].lower() else 1)
        return rows

    def explored_topics(self, student_id: int, agent: str) -> list[str]:
        return [
            r["topic"]
            for r in _rows(
                self.conn.execute(
                    "SELECT topic FROM topic_web "
                    "WHERE student_id = ? AND agent = ? AND explored_on IS NOT NULL "
                    "ORDER BY explored_on DESC",
                    (student_id, agent),
                )
            )
        ]

    def mark_web_node_explored(self, node_id: int) -> None:
        self.conn.execute(
            "UPDATE topic_web SET explored_on = date('now') WHERE id = ?", (node_id,)
        )
        self.conn.commit()

    def get_web_node(self, node_id: int) -> dict[str, Any] | None:
        return _row(self.conn.execute("SELECT * FROM topic_web WHERE id = ?", (node_id,)))

    def delete_web_node(self, node_id: int) -> None:
        """Drop a branch nobody intends to follow.

        Children are re-parented by the schema's ON DELETE SET NULL rather than
        cascading — a grandchild topic is still a perfectly good lesson, and
        deleting a branch shouldn't silently take a subtree with it.
        """
        self.conn.execute("DELETE FROM topic_web WHERE id = ?", (node_id,))
        self.conn.commit()

    def web_nodes(self, student_id: int, agent: str) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                "SELECT * FROM topic_web WHERE student_id = ? AND agent = ? ORDER BY id",
                (student_id, agent),
            )
        )

    # -- books ----------------------------------------------------------------

    def list_books(self, student_id: int, status: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM books WHERE student_id = ?"
        params: list[Any] = [student_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY (status = 'reading') DESC, id DESC"
        return _rows(self.conn.execute(sql, params))

    def current_book(self, student_id: int) -> dict[str, Any] | None:
        return _row(
            self.conn.execute(
                "SELECT * FROM books WHERE student_id = ? AND status = 'reading' "
                "ORDER BY id DESC LIMIT 1",
                (student_id,),
            )
        )

    def add_book(
        self,
        student_id: int,
        title: str,
        author: str = "",
        reading_level: str = "",
        total_pages: int | None = None,
        notes: str = "",
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO books "
            "(student_id, title, author, reading_level, total_pages, notes, started_on) "
            "VALUES (?, ?, ?, ?, ?, ?, date('now'))",
            (student_id, title, author, reading_level, total_pages, notes),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_book(self, book_id: int, **fields: Any) -> None:
        allowed = {
            "title",
            "author",
            "reading_level",
            "total_pages",
            "current_page",
            "status",
            "notes",
            "finished_on",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        if updates.get("status") == "finished" and "finished_on" not in updates:
            updates["finished_on"] = date.today().isoformat()
        assignments = ", ".join(f"{k} = ?" for k in updates)
        self.conn.execute(
            f"UPDATE books SET {assignments} WHERE id = ?", (*updates.values(), book_id)
        )
        self.conn.commit()

    # -- vocabulary (Leitner spaced repetition) -------------------------------

    def add_vocabulary(
        self,
        student_id: int,
        word: str,
        definition: str = "",
        source_book_id: int | None = None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO vocabulary "
            "(student_id, word, definition, source_book_id, box, next_review_on) "
            "VALUES (?, ?, ?, ?, 1, date('now', '+1 day')) "
            "ON CONFLICT(student_id, word) DO UPDATE SET "
            "  definition = CASE WHEN excluded.definition != '' "
            "               THEN excluded.definition ELSE vocabulary.definition END",
            (student_id, word.strip(), definition, source_book_id),
        )
        self.conn.commit()

    def vocabulary_due(self, student_id: int, limit: int = 12) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                "SELECT * FROM vocabulary WHERE student_id = ? AND next_review_on <= date('now') "
                "ORDER BY box ASC, next_review_on ASC LIMIT ?",
                (student_id, limit),
            )
        )

    def list_vocabulary(self, student_id: int) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                "SELECT * FROM vocabulary WHERE student_id = ? "
                "ORDER BY next_review_on ASC, word ASC",
                (student_id,),
            )
        )

    def record_vocabulary_review(self, vocab_id: int, correct: bool) -> None:
        row = _row(self.conn.execute("SELECT * FROM vocabulary WHERE id = ?", (vocab_id,)))
        if row is None:
            return
        box = min(row["box"] + 1, 5) if correct else 1
        interval = LEITNER_INTERVALS[box]
        next_review = (date.today() + timedelta(days=interval)).isoformat()
        self.conn.execute(
            "UPDATE vocabulary SET box = ?, next_review_on = ?, "
            "times_correct = times_correct + ?, times_missed = times_missed + ? "
            "WHERE id = ?",
            (box, next_review, 1 if correct else 0, 0 if correct else 1, vocab_id),
        )
        self.conn.commit()

    # -- lessons --------------------------------------------------------------

    def save_lesson(
        self,
        student_id: int,
        agent: str,
        subject: str,
        topic: str,
        title: str,
        payload: dict[str, Any],
        strategy: str = "",
        rationale: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO lessons "
            "(student_id, agent, subject, topic, title, strategy, rationale, payload, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                student_id,
                agent,
                subject,
                topic,
                title,
                strategy,
                rationale,
                json.dumps(payload),
                json.dumps(metadata or {}),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_lesson(self, lesson_id: int) -> dict[str, Any] | None:
        row = _row(self.conn.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,)))
        if row:
            row["payload"] = json.loads(row["payload"])
            row["metadata"] = json.loads(row["metadata"])
        return row

    def list_lessons(
        self, student_id: int, agent: str | None = None, limit: int = 25
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM lessons WHERE student_id = ?"
        params: list[Any] = [student_id]
        if agent:
            sql += " AND agent = ?"
            params.append(agent)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = _rows(self.conn.execute(sql, params))
        for row in rows:
            row["payload"] = json.loads(row["payload"])
            row["metadata"] = json.loads(row["metadata"])
        return rows

    def latest_life_skill_plan(self, student_id: int, skill_id: int) -> dict[str, Any] | None:
        """The most recent generated plan for one life skill, if there is one.

        Matched on the metadata rather than the title so that renaming a skill
        doesn't orphan its plan.
        """
        row = _row(
            self.conn.execute(
                "SELECT * FROM lessons WHERE student_id = ? AND agent = 'life_skills' "
                "AND json_extract(metadata, '$.life_skill_id') = ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (student_id, skill_id),
            )
        )
        if row:
            row["payload"] = json.loads(row["payload"])
            row["metadata"] = json.loads(row["metadata"])
        return row

    def lesson_usage_between(
        self, student_id: int, start: str, end: str
    ) -> list[dict[str, Any]]:
        """Per-lesson token usage, by *generation* date.

        Generation date, not activity date — a lesson written in March and taught
        in April is billed in March.

        Pulls the `_usage` fields out with SQL rather than loading each payload
        and parsing it in Python. A full school year is several hundred lessons,
        and each payload carries the entire lesson text; deserializing all of it
        to read six integers would make this page crawl by spring.
        """
        return _rows(
            self.conn.execute(
                """
                SELECT
                    agent,
                    date(created_at) AS generated_on,
                    json_extract(payload, '$._usage.model')                       AS model,
                    json_extract(payload, '$._usage.input_tokens')                AS input_tokens,
                    json_extract(payload, '$._usage.output_tokens')               AS output_tokens,
                    json_extract(payload, '$._usage.cache_read_input_tokens')     AS cache_read_input_tokens,
                    json_extract(payload, '$._usage.cache_creation_input_tokens') AS cache_creation_input_tokens,
                    json_extract(payload, '$._usage.web_searches')                AS web_searches
                FROM lessons
                WHERE student_id = ? AND date(created_at) BETWEEN ? AND ?
                ORDER BY created_at DESC, id DESC
                """,
                (student_id, start, end),
            )
        )

    def set_lesson_status(self, lesson_id: int, status: str) -> None:
        if status not in ("planned", "completed", "skipped"):
            raise ValueError(f"invalid lesson status: {status}")
        self.conn.execute("UPDATE lessons SET status = ? WHERE id = ?", (status, lesson_id))
        self.conn.commit()

    def mark_student_done(self, lesson_id: int) -> None:
        """The student's own "I'm done for today" signal.

        Deliberately separate from `status`, which only changes when the parent
        logs actual hours: this only controls what he sees as current versus
        past, and never touches hours, credits, or the compliance record.
        """
        self.conn.execute(
            "UPDATE lessons SET metadata = json_set(metadata, '$.student_done_on', ?) "
            "WHERE id = ?",
            (date.today().isoformat(), lesson_id),
        )
        self.conn.commit()

    def record_quiz_result(self, lesson_id: int, correct: int, total: int, passed: bool) -> None:
        """Stash the graded score into the lesson's metadata, alongside the
        strategy metadata already stored there (skill_id, era, and so on)."""
        self.conn.execute(
            "UPDATE lessons SET metadata = json_set(metadata, '$.quiz_result', json(?)) "
            "WHERE id = ?",
            (
                json.dumps(
                    {
                        "correct": correct,
                        "total": total,
                        "passed": passed,
                        "graded_on": date.today().isoformat(),
                    }
                ),
                lesson_id,
            ),
        )
        self.conn.commit()

    # -- activities and multi-subject credits ---------------------------------

    def log_activity(
        self,
        student_id: int,
        title: str,
        tier: str,
        primary_subject: str,
        minutes: int,
        subject_credits: dict[str, int],
        occurred_on: str | None = None,
        description: str = "",
        source: str = "manual",
        location: str = "",
        lesson_id: int | None = None,
    ) -> int:
        """Log instructional time, crediting one or more of the 11 WA subjects.

        `minutes` is the real elapsed time and is what counts toward the 1,000-hour
        floor. `subject_credits` may sum to more than `minutes` — that is Tier 2
        folding working as intended.
        """
        if minutes <= 0:
            raise ValueError("minutes must be positive")
        if not subject_credits:
            subject_credits = {primary_subject: minutes}

        cur = self.conn.execute(
            "INSERT INTO activities "
            "(student_id, lesson_id, title, description, tier, primary_subject, "
            " source, minutes, occurred_on, location) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                student_id,
                lesson_id,
                title,
                description,
                tier,
                primary_subject,
                source,
                int(minutes),
                occurred_on or date.today().isoformat(),
                location,
            ),
        )
        activity_id = int(cur.lastrowid)
        for subject, credit in subject_credits.items():
            credit = int(credit)
            if credit <= 0:
                continue
            self.conn.execute(
                "INSERT INTO activity_subject_credits (activity_id, subject, minutes) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(activity_id, subject) DO UPDATE SET minutes = excluded.minutes",
                (activity_id, subject, credit),
            )
        if lesson_id is not None:
            self.set_lesson_status(lesson_id, "completed")
        self.conn.commit()
        return activity_id

    def list_activities(
        self,
        student_id: int,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM activities WHERE student_id = ?"
        params: list[Any] = [student_id]
        if start:
            sql += " AND occurred_on >= ?"
            params.append(start)
        if end:
            sql += " AND occurred_on <= ?"
            params.append(end)
        sql += " ORDER BY occurred_on DESC, id DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        activities = _rows(self.conn.execute(sql, params))
        if not activities:
            return []
        ids = [a["id"] for a in activities]
        placeholders = ",".join("?" for _ in ids)
        credits = _rows(
            self.conn.execute(
                "SELECT * FROM activity_subject_credits "
                f"WHERE activity_id IN ({placeholders})",
                ids,
            )
        )
        by_activity: dict[int, dict[str, int]] = {}
        for credit in credits:
            by_activity.setdefault(credit["activity_id"], {})[credit["subject"]] = credit[
                "minutes"
            ]
        for activity in activities:
            activity["credits"] = by_activity.get(activity["id"], {})
        return activities

    def delete_activity(self, activity_id: int) -> None:
        self.conn.execute("DELETE FROM activities WHERE id = ?", (activity_id,))
        self.conn.commit()

    # -- Tier 3 choice topics -------------------------------------------------

    def list_choice_topics(self, student_id: int) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                "SELECT * FROM choice_topics WHERE student_id = ? "
                "ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'approved' THEN 1 "
                "WHEN 'proposed' THEN 2 WHEN 'done' THEN 3 ELSE 4 END, id DESC",
                (student_id,),
            )
        )

    def add_choice_topic(
        self,
        student_id: int,
        title: str,
        description: str = "",
        category: str = "",
        credit_subject: str = "occupational_education",
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO choice_topics "
            "(student_id, title, description, category, credit_subject) VALUES (?, ?, ?, ?, ?)",
            (student_id, title, description, category, credit_subject),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def set_choice_status(self, topic_id: int, status: str, parent_note: str = "") -> None:
        self.conn.execute(
            "UPDATE choice_topics SET status = ?, decided_on = date('now'), "
            "parent_note = CASE WHEN ? != '' THEN ? ELSE parent_note END WHERE id = ?",
            (status, parent_note, parent_note, topic_id),
        )
        self.conn.commit()

    def delete_choice_topic(self, topic_id: int) -> None:
        self.conn.execute("DELETE FROM choice_topics WHERE id = ?", (topic_id,))
        self.conn.commit()

    # -- Core life skills -----------------------------------------------------

    def list_life_skills(self, student_id: int) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                "SELECT * FROM life_skills WHERE student_id = ? "
                "ORDER BY category, sort_order, id",
                (student_id,),
            )
        )

    def add_life_skill(
        self,
        student_id: int,
        title: str,
        category: str = "General",
        description: str = "",
        credit_subject: str = "occupational_education",
        materials: str = "",
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO life_skills "
            "(student_id, title, category, description, credit_subject, materials) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (student_id, title, category, description, credit_subject, materials),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def set_life_skill_done(
        self, skill_id: int, completed: bool, notes: str = ""
    ) -> None:
        self.conn.execute(
            "UPDATE life_skills SET completed_on = ?, "
            "notes = CASE WHEN ? != '' THEN ? ELSE notes END WHERE id = ?",
            (date.today().isoformat() if completed else None, notes, notes, skill_id),
        )
        self.conn.commit()

    def delete_life_skill(self, skill_id: int) -> None:
        self.conn.execute("DELETE FROM life_skills WHERE id = ?", (skill_id,))
        self.conn.commit()

    def seed_life_skills(self, student_id: int) -> int:
        """Seed the starter checklist described in the design doc, once."""
        existing = self.list_life_skills(student_id)
        if existing:
            return 0
        for order, (category, title, subject, description, materials) in enumerate(STARTER_LIFE_SKILLS):
            self.conn.execute(
                "INSERT INTO life_skills "
                "(student_id, category, title, credit_subject, description, materials, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (student_id, category, title, subject, description, materials, order),
            )
        self.conn.commit()
        return len(STARTER_LIFE_SKILLS)

    # -- Declaration of Intent (WA RCW 28A.200.010) ---------------------------

    def declaration_status(self, student_id: int, due_on: str) -> dict[str, Any] | None:
        return _row(
            self.conn.execute(
                "SELECT * FROM declarations_of_intent WHERE student_id = ? AND due_on = ?",
                (student_id, due_on),
            )
        )

    def mark_declaration_filed(
        self, student_id: int, due_on: str, filed_on: str | None = None
    ) -> None:
        self.conn.execute(
            "INSERT INTO declarations_of_intent (student_id, due_on, filed_on) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(student_id, due_on) DO UPDATE SET filed_on = excluded.filed_on",
            (student_id, due_on, filed_on or date.today().isoformat()),
        )
        self.conn.commit()

    def clear_declaration_filed(self, student_id: int, due_on: str) -> None:
        self.conn.execute(
            "UPDATE declarations_of_intent SET filed_on = NULL "
            "WHERE student_id = ? AND due_on = ?",
            (student_id, due_on),
        )
        self.conn.commit()

    # -- school-year helper ---------------------------------------------------

    def school_year_bounds(self, on: date | None = None) -> tuple[str, str]:
        """Inclusive (start, end) ISO dates of the school year containing `on`."""
        on = on or date.today()
        raw = self.get_setting("school_year_start") or "09-01"
        try:
            month, day = (int(part) for part in raw.split("-"))
        except (ValueError, AttributeError):
            month, day = 9, 1
        start_year = on.year if (on.month, on.day) >= (month, day) else on.year - 1
        start = date(start_year, month, day)
        end = date(start_year + 1, month, day) - timedelta(days=1)
        return start.isoformat(), end.isoformat()

    def close(self) -> None:
        self.conn.close()
