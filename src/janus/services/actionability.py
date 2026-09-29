"""Actionability scoring filter for detected problems.

This module implements a distinct, testable filter stage that sits between
problem detection (``audit_goal_integrity``) and task creation.  Each detected
problem is scored for actionability; actionable problems trigger task creation
while non-actionable ones are recorded without side effects.

Design reference: ``docs/design/actionability_scoring.md``
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from janus.models.goal_integrity_report import GoalIntegrityIssue
from janus.models.task import Task

logger = logging.getLogger(__name__)

# ── Actionability threshold ──────────────────────────────────────────────────
# Problems scoring >= this threshold are considered actionable.
DEFAULT_ACTIONABILITY_THRESHOLD = 40

# ── Scoring weights ──────────────────────────────────────────────────────────
_SEVERITY_WEIGHTS: dict[str, int] = {
    "error": 50,
    "warning": 30,
    "info": 10,
}

# Issue codes that have a deterministic repair path (from goal_integrity_repair).
_REPAIRABLE_CODES: frozenset[str] = frozenset({
    "UNKNOWN_GOAL_REFERENCE",
    "INVALID_RELATED_TASK",
    "CIRCULAR_REFERENCE",
    "ORPHANED_TASK",
    "RELATIONSHIP_COUNT_MISMATCH",
})

# Bonus for having a repairable code.
_REPAIRABLE_BONUS = 20

# Bonus for having both goal_id and task_id (sufficient context to act).
_CONTEXT_BONUS = 10

# Bonus for having structured details (enables programmatic repair).
_DETAILS_BONUS = 10


@dataclass
class ActionabilityResult:
    """Result of scoring a single detected problem for actionability.

    Attributes:
        issue: The original GoalIntegrityIssue that was scored.
        score: Computed actionability score (0–100+).
        is_actionable: True if score >= threshold.
        reasons: Human-readable list of scoring factors.
        suggested_task_title: If actionable, a suggested task title.
        suggested_task_metadata: If actionable, metadata for task creation.
    """
    issue: GoalIntegrityIssue
    score: int
    is_actionable: bool
    reasons: list[str] = field(default_factory=list)
    suggested_task_title: str | None = None
    suggested_task_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionabilityReport:
    """Aggregate report from filtering a batch of detected problems.

    Attributes:
        results: One ActionabilityResult per input issue.
        actionable: Subset of results that passed the threshold.
        recorded: Subset of results that did not pass the threshold.
        evaluated_at: When the filter was run.
    """
    results: list[ActionabilityResult] = field(default_factory=list)
    evaluated_at: datetime | None = None

    @property
    def actionable(self) -> list[ActionabilityResult]:
        return [r for r in self.results if r.is_actionable]

    @property
    def recorded(self) -> list[ActionabilityResult]:
        return [r for r in self.results if not r.is_actionable]

    @property
    def actionable_count(self) -> int:
        return len(self.actionable)

    @property
    def recorded_count(self) -> int:
        return len(self.recorded)


def score_actionability(
    issue: GoalIntegrityIssue,
    threshold: int = DEFAULT_ACTIONABILITY_THRESHOLD,
) -> ActionabilityResult:
    """Score a single detected problem for actionability.

    The scoring algorithm is deterministic and based on four factors:

    1. **Severity** (weight: error=50, warning=30, info=10) — errors are
       almost always actionable; info-level issues rarely are.
    2. **Repair path** (+20) — issues with a known deterministic repair
       (codes in ``_REPAIRABLE_CODES``) are more actionable than those
       requiring manual investigation.
    3. **Context completeness** (+10) — issues with both ``goal_id`` and
       ``task_id`` provide sufficient context to act without further
       investigation.
    4. **Structured details** (+10) — issues with a ``details`` dict enable
       programmatic repair.

    A problem is actionable when its total score >= *threshold* (default 40).

    Args:
        issue: The detected problem to score.
        threshold: Minimum score for actionability.

    Returns:
        An ActionabilityResult with the score and actionability decision.
    """
    score = 0
    reasons: list[str] = []

    # 1. Severity weight
    sev_weight = _SEVERITY_WEIGHTS.get(issue.severity, 0)
    score += sev_weight
    if sev_weight > 0:
        reasons.append(f"severity={issue.severity} (+{sev_weight})")

    # 2. Repairable code bonus
    if issue.code in _REPAIRABLE_CODES:
        score += _REPAIRABLE_BONUS
        reasons.append(f"repairable_code={issue.code} (+{_REPAIRABLE_BONUS})")

    # 3. Context completeness bonus
    if issue.goal_id and issue.task_id:
        score += _CONTEXT_BONUS
        reasons.append(f"has_goal_and_task_context (+{_CONTEXT_BONUS})")

    # 4. Structured details bonus
    if issue.details:
        score += _DETAILS_BONUS
        reasons.append(f"has_structured_details (+{_DETAILS_BONUS})")

    is_actionable = score >= threshold

    # Build suggested task title and metadata for actionable issues
    suggested_title = None
    suggested_metadata: dict[str, Any] = {}
    if is_actionable:
        suggested_title = _derive_task_title(issue)
        suggested_metadata = _derive_task_metadata(issue)

    return ActionabilityResult(
        issue=issue,
        score=score,
        is_actionable=is_actionable,
        reasons=reasons,
        suggested_task_title=suggested_title,
        suggested_task_metadata=suggested_metadata,
    )


def _derive_task_title(issue: GoalIntegrityIssue) -> str:
    """Derive a concise task title from an actionable issue."""
    # Use the issue code as a prefix for searchability
    prefix = issue.code.replace("_", " ").title()

    if issue.goal_id and issue.task_id:
        return f"Fix {prefix}: {issue.task_id} → {issue.goal_id}"
    elif issue.goal_id:
        return f"Fix {prefix}: {issue.goal_id}"
    elif issue.task_id:
        return f"Fix {prefix}: {issue.task_id}"
    else:
        return f"Fix {prefix}"


def _derive_task_metadata(issue: GoalIntegrityIssue) -> dict[str, Any]:
    """Derive task metadata from an actionable issue."""
    metadata: dict[str, Any] = {
        "source": "actionability_filter",
        "issue_code": issue.code,
        "severity": issue.severity,
    }
    if issue.goal_id:
        metadata["goal"] = issue.goal_id
    if issue.task_id:
        metadata["task"] = issue.task_id
    if issue.details:
        metadata["details"] = issue.details
    return metadata


def filter_actionable(
    issues: list[GoalIntegrityIssue],
    threshold: int = DEFAULT_ACTIONABILITY_THRESHOLD,
) -> ActionabilityReport:
    """Filter a batch of detected problems for actionability.

    This is the main entry point for the actionability filter stage.  It
    scores each issue and returns an ActionabilityReport with the results.

    Args:
        issues: Detected problems from the audit.
        threshold: Minimum score for actionability.

    Returns:
        An ActionabilityReport with actionable and recorded subsets.
    """
    results = [score_actionability(issue, threshold) for issue in issues]
    return ActionabilityReport(
        results=results,
        evaluated_at=datetime.now().astimezone(),
    )


# ── Task creation integration ────────────────────────────────────────────────

def create_tasks_for_actionable(
    report: ActionabilityReport,
    task_creator: Callable[[str, dict[str, Any]], Task] | None = None,
) -> list[Task]:
    """Create tasks for all actionable problems in the report.

    For each actionable result, this function creates a task with the
    suggested title and metadata.  Non-actionable problems are recorded
    (logged) without creating tasks.

    Args:
        report: The ActionabilityReport from ``filter_actionable``.
        task_creator: Optional callable that creates a task.  Must accept
            ``(title: str, metadata: dict)`` and return a ``Task``.
            Defaults to ``_default_task_creator`` which calls
            ``janus.services.tasks.add_task``.

    Returns:
        List of created Task objects (one per actionable problem).
    """
    if task_creator is None:
        task_creator = _default_task_creator

    created: list[Task] = []
    for result in report.actionable:
        if not result.suggested_task_title:
            continue
        try:
            task = task_creator(
                result.suggested_task_title,
                result.suggested_task_metadata,
            )
            created.append(task)
            logger.info(
                "Created task for actionable issue %s (score=%d): %s",
                result.issue.code, result.score, result.suggested_task_title,
            )
        except Exception as exc:
            logger.error(
                "Failed to create task for issue %s: %s",
                result.issue.code, exc,
            )

    # Record non-actionable issues (log only, no task creation)
    for result in report.recorded:
        logger.info(
            "Recorded non-actionable issue %s (score=%d): %s",
            result.issue.code, result.score, result.issue.message,
        )

    return created


def _default_task_creator(title: str, metadata: dict[str, Any]) -> Task:
    """Default task creator that uses the Janus task service.

    This function is separated so tests can inject a mock task creator
    without touching the real task persistence layer.
    """
    from janus.services.tasks import add_task

    # Extract goal reference for extra_metadata if present
    extra_metadata: list[str] = []
    if "goal" in metadata:
        extra_metadata.append(f"goal: {metadata['goal']}")

    task = add_task(title=title)
    task.state = "todo"
    if extra_metadata:
        task.extra_metadata = extra_metadata
    return task


# ── Pipeline integration ─────────────────────────────────────────────────────

def run_actionability_pipeline(
    issues: list[GoalIntegrityIssue],
    threshold: int = DEFAULT_ACTIONABILITY_THRESHOLD,
    task_creator: Callable[[str, dict[str, Any]], Task] | None = None,
) -> tuple[ActionabilityReport, list[Task]]:
    """Run the full actionability pipeline: filter → create tasks.

    This is a convenience function that combines ``filter_actionable`` and
    ``create_tasks_for_actionable`` into a single call.

    Args:
        issues: Detected problems from the audit.
        threshold: Minimum score for actionability.
        task_creator: Optional callable for task creation.

    Returns:
        Tuple of (ActionabilityReport, list of created Tasks).
    """
    report = filter_actionable(issues, threshold)
    created = create_tasks_for_actionable(report, task_creator)
    return report, created
