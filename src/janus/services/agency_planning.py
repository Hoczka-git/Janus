"""Agency-aware planning service.

This module implements the core of Phase D: the mode-selection algorithm
that chooses the least substitutive mode (preferring USER > JANUS >
COLLABORATIVE for execution_mode, and EXPLAIN > COACH > SCAFFOLD >
REVIEW > EXECUTE for support_mode) that still enables progress toward
the current plan.

The classification is derived at planning time from task properties,
goal context, and user state — it is NOT persisted as a task field.

Design reference: docs/design/agency_aware_planning.md (branch
janus/t_57e1acdc-plan-agency-aware-planning).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date

from janus.models.execution_mode import EXECUTION_MODE_ORDER, ExecutionMode
from janus.models.goal import Goal
from janus.models.support_mode import SUPPORT_MODE_ORDER, SupportMode
from janus.models.task import Task
from janus.models.task_agency import TaskAgency

logger = logging.getLogger(__name__)


# ── AgencyContext ─────────────────────────────────────────────────────────────


@dataclass
class AgencyContext:
    """Context signals derived from user state for agency classification.

    This is a lightweight read-model aggregate that the classifier uses
    to make mode-selection decisions.  It can be derived from
    PersonalState (when available) or constructed directly for testing.

    Attributes:
        skill_evidence_count: Number of pieces of skill evidence the user
            has for the relevant skill.  0 = no evidence.
        goal_health: Health state of the goal — "healthy", "watch",
            "stalled", or "completed".
        goal_stalled: Whether the goal is currently stalled.
        task_completion_history: Number of tasks completed by the user
            in the relevant context.
    """

    skill_evidence_count: int = 0
    goal_health: str = "healthy"
    goal_stalled: bool = False
    task_completion_history: int = 0


# ── Keyword-based task nature classification ─────────────────────────────────

#: Keywords that indicate an administrative task (low-value, automatable).
ADMIN_KEYWORDS: frozenset[str] = frozenset({
    "sync", "format", "collect", "aggregate", "summarize",
    "export", "import", "backup", "cleanup", "migrate",
})

#: Keywords that indicate a learning-related task (capability building).
LEARNING_KEYWORDS: frozenset[str] = frozenset({
    "learn", "practice", "study", "read", "course", "tutorial",
    "exercise", "drill", "memorize",
})

#: Keywords that indicate a routine task (recurring, well-defined).
ROUTINE_KEYWORDS: frozenset[str] = frozenset({
    "daily", "weekly", "routine", "check", "review", "log",
    "track", "record", "update", "maintain",
})


def _classify_task_nature(task: Task) -> str:
    """Classify a task's nature based on title keywords.

    Returns one of: "administrative", "learning", "routine", or "general".
    """
    title_lower = task.title.lower()

    # Check for administrative keywords
    for kw in ADMIN_KEYWORDS:
        if kw in title_lower:
            return "administrative"

    # Check for learning keywords
    for kw in LEARNING_KEYWORDS:
        if kw in title_lower:
            return "learning"

    # Check for routine keywords
    for kw in ROUTINE_KEYWORDS:
        if kw in title_lower:
            return "routine"

    return "general"


def _is_high_complexity(task: Task) -> bool:
    """Check if a task has high complexity.

    High complexity is indicated by:
    - Long estimated duration (if available in extra_metadata)
    - Many dependencies (if available in extra_metadata)
    """
    if not task.extra_metadata:
        return False

    # Check for duration hints in metadata
    for meta in task.extra_metadata:
        meta_lower = meta.lower()
        if "estimate" in meta_lower or "duration" in meta_lower:
            # Simple heuristic: if metadata contains a number > 4, assume hours
            numbers = re.findall(r'\d+', meta)
            for num_str in numbers:
                if int(num_str) > 4:
                    return True

    return False


# ── Execution mode selection ─────────────────────────────────────────────────


def _execution_mode_conditions(
    task: Task,
    nature: str,
) -> dict[ExecutionMode, bool]:
    """Map each execution mode to whether its condition is satisfied.

    This is the single source of truth for execution-mode selection.
    The ordering tuple ``EXECUTION_MODE_ORDER`` is iterated by
    :func:`select_execution_mode` to pick the least substitutive match.
    """
    return {
        # USER: learning tasks (capability building) or default
        ExecutionMode.USER: nature == "learning",
        # JANUS: administrative or routine tasks (automate)
        ExecutionMode.JANUS: nature in ("administrative", "routine"),
        # COLLABORATIVE: high complexity (user needs assistance)
        ExecutionMode.COLLABORATIVE: _is_high_complexity(task),
    }


def select_execution_mode(
    task: Task,
    goal: Goal,
    context: AgencyContext,
) -> ExecutionMode:
    """Select the least substitutive execution mode that enables progress.

    Iterates over ``EXECUTION_MODE_ORDER`` (USER → JANUS → COLLABORATIVE)
    and returns the first mode whose condition is satisfied.  If no
    condition matches, returns the first mode in the ordering (USER —
    the least substitutive default).
    """
    nature = _classify_task_nature(task)
    conditions = _execution_mode_conditions(task, nature)

    for mode in EXECUTION_MODE_ORDER:
        if conditions.get(mode, False):
            return mode

    # Default: least substitutive mode
    return EXECUTION_MODE_ORDER[0]


# ── Support mode selection ───────────────────────────────────────────────────


def _support_mode_conditions(
    task: Task,
    context: AgencyContext,
    execution_mode: ExecutionMode | None,
) -> dict[SupportMode, bool]:
    """Map each support mode to whether its condition is satisfied.

    This is the single source of truth for support-mode selection.
    The ordering tuple ``SUPPORT_MODE_ORDER`` is iterated by
    :func:`select_support_mode` to pick the least substitutive match.
    """
    return {
        # EXPLAIN: no skill evidence (need to understand first)
        SupportMode.EXPLAIN: context.skill_evidence_count == 0,
        # COACH: some evidence + goal stalled (need guidance to restart)
        SupportMode.COACH: (
            context.skill_evidence_count > 0
            and (context.goal_stalled or context.goal_health == "stalled")
        ),
        # SCAFFOLD: evidence + goal active (need structure/tools)
        SupportMode.SCAFFOLD: (
            context.skill_evidence_count > 0
            and context.goal_health in ("healthy", "watch")
        ),
        # REVIEW: task in review phase (user did it, Janus reviews)
        SupportMode.REVIEW: _is_review_phase(task),
        # EXECUTE: execution mode is JANUS (Janus executes)
        SupportMode.EXECUTE: execution_mode == ExecutionMode.JANUS,
    }


def select_support_mode(
    task: Task,
    goal: Goal,
    context: AgencyContext,
    execution_mode: ExecutionMode | None = None,
) -> SupportMode:
    """Select the least substitutive support mode that enables progress.

    When ``execution_mode`` is JANUS, returns EXECUTE immediately (Janus
    executes, user reviews — this overrides all other rules).

    Otherwise, iterates over ``SUPPORT_MODE_ORDER`` (EXPLAIN → COACH →
    SCAFFOLD → REVIEW → EXECUTE) and returns the first mode whose
    condition is satisfied.  If no condition matches, returns the first
    mode in the ordering (EXPLAIN — the least substitutive default).
    """
    # Override: JANUS execution → EXECUTE support
    if execution_mode == ExecutionMode.JANUS:
        return SupportMode.EXECUTE

    conditions = _support_mode_conditions(task, context, execution_mode)

    for mode in SUPPORT_MODE_ORDER:
        if conditions.get(mode, False):
            return mode

    # Default: least substitutive mode
    return SUPPORT_MODE_ORDER[0]


def _is_review_phase(task: Task) -> bool:
    """Check if a task is in the review phase.

    This is a heuristic based on task metadata.  In a fuller
    implementation, this would check task state or project/milestone
    position.
    """
    if not task.extra_metadata:
        return False
    for meta in task.extra_metadata:
        if "review" in meta.lower():
            return True
    return False


# ── Confidence calculation ───────────────────────────────────────────────────


def _compute_confidence(
    task: Task,
    goal: Goal,
    context: AgencyContext,
    execution_mode: ExecutionMode,
    support_mode: SupportMode,
) -> float:
    """Compute confidence score for the classification.

    Base confidence is 0.5.  Evidence increases confidence:
    - Skill evidence count adds up to 0.3
    - Task completion history adds up to 0.2
    """
    confidence = 0.5

    # Evidence bonus (capped at 0.3)
    evidence_bonus = min(context.skill_evidence_count * 0.1, 0.3)
    confidence += evidence_bonus

    # Completion history bonus (capped at 0.2)
    history_bonus = min(context.task_completion_history * 0.05, 0.2)
    confidence += history_bonus

    return min(confidence, 1.0)


# ── Public API ───────────────────────────────────────────────────────────────


def classify_task(
    task: Task,
    goal: Goal,
    context: AgencyContext,
) -> TaskAgency:
    """Classify a single task for agency-awareness.

    This is the main entry point for the agency-aware planning layer.
    It derives the execution mode and support mode for a task based on
    its properties, the goal context, and user state.

    Args:
        task: The task to classify.
        goal: The parent goal (provides context).
        context: Agency context signals (skill evidence, goal health, etc.).

    Returns:
        A TaskAgency with the derived classification.
    """
    execution_mode = select_execution_mode(task, goal, context)
    support_mode = select_support_mode(task, goal, context, execution_mode)
    confidence = _compute_confidence(
        task, goal, context, execution_mode, support_mode
    )

    reason = _build_reason(task, execution_mode, support_mode, context)

    return TaskAgency(
        execution_mode=execution_mode,
        support_mode=support_mode,
        reason=reason,
        confidence=confidence,
    )


def _build_reason(
    task: Task,
    execution_mode: ExecutionMode,
    support_mode: SupportMode,
    context: AgencyContext,
) -> str:
    """Build a human-readable explanation of the classification."""
    nature = _classify_task_nature(task)

    parts = []
    parts.append(f"Task nature: {nature}")
    parts.append(f"Execution: {execution_mode.value}")
    parts.append(f"Support: {support_mode.value}")

    if context.skill_evidence_count > 0:
        parts.append(f"Skill evidence: {context.skill_evidence_count}")
    if context.goal_stalled:
        parts.append("Goal stalled")

    return "; ".join(parts)


def classify_next_action(
    task: Task,
    goal: Goal,
    context: AgencyContext,
) -> TaskAgency:
    """Classify a next action for agency-awareness.

    This is a convenience wrapper around classify_task() for use in
    the next-action engine integration (Phase D2).
    """
    return classify_task(task, goal, context)


def derive_agency_context(
    skill_evidence_count: int = 0,
    goal_health: str = "healthy",
    goal_stalled: bool = False,
    task_completion_history: int = 0,
) -> AgencyContext:
    """Derive an AgencyContext from available signals.

    This is a convenience function for constructing an AgencyContext
    from individual signals.  In a fuller implementation, this would
    derive the context from PersonalState.
    """
    return AgencyContext(
        skill_evidence_count=skill_evidence_count,
        goal_health=goal_health,
        goal_stalled=goal_stalled,
        task_completion_history=task_completion_history,
    )
