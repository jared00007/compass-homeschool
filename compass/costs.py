"""What the agents actually cost to run.

Every generation records its own token usage into the lesson payload under
`_usage`. This module turns that into dollars, so the family reads real numbers
rather than an estimate. Nothing here calls the API.

Rates are per million tokens, as published by Anthropic. They are constants in
one place precisely because they will change — if a number here drifts from
the pricing page, this is the only file to edit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

# Per-million-token rates. `cache_read` is ~0.1x input, `cache_write` ~1.25x
# input for the default 5-minute TTL.
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-5": {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-8": {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-sonnet-5": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00, "cache_read": 0.10, "cache_write": 1.25},
    "claude-fable-5": {"input": 10.00, "output": 50.00, "cache_read": 1.00, "cache_write": 12.50},
}

FALLBACK_PRICING = PRICING["claude-opus-5"]

# Server-side web search is billed per query rather than per token. This rate is
# the least certain number in this file — verify it against the pricing page
# before trusting a projection built on it. Only Science and History use search.
WEB_SEARCH_COST_PER_QUERY = 0.01


def rates_for(model: str) -> dict[str, float]:
    """Pricing for a model id, tolerant of date suffixes and provider prefixes."""
    if model in PRICING:
        return PRICING[model]
    normalized = model.replace("anthropic.", "")
    for known, rates in PRICING.items():
        if normalized.startswith(known):
            return rates
    return FALLBACK_PRICING


def lesson_cost(usage: dict[str, Any] | None) -> float:
    """Dollar cost of a single generation from its recorded usage."""
    if not usage:
        return 0.0
    rates = rates_for(str(usage.get("model") or ""))
    million = 1_000_000
    cost = (
        int(usage.get("input_tokens") or 0) * rates["input"] / million
        + int(usage.get("output_tokens") or 0) * rates["output"] / million
        + int(usage.get("cache_read_input_tokens") or 0) * rates["cache_read"] / million
        + int(usage.get("cache_creation_input_tokens") or 0) * rates["cache_write"] / million
    )
    cost += int(usage.get("web_searches") or 0) * WEB_SEARCH_COST_PER_QUERY
    return cost


@dataclass
class AgentCost:
    agent: str
    lessons: int
    cost: float
    input_tokens: int
    output_tokens: int
    web_searches: int

    @property
    def per_lesson(self) -> float:
        return self.cost / self.lessons if self.lessons else 0.0


@dataclass
class CostReport:
    start: str
    end: str
    total_cost: float
    measured_lessons: int
    unmeasured_lessons: int
    by_agent: list[AgentCost] = field(default_factory=list)

    @property
    def total_lessons(self) -> int:
        return self.measured_lessons + self.unmeasured_lessons

    @property
    def per_lesson(self) -> float:
        return self.total_cost / self.measured_lessons if self.measured_lessons else 0.0

    def projected_year_cost(self, today: date | None = None) -> float | None:
        """Straight-line projection to the end of the period.

        Returns None when there isn't enough history to extrapolate from — a
        projection off two lessons is noise dressed up as a forecast.
        """
        if self.measured_lessons < 5:
            return None
        today = today or date.today()
        start = datetime.fromisoformat(self.start).date()
        end = datetime.fromisoformat(self.end).date()
        elapsed = max((min(today, end) - start).days + 1, 1)
        total_days = max((end - start).days + 1, 1)
        return self.total_cost * total_days / elapsed


def build_cost_report(db, student_id: int, start: str, end: str) -> CostReport:
    rows = db.lesson_usage_between(student_id, start, end)

    totals: dict[str, AgentCost] = {}
    total_cost = 0.0
    measured = 0
    unmeasured = 0

    for usage in rows:
        # A lesson generated before usage tracking existed (or restored from an
        # export) has no `_usage` object, so json_extract returns NULL for every
        # field. Counted, but not priced — a zero would quietly understate spend.
        if usage.get("output_tokens") is None and usage.get("input_tokens") is None:
            unmeasured += 1
            continue
        measured += 1
        cost = lesson_cost(usage)
        total_cost += cost

        agent = usage["agent"]
        entry = totals.get(agent)
        if entry is None:
            entry = AgentCost(agent, 0, 0.0, 0, 0, 0)
            totals[agent] = entry
        entry.lessons += 1
        entry.cost += cost
        entry.input_tokens += int(usage.get("input_tokens") or 0) + int(
            usage.get("cache_read_input_tokens") or 0
        )
        entry.output_tokens += int(usage.get("output_tokens") or 0)
        entry.web_searches += int(usage.get("web_searches") or 0)

    return CostReport(
        start=start,
        end=end,
        total_cost=total_cost,
        measured_lessons=measured,
        unmeasured_lessons=unmeasured,
        by_agent=sorted(totals.values(), key=lambda a: a.cost, reverse=True),
    )
