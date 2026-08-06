"""Hand-authored 8th-grade math scope and sequence, as a prerequisite graph.

This is deliberately *data in version control*, not agent-inferred. Two reasons:

1. Compliance documentation. A fixed, dated scope and sequence is something you
   can hand to a district or an evaluator. "The model decided" is not.
2. Determinism. The Math agent's job is to reason over this graph, not to invent
   it. Same mastery state in, same next skill out, every time.

Coverage is CCSS grade 8 (8.NS, 8.EE, 8.F, 8.G, 8.SP) plus the grade 6-7
prerequisites an 8th grader must actually hold to access it. Skills are unlocked
only when *every* prerequisite is mastered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class MathSkill:
    id: str
    title: str
    strand: str
    prerequisites: tuple[str, ...]
    description: str
    objectives: tuple[str, ...] = field(default_factory=tuple)
    grade_band: str = "8"


STRANDS: dict[str, str] = {
    "number_system": "The Number System",
    "ratios_proportions": "Ratios & Proportional Relationships",
    "expressions_equations": "Expressions & Equations",
    "functions": "Functions",
    "geometry": "Geometry",
    "statistics": "Statistics & Probability",
}


def _s(
    id: str,
    title: str,
    strand: str,
    prerequisites: Iterable[str],
    description: str,
    objectives: Iterable[str] = (),
    grade_band: str = "8",
) -> MathSkill:
    return MathSkill(
        id=id,
        title=title,
        strand=strand,
        prerequisites=tuple(prerequisites),
        description=description,
        objectives=tuple(objectives),
        grade_band=grade_band,
    )


MATH_SKILLS: tuple[MathSkill, ...] = (
    # --- Foundations carried in from grades 6-7 ------------------------------
    _s(
        "integer-operations",
        "Integer Operations",
        "number_system",
        [],
        "Add, subtract, multiply, and divide positive and negative integers.",
        [
            "Apply sign rules across all four operations",
            "Model integer operations on a number line",
        ],
        grade_band="6-7",
    ),
    _s(
        "fraction-operations",
        "Fraction Operations",
        "number_system",
        [],
        "Add, subtract, multiply, and divide fractions and mixed numbers.",
        [
            "Find common denominators fluently",
            "Divide by multiplying by the reciprocal and explain why",
        ],
        grade_band="6-7",
    ),
    _s(
        "decimal-operations",
        "Decimal Operations",
        "number_system",
        ["fraction-operations"],
        "Operate on decimals and convert between decimal and fraction form.",
        [
            "Convert repeating decimals to fractions",
            "Place the decimal point correctly when multiplying and dividing",
        ],
        grade_band="6-7",
    ),
    _s(
        "order-of-operations",
        "Order of Operations",
        "expressions_equations",
        ["integer-operations"],
        "Evaluate multi-step numeric expressions with grouping and exponents.",
        ["Evaluate nested expressions correctly", "Explain why order conventions exist"],
        grade_band="6-7",
    ),
    _s(
        "factors-multiples",
        "Factors, Multiples, GCF & LCM",
        "number_system",
        ["integer-operations"],
        "Prime factorization, greatest common factor, least common multiple.",
        ["Prime-factor any number under 200", "Use GCF and LCM in word problems"],
        grade_band="6-7",
    ),
    _s(
        "ratios-rates",
        "Ratios and Unit Rates",
        "ratios_proportions",
        ["fraction-operations"],
        "Express and compare ratios; compute and interpret unit rates.",
        ["Reduce a ratio to a unit rate", "Compare rates in different units"],
        grade_band="6-7",
    ),
    _s(
        "percent-problems",
        "Percent Problems",
        "ratios_proportions",
        ["ratios-rates", "decimal-operations"],
        "Percent of a number, percent change, discount, tax, tip, and interest.",
        ["Solve percent-increase and percent-decrease problems", "Compute simple interest"],
        grade_band="6-7",
    ),
    _s(
        "rational-numbers",
        "Rational Numbers on the Number Line",
        "number_system",
        ["integer-operations", "fraction-operations"],
        "Locate, order, and compare rational numbers; absolute value.",
        ["Order a mixed set of fractions, decimals, and integers", "Interpret absolute value"],
        grade_band="6-7",
    ),
    _s(
        "coordinate-plane",
        "The Coordinate Plane",
        "geometry",
        ["integer-operations"],
        "Plot and read ordered pairs across all four quadrants.",
        ["Plot points in all four quadrants", "Interpret coordinates in context"],
        grade_band="6-7",
    ),
    _s(
        "algebraic-expressions",
        "Algebraic Expressions",
        "expressions_equations",
        ["order-of-operations", "integer-operations"],
        "Evaluate, simplify, expand, and factor linear expressions.",
        ["Combine like terms", "Apply the distributive property in both directions"],
        grade_band="6-7",
    ),
    # --- 8.NS: The Number System --------------------------------------------
    _s(
        "rational-vs-irrational",
        "Rational vs. Irrational Numbers",
        "number_system",
        ["rational-numbers"],
        "Classify real numbers; recognize that irrationals are non-repeating decimals.",
        [
            "Classify a number as rational or irrational and justify it",
            "Show that every rational number has a repeating or terminating decimal",
        ],
    ),
    _s(
        "approximating-irrationals",
        "Approximating Irrational Numbers",
        "number_system",
        ["rational-vs-irrational"],
        "Estimate irrational values and place them on a number line.",
        ["Estimate a square root to the nearest tenth", "Compare pi to 22/7"],
    ),
    # --- 8.EE: Expressions & Equations --------------------------------------
    _s(
        "exponents-properties",
        "Properties of Integer Exponents",
        "expressions_equations",
        ["order-of-operations"],
        "Product, quotient, power, zero, and negative exponent rules.",
        ["Simplify expressions with negative exponents", "Justify why x^0 = 1"],
    ),
    _s(
        "square-cube-roots",
        "Square and Cube Roots",
        "expressions_equations",
        ["exponents-properties"],
        "Evaluate perfect squares and cubes; solve x^2 = p and x^3 = p.",
        ["Know squares to 15 and cubes to 5", "Solve simple radical equations"],
    ),
    _s(
        "scientific-notation",
        "Scientific Notation",
        "expressions_equations",
        ["exponents-properties", "decimal-operations"],
        "Write and interpret very large and very small numbers.",
        ["Convert between standard and scientific notation", "Compare magnitudes"],
    ),
    _s(
        "scientific-notation-operations",
        "Operations with Scientific Notation",
        "expressions_equations",
        ["scientific-notation"],
        "Multiply, divide, add, and subtract in scientific notation.",
        ["Operate on measured quantities", "Choose appropriate units for the result"],
    ),
    _s(
        "one-step-equations",
        "One-Step Equations",
        "expressions_equations",
        ["algebraic-expressions"],
        "Solve equations requiring a single inverse operation.",
        ["Solve and check one-step equations", "Translate a sentence into an equation"],
        grade_band="6-7",
    ),
    _s(
        "two-step-equations",
        "Two-Step Equations",
        "expressions_equations",
        ["one-step-equations"],
        "Solve equations requiring two inverse operations.",
        ["Solve and check two-step equations", "Model a two-step situation"],
        grade_band="6-7",
    ),
    _s(
        "multi-step-equations",
        "Multi-Step Equations",
        "expressions_equations",
        ["two-step-equations"],
        "Solve equations requiring distribution and combining like terms.",
        ["Distribute before isolating", "Verify solutions by substitution"],
    ),
    _s(
        "variables-both-sides",
        "Equations with Variables on Both Sides",
        "expressions_equations",
        ["multi-step-equations"],
        "Collect variable terms on one side and solve.",
        ["Solve equations with variables on both sides", "Model comparison problems"],
    ),
    _s(
        "solution-cases",
        "One, None, or Infinitely Many Solutions",
        "expressions_equations",
        ["variables-both-sides"],
        "Recognize and explain equations with no solution or infinite solutions.",
        [
            "Identify the solution case from the simplified form",
            "Explain what each case means in context",
        ],
    ),
    _s(
        "inequalities",
        "Solving and Graphing Inequalities",
        "expressions_equations",
        ["two-step-equations"],
        "Solve multi-step inequalities and graph solution sets.",
        [
            "Flip the inequality when multiplying by a negative",
            "Graph and interpret a solution set",
        ],
    ),
    _s(
        "proportional-relationships",
        "Proportional Relationships",
        "ratios_proportions",
        ["ratios-rates"],
        "Recognize proportionality in tables, graphs, and equations.",
        ["Test a table for proportionality", "Write y = kx from a situation"],
    ),
    _s(
        "constant-of-proportionality",
        "Constant of Proportionality",
        "ratios_proportions",
        ["proportional-relationships"],
        "Identify and interpret k in a proportional relationship.",
        ["Find k from a graph, table, or equation", "Explain what k means in context"],
    ),
    _s(
        "graphing-proportional",
        "Graphing Proportional Relationships",
        "expressions_equations",
        ["proportional-relationships", "coordinate-plane"],
        "Graph y = kx and compare unit rates across representations.",
        ["Graph proportional relationships", "Compare two rates given differently"],
    ),
    _s(
        "slope",
        "Slope as Rate of Change",
        "expressions_equations",
        ["graphing-proportional"],
        "Compute slope from two points; interpret it as a rate.",
        ["Compute slope from any two points", "Interpret slope in a real context"],
    ),
    _s(
        "similar-triangles-slope",
        "Similar Triangles and Slope",
        "expressions_equations",
        ["slope"],
        "Explain why slope is constant along a line using similar triangles.",
        ["Construct similar slope triangles", "Argue that slope is well-defined"],
    ),
    _s(
        "slope-intercept",
        "Slope-Intercept Form",
        "expressions_equations",
        ["slope"],
        "Graph and interpret y = mx + b.",
        ["Graph from slope-intercept form", "Interpret b as an initial value"],
    ),
    _s(
        "writing-linear-equations",
        "Writing Linear Equations",
        "expressions_equations",
        ["slope-intercept"],
        "Write equations from graphs, tables, two points, or a description.",
        ["Write an equation from two points", "Model a real situation linearly"],
    ),
    _s(
        "systems-graphing",
        "Systems of Equations: Graphing",
        "expressions_equations",
        ["slope-intercept"],
        "Solve two-variable systems by graphing; interpret the intersection.",
        ["Solve a system graphically", "Explain what the intersection means"],
    ),
    _s(
        "systems-substitution",
        "Systems: Substitution",
        "expressions_equations",
        ["systems-graphing", "variables-both-sides"],
        "Solve systems algebraically by substitution.",
        ["Solve by substitution", "Choose the easier variable to isolate"],
    ),
    _s(
        "systems-elimination",
        "Systems: Elimination",
        "expressions_equations",
        ["systems-substitution"],
        "Solve systems by elimination; recognize special cases.",
        ["Solve by elimination", "Identify systems with no or infinite solutions"],
    ),
    # --- 8.F: Functions ------------------------------------------------------
    _s(
        "function-definition",
        "Defining Functions",
        "functions",
        ["coordinate-plane"],
        "A function assigns exactly one output to each input.",
        ["Apply the vertical line test", "Decide whether a relation is a function"],
    ),
    _s(
        "function-representations",
        "Representing Functions",
        "functions",
        ["function-definition"],
        "Move between tables, graphs, equations, and verbal descriptions.",
        ["Translate among all four representations", "Read values from a graph"],
    ),
    _s(
        "linear-vs-nonlinear",
        "Linear vs. Nonlinear Functions",
        "functions",
        ["function-representations", "slope-intercept"],
        "Distinguish linear from nonlinear functions across representations.",
        ["Identify linearity from a table", "Sketch a nonlinear example"],
    ),
    _s(
        "comparing-functions",
        "Comparing Functions",
        "functions",
        ["linear-vs-nonlinear"],
        "Compare two functions given in different representations.",
        [
            "Compare rates of change across representations",
            "Justify which function grows faster",
        ],
    ),
    _s(
        "qualitative-graphs",
        "Describing Relationships Qualitatively",
        "functions",
        ["function-representations"],
        "Sketch and interpret graphs of real situations without numbers.",
        ["Sketch a graph from a story", "Narrate a story from a graph"],
    ),
    # --- 8.G: Geometry -------------------------------------------------------
    _s(
        "angle-relationships",
        "Angle Relationships",
        "geometry",
        ["algebraic-expressions"],
        "Parallel lines cut by a transversal; vertical and adjacent angles.",
        ["Name angle pairs correctly", "Solve for unknown angles algebraically"],
    ),
    _s(
        "triangle-angle-sum",
        "Triangle Angle Sum & Exterior Angles",
        "geometry",
        ["angle-relationships"],
        "Interior angle sum, exterior angle theorem, and angle-angle criterion.",
        ["Apply the 180-degree sum", "Use the exterior angle theorem"],
    ),
    _s(
        "transformations",
        "Rigid Transformations",
        "geometry",
        ["coordinate-plane"],
        "Translations, reflections, and rotations on the coordinate plane.",
        ["Apply a transformation rule to coordinates", "Describe a transformation precisely"],
    ),
    _s(
        "congruence",
        "Congruence Through Transformations",
        "geometry",
        ["transformations", "triangle-angle-sum"],
        "Show two figures are congruent by a sequence of rigid motions.",
        ["Describe a congruence sequence", "Identify corresponding parts"],
    ),
    _s(
        "dilations",
        "Dilations and Scale Factor",
        "geometry",
        ["transformations", "constant-of-proportionality"],
        "Dilate figures about a center; interpret scale factor.",
        ["Dilate a figure by a given factor", "Predict effects on length and area"],
    ),
    _s(
        "similarity",
        "Similarity Through Transformations",
        "geometry",
        ["dilations", "congruence"],
        "Establish similarity by a sequence of similarity transformations.",
        ["Describe a similarity sequence", "Solve for missing sides in similar figures"],
    ),
    _s(
        "pythagorean-theorem",
        "The Pythagorean Theorem",
        "geometry",
        ["square-cube-roots", "triangle-angle-sum"],
        "State, prove, and apply a^2 + b^2 = c^2.",
        ["Explain a proof of the theorem", "Find a missing side of a right triangle"],
    ),
    _s(
        "pythagorean-applications",
        "Applications of the Pythagorean Theorem",
        "geometry",
        ["pythagorean-theorem"],
        "Solve real-world and 3-D problems using the theorem.",
        ["Solve a real measurement problem", "Apply the theorem in three dimensions"],
    ),
    _s(
        "distance-formula",
        "Distance on the Coordinate Plane",
        "geometry",
        ["pythagorean-theorem", "coordinate-plane"],
        "Find the distance between two points using the Pythagorean theorem.",
        ["Derive the distance formula", "Compute distances between plotted points"],
    ),
    _s(
        "volume-solids",
        "Volume of Cylinders, Cones, and Spheres",
        "geometry",
        ["square-cube-roots"],
        "Apply volume formulas and interpret them in context.",
        ["Apply each volume formula", "Compare a cone to its enclosing cylinder"],
    ),
    # --- 8.SP: Statistics & Probability -------------------------------------
    _s(
        "scatter-plots",
        "Scatter Plots and Bivariate Data",
        "statistics",
        ["coordinate-plane"],
        "Construct and interpret scatter plots; describe association.",
        ["Describe clustering, outliers, and association", "Build a scatter plot from data"],
    ),
    _s(
        "line-of-best-fit",
        "Line of Best Fit",
        "statistics",
        ["scatter-plots", "slope-intercept"],
        "Fit a line informally and use it to make predictions.",
        ["Fit and write an equation for a trend line", "Interpret slope and intercept in context"],
    ),
    _s(
        "two-way-tables",
        "Two-Way Tables",
        "statistics",
        ["percent-problems"],
        "Build two-way frequency tables and compute relative frequencies.",
        ["Construct a two-way table", "Interpret relative frequency for association"],
    ),
)

MATH_GRAPH: dict[str, MathSkill] = {skill.id: skill for skill in MATH_SKILLS}


# --- graph queries -----------------------------------------------------------


def get_skill(skill_id: str) -> MathSkill | None:
    return MATH_GRAPH.get(skill_id)


def validate_graph() -> list[str]:
    """Return a list of structural problems. Empty means the graph is sound."""
    problems: list[str] = []
    for skill in MATH_SKILLS:
        for prereq in skill.prerequisites:
            if prereq not in MATH_GRAPH:
                problems.append(f"{skill.id}: unknown prerequisite '{prereq}'")
        if skill.strand not in STRANDS:
            problems.append(f"{skill.id}: unknown strand '{skill.strand}'")

    # Cycle detection via DFS with colouring.
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {sid: WHITE for sid in MATH_GRAPH}

    def visit(sid: str, path: list[str]) -> None:
        if colour[sid] == GREY:
            problems.append("cycle: " + " -> ".join(path + [sid]))
            return
        if colour[sid] == BLACK:
            return
        colour[sid] = GREY
        for prereq in MATH_GRAPH[sid].prerequisites:
            if prereq in MATH_GRAPH:
                visit(prereq, path + [sid])
        colour[sid] = BLACK

    for sid in MATH_GRAPH:
        visit(sid, [])
    return problems


def missing_prerequisites(skill_id: str, mastered: set[str]) -> tuple[str, ...]:
    skill = MATH_GRAPH.get(skill_id)
    if skill is None:
        return ()
    return tuple(p for p in skill.prerequisites if p not in mastered)


def available_skills(mastered: set[str]) -> list[MathSkill]:
    """Skills whose prerequisites are all mastered and which aren't mastered yet."""
    return [
        skill
        for skill in MATH_SKILLS
        if skill.id not in mastered and all(p in mastered for p in skill.prerequisites)
    ]


def prerequisite_chain(skill_id: str, mastered: set[str] | None = None) -> list[str]:
    """Every unmastered ancestor of `skill_id`, in a valid teaching order."""
    mastered = mastered or set()
    ordered: list[str] = []
    seen: set[str] = set()

    def walk(sid: str) -> None:
        if sid in seen or sid in mastered or sid not in MATH_GRAPH:
            return
        seen.add(sid)
        for prereq in MATH_GRAPH[sid].prerequisites:
            walk(prereq)
        ordered.append(sid)

    walk(skill_id)
    return [s for s in ordered if s != skill_id]


def unlocks(skill_id: str) -> list[str]:
    """Skills that list `skill_id` as a direct prerequisite."""
    return [s.id for s in MATH_SKILLS if skill_id in s.prerequisites]


def frontier_report(mastered: set[str]) -> dict[str, object]:
    """Summary of where the student stands on the graph."""
    ready = available_skills(mastered)
    strand_counts: dict[str, dict[str, int]] = {
        key: {"mastered": 0, "total": 0} for key in STRANDS
    }
    for skill in MATH_SKILLS:
        strand_counts[skill.strand]["total"] += 1
        if skill.id in mastered:
            strand_counts[skill.strand]["mastered"] += 1
    return {
        "total_skills": len(MATH_SKILLS),
        "mastered_count": len([s for s in MATH_SKILLS if s.id in mastered]),
        "available": ready,
        "locked_count": len(MATH_SKILLS) - len(mastered) - len(ready),
        "by_strand": strand_counts,
    }
