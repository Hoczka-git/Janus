"""No-progress detector — four-class classification for stale goals.

Classifies each active goal into exactly one of five categories at query
time:

1. ``NO_DATA`` (brak danych) — insufficient information to determine
   progress/execution/effect state.
2. ``NO_EXECUTION`` (brak wykonania) — config/data exists but no execution
   evidence within the lookback window.
3. ``EXECUTION_WITHOUT_EFFECT`` (wykonanie bez efektu) — execution evidence
   exists but the goal outcome has not changed.
4. ``GOAL_ACHIEVED`` (cel osiągnięty) — goal outcome has been reached.
5. ``MAKING_PROGRESS`` — execution happened and effect is non-negligible.

The detector is a **read-only, on-demand classifier**. It does not persist
state, does not mutate goals, and does not schedule anything.

Design reference: ``docs/design/stale_no_progress_four_class_spec.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum

from janus.models.goal import Goal
from janus.models.goal_signal import GoalSignal
from janus.models.metric_snapshot import MetricSnapshot
from janus.services.activity_ingest import ActivityRecord, ActivityType
from janus.services.goal_health import (
    _has_metric_config,
    _reconstruct_goal_as_of,
    assess_goal_stall,
    _categorize_signal,
)
from janus.services.goal_progress import compute_goal_progress

logger = logging.getLogger(__name__)

# ── Constants (design §4.1) ─────────────────────────────────────────────────

# Lookback windows (days)
NO_DATA_LOOKBACK_DAYS = 30
NO_EXECUTION_LOOKBACK_DAYS = 30
EXECUTION_WITHOUT_EFFECT_WINDOW = 30
EFFECT_LOOKBACK_DAYS = 14
GOAL_ACHIEVED_CONFIRM_DAYS = 7

# Effect thresholds
EFFECT_THRESHOLD_PCT = 5.0
EFFECT_THRESHOLD_TASK_COMPLETED = 0
EFFECT_CURRENT_VALUE_TOLERANCE = 1e-6

# Activity types that count as execution evidence
_EXECUTION_ACTIVITY_TYPES = frozenset({
    ActivityType.TASK_COMPLETED,
    ActivityType.GOAL_PROGRESS,
    ActivityType.MILESTONE_COMPLETED,
})


# ── Classification enum ──────────────────────────────────────────────────────

class NoProgressClass(StrEnum):
    """Four-class classification of a goal's stale/no-progress state.

    Each active goal is classified into exactly one of these at query time.
    The classification is a diagnostic label — it does not replace the
    severity-based health_state from GoalHealthAssessment.
    """

    NO_DATA = "no_data"
    NO_EXECUTION = "no_execution"
    EXECUTION_WITHOUT_EFFECT = "execution_without_effect"
    GOAL_ACHIEVED = "goal_achieved"
    MAKING_PROGRESS = "making_progress"


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class NoProgressResult:
    """The classification result for a single goal.

    Attributes:
        goal_title: The goal being classified (identity string).
        classification: One of NoProgressClass.
        progress: Current progress % from compute_goal_progress, or None.
        signals: All GoalSignal values that fired for this goal (from the
                 existing health/attention pipeline), attached for diagnostic
                 context. Empty list when no signals fire.
        dominant_signal: Highest-severity signal, or None.
        reason: Human-readable explanation of why this classification was
                assigned. Suitable for display/debugging.
        evaluated_at: When the classification was computed.
        lookback_days: The lookback window used (may be per-goal override).
    """

    goal_title: str
    classification: NoProgressClass
    progress: float | None
    signals: list[GoalSignal] = field(default_factory=list)
    dominant_signal: GoalSignal | None = None
    reason: str = ""
    evaluated_at: datetime | None = None
    lookback_days: int = 30


# ── Query helpers ────────────────────────────────────────────────────────────

def is_stale(result: NoProgressResult) -> bool:
    """Return True when the classification indicates a stale/no-progress state.

    True for: NO_DATA, NO_EXECUTION, EXECUTION_WITHOUT_EFFECT.
    False for: GOAL_ACHIEVED, MAKING_PROGRESS.
    """
    return result.classification in (
        NoProgressClass.NO_DATA,
        NoProgressClass.NO_EXECUTION,
        NoProgressClass.EXECUTION_WITHOUT_EFFECT,
    )


def stale_reason_summary(result: NoProgressResult) -> str:
    """Short human-readable summary of the classification.

    Suitable for display in CLI output or attention items.
    """
    if result.classification == NoProgressClass.NO_DATA:
        return f"Brak danych: {result.reason}"
    if result.classification == NoProgressClass.NO_EXECUTION:
        return f"Brak wykonania: {result.reason}"
    if result.classification == NoProgressClass.EXECUTION_WITHOUT_EFFECT:
        return f"Wykonanie bez efektu: {result.reason}"
    if result.classification == NoProgressClass.GOAL_ACHIEVED:
        return f"Cel osiągnięty: {result.reason}"
    return f"W trakcie: {result.reason}"


# ── Internal helpers ─────────────────────────────────────────────────────────

def _get_lookback_days(goal: Goal, default: int) -> int:
    """Return the lookback window for a goal, respecting per-goal override."""
    return goal.inactivity_window_days or default


def _gather_execution_evidence(
    goal: Goal,
    today: date,
    activity_records: list[ActivityRecord] | None,
    completed_task_dates: dict[str, date] | None,
    window_days: int,
) -> bool:
    """Return True if execution evidence exists within the lookback window.

    Checks (in order):
    1. ActivityRecord list for execution-type activities in the window.
    2. goal.recent_activity entries with completed_at in the window.
    3. completed_task_dates for tasks completed in the window.
    """
    now = datetime.now().astimezone()
    window_start = now - timedelta(days=window_days)

    # 1. ActivityRecord list
    if activity_records:
        for record in activity_records:
            if record.type not in _EXECUTION_ACTIVITY_TYPES:
                continue
            if record.goal_title and record.goal_title != goal.title:
                continue
            if record.timestamp >= window_start:
                return True

    # 2. goal.recent_activity entries
    if goal.recent_activity:
        for entry in goal.recent_activity:
            completed_at = entry.get("completed_at")
            if completed_at is None:
                continue
            try:
                dt = datetime.fromisoformat(completed_at)
                if dt >= window_start:
                    return True
            except (ValueError, TypeError):
                continue

    # 3. completed_task_dates
    if completed_task_dates:
        for task_title, completion_date in completed_task_dates.items():
            if task_title not in goal.related_tasks:
                continue
            completion_dt = datetime.combine(
                completion_date, datetime.min.time()
            ).astimezone()
            if completion_dt >= window_start:
                return True

    return False


def _has_negligible_effect(
    goal: Goal,
    current_progress: float | None,
    metric_snapshots: list[MetricSnapshot] | None,
    completed_task_titles: set[str] | None,
    completed_task_dates: dict[str, date] | None,
    today: date,
) -> bool:
    """Return True when execution occurred but effect on the goal is negligible.

    Metric path: progress_delta over EFFECT_LOOKBACK_DAYS is below
    EFFECT_THRESHOLD_PCT, or current_value has not moved beyond tolerance.

    Task-based path: zero completions within the effect lookback window.
    """
    if current_progress is None:
        return False

    now = datetime.now().astimezone()
    lookback_start = now - timedelta(days=EFFECT_LOOKBACK_DAYS)

    # ── Metric path ───────────────────────────────────────────────────────────
    if _has_metric_config(goal) and goal.metric_name and metric_snapshots:
        relevant = [s for s in metric_snapshots if s.metric_name == goal.metric_name]
        past_snapshots = [s for s in relevant if s.timestamp <= lookback_start]
        if past_snapshots:
            past_snapshot = max(past_snapshots, key=lambda s: s.timestamp)
            past_goal = _reconstruct_goal_as_of(goal, past_snapshot.value)
            past_progress = compute_goal_progress(past_goal, completed_task_titles)
            if past_progress is not None:
                delta = current_progress - past_progress
                if 0 <= delta < EFFECT_THRESHOLD_PCT:
                    return True
                # Also check: current_value has not moved beyond tolerance
                if _value_moved_within_tolerance(goal, metric_snapshots, lookback_start):
                    return True

    # ── Task-based path ───────────────────────────────────────────────────────
    if goal.related_tasks and completed_task_titles is not None:
        recent_completions = 0
        if completed_task_dates:
            for rt in goal.related_tasks:
                if rt in completed_task_dates:
                    completion_dt = datetime.combine(
                        completed_task_dates[rt], datetime.min.time()
                    ).astimezone()
                    if completion_dt >= lookback_start:
                        recent_completions += 1
        else:
            # Without dates, count all completed related tasks
            recent_completions = sum(
                1 for rt in goal.related_tasks if rt in completed_task_titles
            )
        if recent_completions <= EFFECT_THRESHOLD_TASK_COMPLETED:
            return True

    return False


def _value_moved_within_tolerance(
    goal: Goal,
    metric_snapshots: list[MetricSnapshot],
    lookback_start: datetime,
) -> bool:
    """Return True if current_value has NOT moved beyond tolerance.

    Compares the most recent snapshot value against the goal's current_value.
    Returns True when the difference is within EFFECT_CURRENT_VALUE_TOLERANCE
    (i.e., the value has effectively not moved).
    """
    if not goal.metric_name or goal.current_value is None:
        return False

    relevant = [s for s in metric_snapshots if s.metric_name == goal.metric_name]
    if not relevant:
        return False

    most_recent = max(relevant, key=lambda s: s.timestamp)
    return abs(most_recent.value - goal.current_value) <= EFFECT_CURRENT_VALUE_TOLERANCE


def _attach_signals(
    goal: Goal,
    today: date,
    open_task_titles: set[str],
    all_task_titles: set[str],
    metric_snapshots: list[MetricSnapshot] | None,
    completed_task_dates: dict[str, date] | None,
    now: datetime,
) -> tuple[list[GoalSignal], GoalSignal | None]:
    """Attach existing health/attention signals for diagnostic context.

    Returns (signals, dominant_signal) — same pipeline as assess_goal_health.
    """
    stall_signals = assess_goal_stall(
        goal, today, open_task_titles, all_task_titles,
        metric_snapshots=metric_snapshots,
        completed_task_dates=completed_task_dates,
    )
    signals: list[GoalSignal] = []
    for stall_signal, category in stall_signals:
        signals.append(GoalSignal(
            signal=stall_signal.signal,
            score=stall_signal.score,
            reason=stall_signal.reason,
            timestamp=now,
            category=_categorize_signal(stall_signal.signal),
        ))
    dominant = max(signals, key=lambda s: s.score) if signals else None
    return signals, dominant


# ── Primary entry point ──────────────────────────────────────────────────────

def classify_no_progress(
    goal: Goal,
    today: date,
    open_task_titles: set[str],
    all_task_titles: set[str],
    completed_task_titles: set[str] | None = None,
    completed_task_dates: dict[str, date] | None = None,
    metric_snapshots: list[MetricSnapshot] | None = None,
    activity_records: list[ActivityRecord] | None = None,
) -> NoProgressResult:
    """Classify an active goal into one of the stale/no-progress categories.

    Args:
        goal: The goal to classify. Must be a parsed Goal object (from
              markdown_goals or the Goal model). Non-active goals return
              GOAL_ACHIEVED with a reason explaining the status.
        today: Current date (caller picks; use date.today() for live use,
               fixed date for tests).
        open_task_titles: Set of currently-open task titles (same convention
                          as assess_goal_stall).
        all_task_titles: Set of all task titles open + completed (same
                         convention as assess_goal_stall).
        completed_task_titles: Set of completed task titles. When None,
                               task-based progress cannot be computed and
                               task-based effect assessment is skipped.
        completed_task_dates: Optional mapping of task title → completion
                              date. When provided, enables time-filtered
                              execution evidence and effect assessment.
        metric_snapshots: Optional list of MetricSnapshot objects for this
                          goal. Enables metric progress_delta computation.
        activity_records: Optional list of ActivityRecord objects for this
                          goal. When None, execution evidence is gathered
                          from goal.recent_activity only.

    Returns:
        NoProgressResult with the classification, current progress, attached
        signals for context, and a human-readable reason.

    Raises:
        Nothing. Returns a result for every goal — non-active goals are
        classified as GOAL_ACHIEVED with an appropriate reason.
    """
    now = datetime.now().astimezone()
    lookback_days = _get_lookback_days(goal, NO_EXECUTION_LOOKBACK_DAYS)

    # ── Non-active goals ──────────────────────────────────────────────────────
    if goal.status == "completed":
        return NoProgressResult(
            goal_title=goal.title,
            classification=NoProgressClass.GOAL_ACHIEVED,
            progress=None,
            reason="Goal is explicitly marked as completed",
            evaluated_at=now,
            lookback_days=lookback_days,
        )
    if goal.status == "inactive":
        return NoProgressResult(
            goal_title=goal.title,
            classification=NoProgressClass.GOAL_ACHIEVED,
            progress=None,
            reason="Goal is inactive — out of scope for stale detection",
            evaluated_at=now,
            lookback_days=lookback_days,
        )

    # ── Class 4: goal_achieved (check first — terminal state) ───────────────
    progress = compute_goal_progress(goal, completed_task_titles)
    if progress == 100.0:
        return NoProgressResult(
            goal_title=goal.title,
            classification=NoProgressClass.GOAL_ACHIEVED,
            progress=progress,
            reason="Goal progress is 100% — target reached",
            evaluated_at=now,
            lookback_days=lookback_days,
        )

    # ── Gather execution evidence ─────────────────────────────────────────────
    exec_evidence = _gather_execution_evidence(
        goal, today, activity_records, completed_task_dates,
        window_days=lookback_days,
    )

    # ── Class 1: no_data ─────────────────────────────────────────────────────
    has_metric_config = _has_metric_config(goal)
    has_tasks = bool(goal.related_tasks)
    has_activity_data = bool(goal.recent_activity) or bool(metric_snapshots)

    if not has_metric_config and not has_tasks and not has_activity_data:
        signals, dominant = _attach_signals(
            goal, today, open_task_titles, all_task_titles,
            metric_snapshots, completed_task_dates, now,
        )
        return NoProgressResult(
            goal_title=goal.title,
            classification=NoProgressClass.NO_DATA,
            progress=progress,
            signals=signals,
            dominant_signal=dominant,
            reason=(
                "No metric config, no related tasks, and no activity data — "
                "insufficient information to assess progress"
            ),
            evaluated_at=now,
            lookback_days=lookback_days,
        )

    # ── Class 2: no_execution ────────────────────────────────────────────────
    if not exec_evidence:
        signals, dominant = _attach_signals(
            goal, today, open_task_titles, all_task_titles,
            metric_snapshots, completed_task_dates, now,
        )
        return NoProgressResult(
            goal_title=goal.title,
            classification=NoProgressClass.NO_EXECUTION,
            progress=progress,
            signals=signals,
            dominant_signal=dominant,
            reason=(
                f"No execution evidence within the last {lookback_days} days"
            ),
            evaluated_at=now,
            lookback_days=lookback_days,
        )

    # ── Class 3: execution_without_effect ────────────────────────────────────
    if _has_negligible_effect(
        goal, progress, metric_snapshots,
        completed_task_titles, completed_task_dates, today,
    ):
        signals, dominant = _attach_signals(
            goal, today, open_task_titles, all_task_titles,
            metric_snapshots, completed_task_dates, now,
        )
        return NoProgressResult(
            goal_title=goal.title,
            classification=NoProgressClass.EXECUTION_WITHOUT_EFFECT,
            progress=progress,
            signals=signals,
            dominant_signal=dominant,
            reason=(
                "Execution evidence exists but goal outcome has not changed "
                "significantly"
            ),
            evaluated_at=now,
            lookback_days=lookback_days,
        )

    # ── Fallthrough: making_progress ──────────────────────────────────────────
    signals, dominant = _attach_signals(
        goal, today, open_task_titles, all_task_titles,
        metric_snapshots, completed_task_dates, now,
    )
    return NoProgressResult(
        goal_title=goal.title,
        classification=NoProgressClass.MAKING_PROGRESS,
        progress=progress,
        signals=signals,
        dominant_signal=dominant,
        reason="Execution happened and effect is non-negligible",
        evaluated_at=now,
        lookback_days=lookback_days,
    )


# ── Batch entry point ────────────────────────────────────────────────────────

def classify_all_goals(
    goals: list[Goal],
    today: date,
    open_task_titles: set[str],
    all_task_titles: set[str],
    completed_task_titles: set[str] | None = None,
    completed_task_dates: dict[str, date] | None = None,
    metric_snapshots_by_goal: dict[str, list[MetricSnapshot]] | None = None,
    activity_records_by_goal: dict[str, list[ActivityRecord]] | None = None,
) -> list[NoProgressResult]:
    """Classify every goal in the provided list.

    Convenience wrapper around classify_no_progress for bulk assessment.
    Metric snapshots and activity records are looked up by goal title from
    the provided dicts (empty list when a goal key is missing).
    """
    results: list[NoProgressResult] = []
    for goal in goals:
        snapshots = None
        if metric_snapshots_by_goal is not None:
            snapshots = metric_snapshots_by_goal.get(goal.title)
        records = None
        if activity_records_by_goal is not None:
            records = activity_records_by_goal.get(goal.title)
        result = classify_no_progress(
            goal, today, open_task_titles, all_task_titles,
            completed_task_titles=completed_task_titles,
            completed_task_dates=completed_task_dates,
            metric_snapshots=snapshots,
            activity_records=records,
        )
        results.append(result)
    return results
