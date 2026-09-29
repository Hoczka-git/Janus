"""Execution mode taxonomy for agency-aware planning.

This module defines the execution dimension of agency-aware task
classification: who should perform the task.  The enum is a planning-layer
concern (not a domain enum) — it is derived at planning time from task
properties, goal context, and user state.

The substitutability ordering (least → most substitutive) is:
    USER → JANUS → COLLABORATIVE

USER is least substitutive (the user acts, Janus assists).  JANUS is most
substitutive (Janus executes, user reviews).  COLLABORATIVE is in between.
"""

from enum import StrEnum


class ExecutionMode(StrEnum):
    """Who should perform a task.

    Members:
        USER          — user acts, Janus assists (least substitutive).
        JANUS         — Janus executes, user reviews (most substitutive).
        COLLABORATIVE — user + Janus work together.
    """

    USER = "user"
    JANUS = "janus"
    COLLABORATIVE = "collaborative"


#: Substitutability ordering for execution modes (least → most substitutive).
#: The planner prefers the earliest mode in this ordering that still
#: enables progress toward the current plan.
EXECUTION_MODE_ORDER: tuple[ExecutionMode, ...] = (
    ExecutionMode.USER,
    ExecutionMode.JANUS,
    ExecutionMode.COLLABORATIVE,
)
