"""Policing the model's multi-subject credit claims.

This lives on its own because it is the one piece of agent output that goes
straight into a legal record. The compliance dashboard reads these numbers, and
the parent has to defend them to a district — so anything that generates credits
runs through here, and there is exactly one implementation to keep honest.
"""

from __future__ import annotations

from typing import Any, Iterable

from compass import subjects


def normalize_credits(
    payload: dict[str, Any],
    *,
    primary: str,
    allowed: Iterable[str],
    fallback_minutes: int,
    segments_key: str = "activities",
) -> list[str]:
    """Clamp `payload["subject_credits"]` to what may honestly be claimed.

    `segments_key` names the list of timed chunks the payload is built from —
    `activities` for a lesson, `steps` for a life-skill plan — which is what the
    total is reconciled against.

    Returns parent-facing warnings. Every adjustment produces one: silently
    rewriting a compliance record would be worse than not checking at all.
    """
    warnings: list[str] = []
    allowed_set = set(allowed)

    segments = payload.get(segments_key) or []
    segment_minutes = sum(int(s.get("minutes") or 0) for s in segments)
    estimated = int(payload.get("estimated_minutes") or 0)
    if segment_minutes and abs(segment_minutes - estimated) > 5:
        payload["estimated_minutes"] = segment_minutes
        estimated = segment_minutes
        warnings.append(
            f"Adjusted total time to {segment_minutes} min to match the listed {segments_key}."
        )
    if estimated <= 0:
        payload["estimated_minutes"] = fallback_minutes
        estimated = fallback_minutes

    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for credit in payload.get("subject_credits") or []:
        subject = credit.get("subject")
        minutes = int(credit.get("minutes") or 0)
        if not subjects.is_valid(subject):
            warnings.append(f"Dropped credit for unknown subject '{subject}'.")
            continue
        if subject not in allowed_set:
            warnings.append(
                f"Dropped {subjects.label(subject)} credit — outside this agent's scope."
            )
            continue
        if subject in seen:
            warnings.append(f"Merged a duplicate {subjects.label(subject)} credit.")
            continue
        if minutes <= 0:
            continue
        if minutes > estimated:
            warnings.append(
                f"Capped {subjects.label(subject)} at the lesson's {estimated} min "
                f"(claimed {minutes})."
            )
            minutes = estimated
        seen.add(subject)
        cleaned.append(
            {
                "subject": subject,
                "minutes": minutes,
                "justification": credit.get("justification", ""),
            }
        )

    if primary not in seen:
        cleaned.insert(
            0,
            {
                "subject": primary,
                "minutes": estimated,
                "justification": "Primary subject for this agent.",
            },
        )
        warnings.append(f"Added the missing primary {subjects.label(primary)} credit.")

    # The per-credit cap above is not enough on its own. Capping each credit at
    # the lesson length still lets six subjects each claim most of the hour — a
    # 60-minute history lesson was observed claiming 135 minutes across six
    # subjects, so every minute was counted 2.25 times.
    #
    # The defensible rule: the primary subject gets the whole lesson, because the
    # whole lesson is that subject. Secondary subjects are *segments within* it —
    # the 18 minutes reading a source, the 15 minutes writing about it. Segments
    # may overlap each other, but they cannot collectively exceed the lesson they
    # sit inside. So secondaries are capped, together, at the lesson length.
    secondary = [c for c in cleaned if c["subject"] != primary]
    secondary_total = sum(c["minutes"] for c in secondary)
    if secondary_total > estimated and secondary_total > 0:
        scale = estimated / secondary_total
        for credit in secondary:
            credit["minutes"] = max(int(round(credit["minutes"] * scale)), 1)
        warnings.append(
            f"Secondary subjects claimed {secondary_total} min inside a "
            f"{estimated} min lesson — scaled down to fit. Check they're still fair "
            "before logging."
        )
        cleaned = [c for c in cleaned if c["minutes"] > 0]

    payload["subject_credits"] = cleaned
    return warnings
