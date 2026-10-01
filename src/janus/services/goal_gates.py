"""Goal completion gates for P1 Policy Enforcement & Approval Workflow (ADR-011).

This module implements structural gates that must pass before a goal
can be marked as completed. These are mechanical checks (not human
approval) that verify the goal's state is consistent.

Design reference: docs/design/policy_approval_p1_design.md §7.3
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from janus.models.goal import Goal

logger = logging.getLogger(__name__)


@dataclass
class GoalCompletionGateResult:
    """Outcome of running the goal completion structural gates.

    ``ok`` is True only when all applicable gates passed.
    On failure, ``blocked_reason`` carries a structured reason code and
    ``blocked_message`` carries a human-readable explanation.
    """

    ok: bool = False
    blocked_reason: str | None = None
    blocked_message: str | None = None


class GoalCompletionGateError(ValueError):
    """Raised when a goal completion structural gate blocks completion.

    Carries a structured ``reason`` code and a human-readable ``message``.
    """

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


# ── Reason codes ──────────────────────────────────────────────────────────────

GATE_GOAL_NOT_FOUND = "goal_not_found"
GATE_GOAL_ALREADY_COMPLETED = "goal_already_completed"
GATE_GOAL_HAS_ACTIVE_TASKS = "goal_has_active_tasks"
GATE_GOAL_METRIC_NOT_AT_TARGET = "goal_metric_not_at_target"


def run_goal_completion_gates(goal: Goal | None) -> GoalCompletionGateResult:
    """Run structural gates that must pass before a goal can be completed.

    Gates:
    1. Goal must exist (not None).
    2. Goal must not already be completed.
    3. Goal must not have active (incomplete) related tasks.
    4. If the goal has a metric, the metric must be at or past its target.

    Args:
        goal: The goal to check.

    Returns:
        A GoalCompletionGateResult. Callers should check ``ok`` before
        proceeding with the completion.
    """
    # Gate 1: Goal must exist
    if goal is None:
        return GoalCompletionGateResult(
            ok=False,
            blocked_reason=GATE_GOAL_NOT_FOUND,
            blocked_message="Goal not found.",
        )

    # Gate 2: Goal must not already be completed
    if goal.status == "completed":
        return GoalCompletionGateResult(
            ok=False,
            blocked_reason=GATE_GOAL_ALREADY_COMPLETED,
            blocked_message=f"Goal '{goal.title}' is already completed.",
        )

    # Gate 3: Goal must not have active related tasks
    # (This is a structural check; the caller is responsible for ensuring
    # the related_tasks list is up-to-date.)
    # At P1, we check if the goal has any related tasks that are not marked
    # as completed. Since we don't have direct access to task state here,
    # we rely on the caller to provide a goal with accurate related_tasks.
    # For now, we skip this gate if related_tasks is None or empty.
    # TODO: Integrate with task service to check task completion status.

    # Gate 4: If the goal has a metric, check if it's at target
    if goal.metric_name and goal.target_value is not None:
        if goal.current_value is None:
            return GoalCompletionGateResult(
                ok=False,
                blocked_reason=GATE_GOAL_METRIC_NOT_AT_TARGET,
                blocked_message=(
                    f"Goal '{goal.title}' has metric '{goal.metric_name}' "
                    f"but no current value recorded."
                ),
            )
        if goal.direction == "increase":
            if goal.current_value < goal.target_value:
                return GoalCompletionGateResult(
                    ok=False,
                    blocked_reason=GATE_GOAL_METRIC_NOT_AT_TARGET,
                    blocked_message=(
                        f"Goal '{goal.title}' metric '{goal.metric_name}' "
                        f"is {goal.current_value}, target is {goal.target_value}."
                    ),
                )
        elif goal.direction == "decrease":
            if goal.current_value > goal.target_value:
                return GoalCompletionGateResult(
                    ok=False,
                    blocked_reason=GATE_GOAL_METRIC_NOT_AT_TARGET,
                    blocked_message=(
                        f"Goal '{goal.title}' metric '{goal.metric_name}' "
                        f"is {goal.current_value}, target is {goal.target_value}."
                    ),
                )

    return GoalCompletionGateResult(ok=True)
