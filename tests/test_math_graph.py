"""The math graph is compliance documentation, so its structure is tested."""

from __future__ import annotations

from compass.curriculum import math_graph


def test_graph_is_structurally_sound():
    assert math_graph.validate_graph() == []


def test_every_skill_has_a_known_strand():
    for skill in math_graph.MATH_SKILLS:
        assert skill.strand in math_graph.STRANDS


def test_graph_has_entry_points():
    roots = [s for s in math_graph.MATH_SKILLS if not s.prerequisites]
    assert roots, "a graph with no roots can never be started"


def test_every_skill_is_reachable_from_the_roots():
    """No orphaned skills — every node must be teachable eventually."""
    mastered: set[str] = set()
    for _ in range(len(math_graph.MATH_SKILLS) + 1):
        available = math_graph.available_skills(mastered)
        if not available:
            break
        mastered.update(s.id for s in available)
    assert mastered == set(math_graph.MATH_GRAPH), (
        "unreachable skills: " + ", ".join(sorted(set(math_graph.MATH_GRAPH) - mastered))
    )


def test_nothing_unlocks_before_its_prerequisites():
    mastered = {"integer-operations"}
    available = {s.id for s in math_graph.available_skills(mastered)}
    assert "pythagorean-theorem" not in available
    assert "order-of-operations" in available  # its only prereq is mastered


def test_prerequisite_chain_is_in_teachable_order():
    chain = math_graph.prerequisite_chain("pythagorean-theorem")
    seen: set[str] = set()
    for skill_id in chain:
        skill = math_graph.MATH_GRAPH[skill_id]
        assert set(skill.prerequisites) <= seen, f"{skill_id} taught before its prerequisites"
        seen.add(skill_id)
    assert "square-cube-roots" in chain


def test_missing_prerequisites_reports_the_gap():
    missing = math_graph.missing_prerequisites("slope", set())
    assert "graphing-proportional" in missing


def test_frontier_report_counts_all_strands():
    report = math_graph.frontier_report(set())
    assert report["total_skills"] == len(math_graph.MATH_SKILLS)
    assert report["mastered_count"] == 0
    assert set(report["by_strand"]) == set(math_graph.STRANDS)
