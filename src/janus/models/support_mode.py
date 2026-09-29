"""Support mode taxonomy for agency-aware planning.

This module defines the support dimension of agency-aware task
classification: how much support the user needs.  The enum is a
planning-layer concern (not a domain enum) — it is derived at planning
time from task properties, goal context, and user state.

The substitutability ordering (least → most substitutive) is:
    EXPLAIN → COACH → SCAFFOLD → REVIEW → EXECUTE

EXPLAIN is least substitutive (Janus explains, user does everything).
EXECUTE is most substitutive (Janus does everything, user reviews).
"""

from enum import StrEnum


class SupportMode(StrEnum):
    """How much support the user needs for a task.

    Members:
        EXPLAIN  — user needs to understand (Janus explains).
        COACH    — user needs guidance (Janus coaches).
        SCAFFOLD — user needs structure/tools (Janus scaffolds).
        REVIEW   — user does it, Janus reviews.
        EXECUTE  — Janus does it (most substitutive).
    """

    EXPLAIN = "explain"
    COACH = "coach"
    SCAFFOLD = "scaffold"
    REVIEW = "review"
    EXECUTE = "execute"


#: Substitutability ordering for support modes (least → most substitutive).
#: The planner prefers the earliest mode in this ordering that still
#: enables progress toward the current plan.
SUPPORT_MODE_ORDER: tuple[SupportMode, ...] = (
    SupportMode.EXPLAIN,
    SupportMode.COACH,
    SupportMode.SCAFFOLD,
    SupportMode.REVIEW,
    SupportMode.EXECUTE,
)
