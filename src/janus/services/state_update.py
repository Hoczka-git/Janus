"""State Update module — consumes Verification results and updates system state.

This is Stage 7 of the closed-loop execution pipeline:

    Planner → Agency → Policy → Hermes → Evidence → Verification → State Update → Planner

The module:
1. Consumes a ``VerificationReport`` (from :mod:`janus.verification`)
2. When verification passes, dispatches evidence to update Janus state
3. When verification fails, records the failure without mutating state
4. Produces a ``StateUpdateResult`` describing what changed
5. Evaluates whether the state change requires planner re-derivation

Idempotency: The underlying services (:func:`update_goal_progress`,
:func:`complete_janus_task`, :func:`update_milestone_status`) are
idempotent by ``task_id``.  Re-applying the same verification result will
not double-update state.

State consistency: If any part of the state update fails, the error is
recorded in the ``StateUpdateResult``.  The module never leaves the system
in a partially updated state — either all updates succeed or the error is
reported.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from janus.domain.planning import NextAction, derive_next_action
from janus.models.goal import Goal
from janus.models.milestone import Milestone
from janus.models.project import Project
from janus.models.task import Task
from janus.services.execution_feedback import (
    EvidencePackage,
    JanusDomainMetadata,
    _describe_state_changes,
    _normalize_to_jsonable,
    dispatch_completion,
)
from janus.verification import VerificationReport

logger = logging.getLogger(__name__)


# ── Result models ─────────────────────────────────────────────────────────────


@dataclass
class StateUpdateResult:
    """Result of applying a verification report to Janus state.

    Attributes:
        task_id: The task that was verified.
        verification_passed: Whether the verification report was PASS.
        state_changes: Human-readable descriptions of what changed.
        updated_goals: Goal titles that were updated.
        updated_tasks: Task titles that were updated.
        updated_milestones: Milestone titles that were updated.
        errors: Any errors that occurred during state update.
        timestamp: ISO-8601 UTC timestamp of when the update was applied.
    """

    task_id: str
    verification_passed: bool
    state_changes: list[str] = field(default_factory=list)
    updated_goals: list[str] = field(default_factory=list)
    updated_tasks: list[str] = field(default_factory=list)
    updated_milestones: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-serializable dict."""
        return {
            "task_id": self.task_id,
            "verification_passed": self.verification_passed,
            "state_changes": self.state_changes,
            "updated_goals": self.updated_goals,
            "updated_tasks": self.updated_tasks,
            "updated_milestones": self.updated_milestones,
            "errors": self.errors,
            "timestamp": self.timestamp,
        }

    @property
    def has_changes(self) -> bool:
        """True if any state was actually changed."""
        return bool(
            self.state_changes
            or self.updated_goals
            or self.updated_tasks
            or self.updated_milestones
        )


@dataclass
class PlanRevisionSignal:
    """Signal that the planner should re-derive next actions.

    Produced by :func:`evaluate_plan_impact` when a state update changes
    the goal/task/milestone state in a way that affects the planner's
    next-action derivation.

    Attributes:
        goal_title: The goal that should be re-planned.
        reason: Human-readable reason for the revision.
        priority: 0 = no revision needed, higher = more urgent.
        affected_tasks: Tasks that were updated.
        previous_action: The previous next action title (if known).
        suggested_action: The suggested new next action title (if known).
    """

    goal_title: str
    reason: str
    priority: int = 0
    affected_tasks: list[str] = field(default_factory=list)
    previous_action: str | None = None
    suggested_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-serializable dict."""
        return {
            "goal_title": self.goal_title,
            "reason": self.reason,
            "priority": self.priority,
            "affected_tasks": self.affected_tasks,
            "previous_action": self.previous_action,
            "suggested_action": self.suggested_action,
        }


# ── Core functions ────────────────────────────────────────────────────────────


def apply_verification_result(
    report: VerificationReport,
    metadata: JanusDomainMetadata,
    evidence: EvidencePackage,
) -> StateUpdateResult:
    """Apply a verification report to Janus state.

    When verification passes, dispatches evidence to update goals/tasks/
    milestones via :func:`dispatch_completion`.  When verification fails,
    records the failure without mutating state.

    Idempotent: re-applying the same verification result for the same
    ``task_id`` will not double-update state (the underlying services
    deduplicate by ``task_id``).

    Args:
        report: The verification report from :func:`run_verification`.
        metadata: The Janus domain linkage metadata.
        evidence: The execution evidence package.

    Returns:
        A ``StateUpdateResult`` describing what changed.
    """
    result = StateUpdateResult(
        task_id=report.task_id,
        verification_passed=report.is_pass,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    if not report.is_pass:
        result.errors.append(f"Verification failed: {report.summary}")
        return result

    # Verification passed — dispatch evidence to update state.
    try:
        dispatch_result = dispatch_completion(metadata, evidence)
        dispatch_result = _normalize_to_jsonable(dispatch_result)
        result.state_changes = _describe_state_changes(
            metadata, evidence, dispatch_result
        )

        # Track what was updated based on the dispatch result keys.
        if "goal" in dispatch_result:
            result.updated_goals.append(metadata.title)
        if "task" in dispatch_result:
            result.updated_tasks.append(metadata.title)
        if "milestone" in dispatch_result:
            result.updated_milestones.append(metadata.title)

    except Exception as exc:
        result.errors.append(f"State update failed: {exc}")

    return result


def evaluate_plan_impact(
    state_result: StateUpdateResult,
    goal_title: str | None = None,
) -> PlanRevisionSignal | None:
    """Evaluate whether a state update requires planner re-derivation.

    Returns a ``PlanRevisionSignal`` if the planner should re-derive next
    actions, or ``None`` if no revision is needed.

    Args:
        state_result: The result of :func:`apply_verification_result`.
        goal_title: Optional explicit goal title.  When not provided, the
            first updated goal is used.

    Returns:
        A ``PlanRevisionSignal`` or ``None``.
    """
    if not state_result.verification_passed:
        return None

    if not state_result.has_changes:
        return None

    # Determine the goal title.
    target_goal = goal_title or (
        state_result.updated_goals[0] if state_result.updated_goals else None
    )
    if not target_goal:
        return None

    # Determine priority based on what changed.
    priority = 0
    reason_parts: list[str] = []

    if state_result.updated_tasks:
        priority = max(priority, 2)
        reason_parts.append(
            f"tasks updated: {', '.join(state_result.updated_tasks)}"
        )

    if state_result.updated_milestones:
        priority = max(priority, 3)
        reason_parts.append(
            f"milestones updated: {', '.join(state_result.updated_milestones)}"
        )

    if state_result.updated_goals:
        priority = max(priority, 1)
        reason_parts.append(
            f"goals updated: {', '.join(state_result.updated_goals)}"
        )

    if not reason_parts:
        return None

    return PlanRevisionSignal(
        goal_title=target_goal,
        reason="; ".join(reason_parts),
        priority=priority,
        affected_tasks=state_result.updated_tasks,
    )


def rederive_next_action(
    plan_signal: PlanRevisionSignal,
    goal: Goal,
    tasks: list[Task],
    completed_task_titles: set[str],
    today: date,
    projects: list[Project] | None = None,
) -> NextAction | None:
    """Re-derive the next action for a goal after a state update.

    This is the final step in closing the loop: the planner re-derives
    the next action based on the updated state.

    Args:
        plan_signal: The signal from :func:`evaluate_plan_impact`.
        goal: The updated goal.
        tasks: Current open tasks.
        completed_task_titles: Set of completed task titles.
        today: Current date.
        projects: Optional project list.

    Returns:
        The new next action, or ``None`` if nothing is actionable.
    """
    return derive_next_action(
        goal, tasks, completed_task_titles, today, projects
    )


def close_loop(
    report: VerificationReport,
    metadata: JanusDomainMetadata,
    evidence: EvidencePackage,
    goal_title: str | None = None,
) -> tuple[StateUpdateResult, PlanRevisionSignal | None]:
    """Close the loop: verification → state update → planner feedback.

    This is the top-level entry point for the closed-loop execution
    pipeline.  It applies the verification result to Janus state and
    evaluates whether the planner should re-derive next actions.

    Args:
        report: The verification report.
        metadata: The Janus domain linkage metadata.
        evidence: The execution evidence package.
        goal_title: Optional explicit goal title for planner feedback.

    Returns:
        A tuple of ``(StateUpdateResult, PlanRevisionSignal | None)``.
    """
    state_result = apply_verification_result(report, metadata, evidence)
    plan_signal = evaluate_plan_impact(state_result, goal_title=goal_title)
    return state_result, plan_signal
