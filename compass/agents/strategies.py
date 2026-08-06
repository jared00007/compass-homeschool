"""The pluggable "what's a good next lesson" strategies.

Four genuinely different shapes of logic, all satisfying the same
`(StudentContext) -> TopicProposal` contract:

    graph_walk       Math    — unlock the next node only when its prereqs are mastered
    spiderweb        Science — branch outward from a topic or a location
    timeline         History — least-covered era, unless where we are beats it
    reading_tied     English — whatever he is reading, plus vocabulary that's due

Strategies are deliberately deterministic and offline. No model call happens
here — a strategy decides *what*, the framework's model call decides *how*.
"""

from __future__ import annotations

import random
from datetime import date
from typing import Any

from compass.agents.framework import StudentContext, TopicProposal
from compass.curriculum import math_graph

# ---------------------------------------------------------------------------
# Math — prerequisite graph walk
# ---------------------------------------------------------------------------

# When several skills unlock at once, prefer the strand that is furthest behind.
# This keeps the year balanced across the five 8th-grade strands rather than
# racing down whichever branch happens to be shortest.


def graph_walk(ctx: StudentContext) -> TopicProposal:
    mastered = ctx.db.mastered_skills(ctx.student_id)
    mastery = ctx.db.mastery_map(ctx.student_id)

    requested = (ctx.inputs.get("skill_id") or "").strip()
    if requested:
        return _proposal_for_skill(requested, mastered, mastery, forced=True)

    in_progress = [
        skill_id
        for skill_id, row in mastery.items()
        if row["status"] == "in_progress" and skill_id in math_graph.MATH_GRAPH
    ]
    if in_progress:
        # Finish what he started before unlocking anything new.
        return _proposal_for_skill(in_progress[0], mastered, mastery, continuing=True)

    available = math_graph.available_skills(mastered)
    if not available:
        return TopicProposal(
            topic="",
            rationale="",
            strategy="graph_walk",
            blocked=True,
            blocked_reason=(
                "Every skill in the 8th-grade graph is mastered. Time to move on to "
                "Algebra I, or record a new scope and sequence."
            ),
        )

    report = math_graph.frontier_report(mastered)
    by_strand: dict[str, dict[str, int]] = report["by_strand"]  # type: ignore[assignment]

    def strand_progress(strand: str) -> float:
        counts = by_strand.get(strand, {"mastered": 0, "total": 1})
        total = counts["total"] or 1
        return counts["mastered"] / total

    # Least-progressed strand first; within a strand, the skill that unlocks the
    # most downstream work.
    chosen = min(
        available,
        key=lambda s: (strand_progress(s.strand), -len(math_graph.unlocks(s.id)), s.id),
    )
    return _proposal_for_skill(chosen.id, mastered, mastery)


def _proposal_for_skill(
    skill_id: str,
    mastered: set[str],
    mastery: dict[str, Any],
    forced: bool = False,
    continuing: bool = False,
) -> TopicProposal:
    skill = math_graph.get_skill(skill_id)
    if skill is None:
        return TopicProposal(
            topic="",
            rationale="",
            strategy="graph_walk",
            blocked=True,
            blocked_reason=f"'{skill_id}' is not in the 8th-grade math graph.",
        )

    missing = math_graph.missing_prerequisites(skill_id, mastered)
    if missing and forced:
        chain = math_graph.prerequisite_chain(skill_id, mastered)
        names = ", ".join(math_graph.MATH_GRAPH[m].title for m in missing)
        return TopicProposal(
            topic="",
            rationale="",
            strategy="graph_walk",
            blocked=True,
            blocked_reason=(
                f"{skill.title} is locked. Unmastered prerequisites: {names}. "
                f"Teaching order to get there: "
                + " -> ".join(math_graph.MATH_GRAPH[c].title for c in chain)
            ),
        )

    prereq_titles = [
        math_graph.MATH_GRAPH[p].title for p in skill.prerequisites if p in math_graph.MATH_GRAPH
    ]
    downstream = [math_graph.MATH_GRAPH[u].title for u in math_graph.unlocks(skill.id)]
    prior_note = mastery.get(skill_id, {}).get("notes", "")

    if continuing:
        rationale = f"Already in progress — finish {skill.title} before unlocking anything new."
    elif forced:
        rationale = f"Parent selected {skill.title}; prerequisites are satisfied."
    else:
        rationale = (
            f"All prerequisites for {skill.title} are mastered, and "
            f"{math_graph.STRANDS[skill.strand]} is the strand furthest behind."
        )

    context_lines = [
        f"Skill: {skill.title} ({skill.id})",
        f"Strand: {math_graph.STRANDS[skill.strand]}",
        f"Scope description: {skill.description}",
    ]
    if skill.objectives:
        context_lines.append("Scope-and-sequence objectives: " + "; ".join(skill.objectives))
    if prereq_titles:
        context_lines.append(
            "Prerequisites he has already mastered (build on these, do not reteach): "
            + ", ".join(prereq_titles)
        )
    else:
        context_lines.append("This is a foundational skill with no prerequisites.")
    if downstream:
        context_lines.append("This unlocks next: " + ", ".join(downstream))
    if continuing and prior_note:
        context_lines.append(f"Notes from the previous attempt: {prior_note}")

    guidance = (
        "This is a prerequisite-graph subject. Teach exactly this one skill — do not "
        "wander into the skills it unlocks, and do not reteach its prerequisites beyond "
        "a brief warm-up. The assessment must produce a clear mastered / not-yet signal, "
        "because the parent logs that result and it is what unlocks the next node. "
        "Leave `branches` empty; the graph decides what comes next, not you."
    )

    return TopicProposal(
        topic=skill.title,
        rationale=rationale,
        strategy="graph_walk",
        guidance=guidance,
        context_lines=context_lines,
        metadata={
            "skill_id": skill.id,
            "strand": skill.strand,
            "prerequisites": list(skill.prerequisites),
            "unlocks": math_graph.unlocks(skill.id),
        },
    )


# ---------------------------------------------------------------------------
# Science — spiderweb branching
# ---------------------------------------------------------------------------

SCIENCE_DOMAINS = (
    "life science and ecosystems",
    "physical science: forces, energy, and matter",
    "earth and space science",
    "engineering design and human impact",
)


def spiderweb(ctx: StudentContext) -> TopicProposal:
    agent_key = "science"
    location = ctx.location
    seed = (ctx.inputs.get("seed_topic") or "").strip()
    pool = ctx.db.unexplored_web_nodes(ctx.student_id, agent_key, location or None)
    explored = ctx.db.explored_topics(ctx.student_id, agent_key)

    guidance = (
        "This is a spiderweb subject. Pick one thread and pull it — depth beats coverage. "
        "Ground the lesson in something he can physically observe or do where the family "
        "is right now, and use web search to get the specifics right (actual species, "
        "actual geology, actual conditions) rather than writing something generic. "
        "Every lesson must include one field or hands-on activity. Then propose 2-4 "
        "`branches`: genuinely different directions this topic opens up, each one a real "
        "next lesson rather than a rephrasing of this one."
    )

    if seed:
        return TopicProposal(
            topic=seed,
            rationale="Parent or student supplied this as the thread to pull.",
            strategy="spiderweb",
            guidance=guidance,
            context_lines=_web_context(location, explored),
            metadata={"seed": True, "location": location},
        )

    # The parent may pick a specific branch rather than taking the pool's head.
    chosen_id = ctx.inputs.get("node_id")
    if chosen_id:
        picked = ctx.db.get_web_node(int(chosen_id))
        if picked and not picked["explored_on"]:
            pool = [picked] + [n for n in pool if n["id"] != picked["id"]]

    if pool:
        node = pool[0]
        parent = ""
        if node["parent_id"]:
            parents = [n for n in ctx.db.web_nodes(ctx.student_id, agent_key) if n["id"] == node["parent_id"]]
            parent = parents[0]["topic"] if parents else ""
        rationale = (
            f"Unexplored branch off {parent}." if parent else "Unexplored branch in the web."
        )
        if location and location.lower() in (node["location"] or "").lower():
            rationale += f" It also matches where you are ({location})."
        return TopicProposal(
            topic=node["topic"],
            rationale=rationale,
            strategy="spiderweb",
            guidance=guidance,
            context_lines=_web_context(location, explored)
            + ([f"Why this branch was proposed: {node['rationale']}"] if node["rationale"] else []),
            metadata={
                "node_id": node["id"],
                "parent_id": node["parent_id"],
                "depth": node["depth"],
                "location": location,
            },
        )

    # Empty web: start a new thread. Let the model choose the entry point, since
    # picking a good one depends on facts about the location that only the model
    # (with web search) has.
    domain = SCIENCE_DOMAINS[len(explored) % len(SCIENCE_DOMAINS)]
    anchor = location or (ctx.interests or "his current interests")
    return TopicProposal(
        topic=f"New science thread anchored on {anchor}",
        rationale=(
            f"The web has no unexplored branches, so start a fresh thread. "
            f"Rotating into {domain}, which is the domain least recently touched."
        ),
        strategy="spiderweb_seed",
        guidance=(
            guidance
            + f"\n\nThis is a NEW thread, so you choose the entry point. Lean toward "
            f"{domain}. Set `topic` to the specific entry point you actually chose — "
            "Compass stores that as the root of the new web, so make it concrete "
            "(a specific phenomenon, organism, or process), not a subject heading."
        ),
        context_lines=_web_context(location, explored)
        + [f"Rotate toward this domain: {domain}"],
        metadata={"seeding": True, "domain": domain, "location": location},
    )


def _web_context(location: str, explored: list[str]) -> list[str]:
    lines: list[str] = []
    if location:
        lines.append(f"Where the family is right now: {location}")
    else:
        lines.append("No location given — this is an at-home or on-the-road lesson.")
    if explored:
        lines.append(
            "Already covered in this web (do not repeat): " + "; ".join(explored[:12])
        )
    else:
        lines.append("Nothing covered in this web yet.")
    return lines


def record_spiderweb_result(
    ctx: StudentContext, proposal: TopicProposal, payload: dict[str, Any], agent_key: str
) -> None:
    """Mark the explored node and graft the model's proposed branches onto the web."""
    node_id = proposal.metadata.get("node_id")
    depth = int(proposal.metadata.get("depth") or 0)
    location = proposal.metadata.get("location") or ctx.location
    topic = payload.get("topic") or proposal.topic

    if node_id:
        ctx.db.mark_web_node_explored(int(node_id))
        parent_id = int(node_id)
    else:
        parent_id = ctx.db.add_web_node(
            ctx.student_id,
            agent_key,
            topic=topic,
            rationale=proposal.rationale,
            location=location,
            depth=depth,
        )
        ctx.db.mark_web_node_explored(parent_id)

    existing = {n["topic"].strip().lower() for n in ctx.db.web_nodes(ctx.student_id, agent_key)}
    for branch in payload.get("branches") or []:
        branch_topic = (branch.get("topic") or "").strip()
        if not branch_topic or branch_topic.lower() in existing:
            continue
        existing.add(branch_topic.lower())
        ctx.db.add_web_node(
            ctx.student_id,
            agent_key,
            topic=branch_topic,
            rationale=branch.get("rationale", ""),
            location=location,
            parent_id=parent_id,
            depth=depth + 1,
        )


# ---------------------------------------------------------------------------
# History — timeline coverage, overridden by location when the location earns it
# ---------------------------------------------------------------------------

ERAS: tuple[tuple[str, str], ...] = (
    ("indigenous", "Indigenous North America before 1492"),
    ("exploration", "European Exploration and Encounter (1400-1650)"),
    ("colonial", "Colonial America (1607-1754)"),
    ("revolution-road", "The Road to Revolution (1754-1775)"),
    ("revolution", "The American Revolution (1775-1783)"),
    ("constitution", "Confederation and the Constitution (1783-1791)"),
    ("early-republic", "The Early Republic (1789-1815)"),
    ("expansion", "Westward Expansion and Manifest Destiny (1800-1860)"),
    ("reform", "Expansion, Industry, and Reform (1815-1850)"),
    ("sectionalism", "Sectionalism and the Road to Civil War (1850-1861)"),
    ("civil-war", "The Civil War (1861-1865)"),
    ("reconstruction", "Reconstruction (1865-1877)"),
    ("civics", "Civics: the Constitution, the branches, and rights"),
    ("geography-economics", "Geography and economics of the United States"),
    ("pacific-northwest", "Pacific Northwest and Washington state history"),
)

ERA_LABELS = dict(ERAS)


def timeline(ctx: StudentContext) -> TopicProposal:
    agent_key = "history"
    location = ctx.location
    seed = (ctx.inputs.get("seed_topic") or "").strip()

    lessons = ctx.db.list_lessons(ctx.student_id, agent=agent_key, limit=200)
    covered: dict[str, int] = {key: 0 for key, _ in ERAS}
    for lesson in lessons:
        era = lesson.get("metadata", {}).get("era")
        if era in covered:
            covered[era] += 1

    least_covered = min(ERAS, key=lambda item: (covered[item[0]], ERAS.index(item)))
    era_key, era_label = least_covered

    explored = ctx.db.explored_topics(ctx.student_id, agent_key)
    pool = ctx.db.unexplored_web_nodes(ctx.student_id, agent_key, location or None)

    guidance = (
        "This is a timeline subject, and it is location-aware. Two rules, in this order:\n"
        "1. If the family's current location has a genuine, specific connection to history "
        "he can stand in front of — a site, a route, a battlefield, a treaty boundary, a "
        "resource that shaped settlement — teach that, and say plainly in `overview` which "
        "era it belongs to. Use web search to confirm the connection is real and get the "
        "details right. Do not force it: a weak 'people also lived here' link is not a "
        "connection.\n"
        "2. Otherwise, teach the least-covered era below.\n\n"
        "Either way, place the lesson on the timeline explicitly — what came before, what "
        "came after, and why the order matters. Then propose 2-4 `branches` for where this "
        "thread could go next."
    )

    context_lines = [
        f"Least-covered era on the timeline: {era_label}",
        "Coverage so far: "
        + ", ".join(f"{label} ({covered[key]})" for key, label in ERAS if covered[key])
        or "Coverage so far: nothing recorded yet.",
    ]
    if location:
        context_lines.insert(0, f"Where the family is right now: {location}")
    else:
        context_lines.insert(0, "No location given — teach the least-covered era.")
    if explored:
        context_lines.append("Already covered (do not repeat): " + "; ".join(explored[:12]))
    if pool:
        context_lines.append(
            "Open branches from earlier lessons you may pick up instead: "
            + "; ".join(n["topic"] for n in pool[:5])
        )

    chosen_id = ctx.inputs.get("node_id")
    if chosen_id:
        picked = ctx.db.get_web_node(int(chosen_id))
        if picked and not picked["explored_on"]:
            return TopicProposal(
                topic=picked["topic"],
                rationale=f"Picked from the open threads. {picked['rationale']}".strip(),
                strategy="timeline",
                guidance=guidance,
                context_lines=context_lines,
                metadata={
                    "era": era_key,
                    "era_label": era_label,
                    "location": location,
                    "node_id": picked["id"],
                    "depth": picked["depth"],
                },
            )

    if seed:
        topic = seed
        rationale = "Parent or student supplied this topic."
    elif location:
        topic = f"{era_label} — or the history of {location}, if the location earns it"
        rationale = (
            f"Timeline says {era_label} is furthest behind, but you are at {location}, "
            "so a real local connection takes priority."
        )
    else:
        topic = era_label
        rationale = f"{era_label} is the least-covered era on the timeline."

    return TopicProposal(
        topic=topic,
        rationale=rationale,
        strategy="timeline",
        guidance=guidance,
        context_lines=context_lines,
        metadata={
            "era": era_key,
            "era_label": era_label,
            "location": location,
            "node_id": pool[0]["id"] if pool and not seed and not location else None,
        },
    )


# ---------------------------------------------------------------------------
# English — tied to what he is actually reading
# ---------------------------------------------------------------------------

ELA_FOCUS_ROTATION = (
    ("comprehension", "close reading and comprehension of the current book"),
    ("vocabulary", "vocabulary drawn from the current book, plus review of words that are due"),
    ("writing", "a writing task that responds to the current book"),
    ("craft", "author's craft: structure, voice, figurative language, and choices"),
)


def reading_tied(ctx: StudentContext) -> TopicProposal:
    book = ctx.db.current_book(ctx.student_id)
    if not book:
        return TopicProposal(
            topic="",
            rationale="",
            strategy="reading_tied",
            blocked=True,
            blocked_reason=(
                "No book is marked as currently being read. Add what he's reading on the "
                "English page first — this agent builds exercises off the actual book, not "
                "a generic passage list."
            ),
        )

    due = ctx.db.vocabulary_due(ctx.student_id, limit=12)
    lessons = ctx.db.list_lessons(ctx.student_id, agent="english", limit=8)
    used_focus = [l.get("metadata", {}).get("focus") for l in lessons]

    requested = (ctx.inputs.get("focus") or "").strip()
    if requested and requested in dict(ELA_FOCUS_ROTATION):
        focus_key = requested
    else:
        focus_key = next(
            (key for key, _ in ELA_FOCUS_ROTATION if key not in used_focus[:3]),
            ELA_FOCUS_ROTATION[0][0],
        )
    focus_label = dict(ELA_FOCUS_ROTATION)[focus_key]

    progress = ""
    if book.get("total_pages"):
        progress = f" (on page {book['current_page']} of {book['total_pages']})"
    elif book.get("current_page"):
        progress = f" (on page {book['current_page']})"

    context_lines = [
        f"Currently reading: \"{book['title']}\"" + (f" by {book['author']}" if book["author"] else "") + progress,
    ]
    if book.get("reading_level"):
        context_lines.append(f"Recorded reading level: {book['reading_level']}")
    if book.get("notes"):
        context_lines.append(f"Parent notes on this book: {book['notes']}")
    context_lines.append(f"This lesson's focus: {focus_label}")

    if due:
        words = ", ".join(f"{v['word']} (box {v['box']})" for v in due)
        context_lines.append(
            "Vocabulary due for spaced-repetition review today — work these into the "
            f"lesson naturally rather than as a quiz: {words}"
        )
    else:
        context_lines.append("No vocabulary is due for review today.")

    finished = ctx.db.list_books(ctx.student_id, status="finished")
    if finished:
        context_lines.append(
            "Books he has already finished: "
            + ", ".join(b["title"] for b in finished[:8])
        )

    guidance = (
        "This is a reading-tied subject. Every exercise must come off the book he is "
        "actually reading right now — quote it, refer to its characters and events, and "
        "meet it where he is in the book. Never substitute a generic passage or a canned "
        "vocabulary list.\n\n"
        "Spoiler rule: do not reference anything past his current page.\n\n"
        "If you introduce new vocabulary, put the words in `materials` as lines formatted "
        "exactly `VOCAB: word — definition`. Compass parses those into his spaced-repetition "
        "deck, so the format matters. Six words is plenty.\n\n"
        "Leave `branches` empty — the book decides what comes next."
    )

    return TopicProposal(
        topic=f"{book['title']}: {focus_label}",
        rationale=(
            f"He is mid-book on \"{book['title']}\", and {focus_key} is the focus area "
            "least recently used."
        ),
        strategy="reading_tied",
        guidance=guidance,
        context_lines=context_lines,
        metadata={
            "book_id": book["id"],
            "book_title": book["title"],
            "focus": focus_key,
            "vocab_due": [v["word"] for v in due],
        },
    )


def record_english_result(
    ctx: StudentContext, proposal: TopicProposal, payload: dict[str, Any]
) -> None:
    """Harvest `VOCAB:` lines from materials into the spaced-repetition deck."""
    book_id = proposal.metadata.get("book_id")
    for item in payload.get("materials") or []:
        if not isinstance(item, str) or not item.strip().upper().startswith("VOCAB:"):
            continue
        body = item.split(":", 1)[1].strip()
        for separator in ("—", "–", " - ", ":"):
            if separator in body:
                word, definition = body.split(separator, 1)
                break
        else:
            word, definition = body, ""
        word = word.strip()
        if word:
            ctx.db.add_vocabulary(
                ctx.student_id, word, definition.strip(), source_book_id=book_id
            )
