"""Goal health assessment service for Janus.

Provides the ``assess_goal_health()`` entry point and supporting dataclasses
that compute a goal's health state (healthy | watch | stalled | completed)
from the union of stall/deadline signals and progress/measurement/inactivity
signals.

This implements the design in
``docs/goal_health_progress_signals_stalled_detection_spec.md``.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from janus.models.goal import Goal
from janus.services.attention import StallSignal, assess_goal_stall
from janus.services.goal_progress import compute_goal_progress
from janus.integrations.metric_history import (
    MetricSnapshot,
    get_metric_snapshots,
)

logger = logging.getLogger(__name__)

# ── Constants (design §6.3) ─────────────────────────────────────────────────
DEADLINE_SOON_WINDOW_DAYS = 7
INACTIVITY_WINDOW_DAYS = 30
PROGRESS_SLOW_THRESHOLD = 5.0       # percentage points over lookback window
PROGRESS_LOOKBACK_DAYS = 14
MEASUREMENT_DUE_GRACE_DAYS = 2

# Frequency name → interval in days (design §9.2).
_FREQUENCY_INTERVAL_DAYS = {
    "daily": 1,
    "twice_weekly": 3,
    "weekly": 7,
    "biweekly": 14,
    "monthly": 30,
}


@dataclass
class GoalSignal:
    """A single signal emitted for a goal at a point in time.

    Attributes:
        signal: Signal identifier (matches StallSignal.signal).
        score: Severity score (higher = more severe).
        reason: Human-readable explanation.
        timestamp: When the signal was evaluated.
        stale_after: Optional auto-resolve duration (not used in v1).
    """

    signal: str
    score: int
    reason: str
    timestamp: datetime
    stale_after: timedelta | None = None


# Health states in order of severity for sorting.
_HEALTH_SEVERITY = {"healthy": 0, "watch": 1, "stalled": 2, "completed": 3}


def _health_from_signals(signals: list[GoalSignal]) -> str:
    """Resolve a health state from the highest-severity signal that fired.

    Implements design §4.2 (Health State Resolution Order). Returns
    ``healthy`` when no signals fire.
    """
    if not signals:
        return "healthy"

    # Severity order maps each signal to the health state it produces.
    # The highest-scoring signal determines the health state.
    signal_to_state = {
        "goal_overdue": "stalled",
        "goal_deadline_today": "watch",
        "goal_deadline_soon": "healthy",  # exception below
        "milestone_slipped": "stalled",
        "milestone_deadline_soon": "healthy",  # exception below
        "goal_stalled": "stalled",
        "goal_inactive": "watch",
        "no_recent_activity": "stalled",
        "progress_slow": "watch",
        "measurement_due": "watch",
    }

    best_signal = max(signals, key=lambda s: s.score)

    # Exception: deadline_soon / milestone_deadline_soon do NOT downgrade to
    # watch if there are open related tasks AND no progress_slow signal.
    # (design §4.2 exception + §135 / §135)
    if best_signal.signal in ("goal_deadline_soon", "milestone_deadline_soon"):
        # Check whether open tasks exist — we need that info. Since
        # assess_goal_health receives context, we check via the signal set:
        # progress_slow would only fire if tasks are open but progress is slow.
        # If progress_slow is NOT among the signals, and there are open tasks,
        # the goal is healthy (actively working toward the deadline).
        has_progress_slow = any(s.signal == "progress_slow" for s in signals)
        if not has_progress_slow:
            return "healthy"
        return "watch"  # deadline_soon + progress_slow → watch

    return signal_to_state.get(best_signal.signal, "healthy")


def _compute_progress_slow(
    goal: Goal,
    today: date,
    metric_snapshots: list[MetricSnapshot],
    completed_task_titles: set[str] | None,
) -> GoalSignal | None:
    """Evaluate the ``progress_slow`` signal (design §8).

    Fires when the goal has been active for at least
    ``PROGRESS_LOOKBACK_DAYS`` and the progress delta over that window is
    below ``PROGRESS_SLOW_THRESHOLD``.
    """
    if goal.status != "active":
        return None

    now = datetime.now().astimezone()
    lookback_start = now - timedelta(days=PROGRESS_LOOKBACK_DAYS)

    # Need at least some progress configuration
    has_metric = (
        goal.metric_name
        and goal.target_value is not None
        and goal.direction
        and goal.start_value is not None
        and goal.current_value is not None
    )
    has_tasks = bool(goal.related_tasks)
    if not has_metric and not has_tasks:
        return None

    current_progress = compute_goal_progress(goal, completed_task_titles)
    if current_progress is None:
        return None

    # For metric-based goals, compute lookback progress from snapshots.
    if has_metric:
        relevant = [s for s in metric_snapshots if s.metric_name == goal.metric_name]
        # Find the most recent snapshot on or before lookback_start
        past_snapshots = [s for s in relevant if s.timestamp <= lookback_start]
        if not past_snapshots:
            # Not enough history — lookback window has not elapsed.
            return None
        past_snapshot = max(past_snapshots, key=lambda s: s.timestamp)

        # Reconstruct a goal-as-of snapshot to compute past progress.
        past_goal = Goal(
            title=goal.title,
            status=goal.status,
            deadline=goal.deadline,
            metric_name=goal.metric_name,
            metric_unit=goal.metric_unit,
            start_value=goal.start_value,
            current_value=past_snapshot.value,
            target_value=goal.target_value,
            direction=goal.direction,
            related_tasks=goal.related_tasks,
            milestones=goal.milestones,
            measurement_requirements=goal.measurement_requirements,
            research_artifact_titles=goal.research_artifact_titles,
        )
        past_progress = compute_goal_progress(past_goal, completed_task_titles)
        if past_progress is None:
            return None
        progress_delta = current_progress - past_progress
    else:
        # Task-based goals: without completion timestamps we use the current
        # completed set (conservative). The signal may be weaker until task
        # completion timestamps are recorded (design §13.4).
        progress_delta = current_progress

    if progress_delta < 0:
        # Regression is a different problem (design §13.3 / open question 3).
        return None

    if progress_delta < PROGRESS_SLOW_THRESHOLD:
        # The lookback check: ensure the goal has existed for at least the
        # lookback window. Without a creation date stored, we check whether
        # a metric snapshot exists that is at least PROGRESS_LOOKBACK_DAYS old.
        has_lookback_history = has_metric and any(
            s.timestamp <= (now - timedelta(days=PROGRESS_LOOKBACK_DAYS))
            for s in metric_snapshots
            if s.metric_name == goal.metric_name
        )
        if has_metric and not has_lookback_history:
            return None
        if not has_metric and not has_tasks:
            return None
        return GoalSignal(
            signal="progress_slow",
            score=40,
            reason=(
                f"Progress increased only {progress_delta:.1f} percentage "
                f"points over the last {PROGRESS_LOOKBACK_DAYS} days "
                f"(threshold: {PROGRESS_SLOW_THRESHOLD:.0f}%)"
            ),
            timestamp=now,
        )

    return None


def _compute_measurement_due(
    goal: Goal,
    today: date,
    metric_snapshots: list[MetricSnapshot],
) -> GoalSignal | None:
    """Evaluate the ``measurement_due`` signal (design §9).

    Fires when at least one measurement requirement's frequency window has
    elapsed without a new snapshot.
    """
    if goal.status != "active":
        return None
    if not goal.measurement_requirements:
        return None

    now = datetime.now().astimezone()
    overdue_metrics: list[str] = []

    for req in goal.measurement_requirements:
        metric = req.get("metric")
        if not metric:
            continue
        frequency = req.get("frequency", "daily")
        interval_days = req.get("interval_days")

        if frequency == "custom" and interval_days is None:
            continue
        if frequency not in _FREQUENCY_INTERVAL_DAYS and frequency != "custom":
            continue

        if frequency == "custom":
            interval = interval_days
        else:
            interval = _FREQUENCY_INTERVAL_DAYS[frequency]
        assert interval is not None  # guaranteed by guards above
        due_after = interval + MEASUREMENT_DUE_GRACE_DAYS

        # Find most recent snapshot for this metric
        metric_snaps = [s for s in metric_snapshots if s.metric_name == metric]
        if not metric_snaps:
            overdue_metrics.append(metric)
            continue
        most_recent = max(metric_snaps, key=lambda s: s.timestamp)
        days_since = (now - most_recent.timestamp).days
        if days_since >= due_after:
            overdue_metrics.append(metric)

    if overdue_metrics:
        return GoalSignal(
            signal="measurement_due",
            score=45,
            reason=f"Overdue measurements: {', '.join(overdue_metrics)}",
            timestamp=now,
        )
    return None


@dataclass
class GoalHealthAssessment:
    """The computed health assessment for a single goal.

    Health state is a derived attribute — it is computed on demand from
    current signals and NOT persisted (design §13.1).
    """

    goal_title: str
    health_state: str                    # healthy | watch | stalled | completed
    signals: list[GoalSignal]            # all signals that fired
    dominant_signal: GoalSignal | None   # highest-severity signal (None if healthy)
    progress: float | None               # current progress % (from compute_goal_progress)
    progress_delta: float | None         # change in progress over lookback window
    days_since_last_activity: int | None # days since last metric update or task completion
    measurement_overdue_count: int       # number of overdue measurement requirements
    evaluated_at: datetime


def assess_goal_health(
    goal: Goal,
    today: date,
    open_task_titles: set[str],
    all_task_titles: set[str],
    metric_snapshots: list[MetricSnapshot] | None = None,
    completed_task_dates: dict[str, date] | None = None,
) -> GoalHealthAssessment | None:
    """Compute the health assessment for a single goal.

    Args:
        goal: The goal to assess (caller should pass active goals).
        today: Current date.
        open_task_titles: Currently-open task titles.
        all_task_titles: All task titles (open + completed) from raw file.
        metric_snapshots: Pre-loaded snapshots for this goal. If None,
            loaded from ``metric_history``.
        completed_task_dates: Mapping of task title → completion date. If
            None, task-based progress delta is not computed precisely.

    Returns:
        A GoalHealthAssessment, or None if the goal should be excluded
        (completed goals return a completed-state assessment; inactive goals
        return None entirely per design §4.4).
    """
    now = datetime.now().astimezone()

    # Completed goals — always completed state, no signals.
    if goal.status == "completed":
        return GoalHealthAssessment(
            goal_title=goal.title,
            health_state="completed",
            signals=[],
            dominant_signal=None,
            progress=compute_goal_progress(goal, None),
            progress_delta=None,
            days_since_last_activity=None,
            measurement_overdue_count=0,
            evaluated_at=now,
        )

    # Inactive goals — excluded from health assessment entirely.
    if goal.status == "inactive":
        return None

    # Active goals — the main path.
    signals: list[GoalSignal] = []

    # Load metric snapshots if not provided (needed by assess_goal_stall
    # for no_recent_activity and by progress_slow computation).
    if metric_snapshots is None:
        metric_snapshots = get_metric_snapshots(goal.title)

    # 1. Existing stall/deadline signals from the attention engine.
    stall_signals = assess_goal_stall(
        goal, today, open_task_titles, all_task_titles,
        metric_snapshots=metric_snapshots,
        completed_task_dates=completed_task_dates,
    )
    # Convert existing StallSignal tuples to GoalSignal objects.
    for stall_signal, _category in stall_signals:
        signals.append(GoalSignal(
            signal=stall_signal.signal,
            score=stall_signal.score,
            reason=stall_signal.reason,
            timestamp=now,
        ))

    # 2. progress_slow signal.
    progress_slow = _compute_progress_slow(
        goal, today, metric_snapshots,
        set(completed_task_dates.keys()) if completed_task_dates else None,
    )
    if progress_slow is not None:
        signals.append(progress_slow)

    # 3. measurement_due signal.
    measurement_due = _compute_measurement_due(goal, today, metric_snapshots)
    if measurement_due is not None:
        signals.append(measurement_due)
        # Also count overdue measurements.
        # (measurement_overdue_count computed below separately)

    # 4. no_recent_activity is handled by assess_goal_stall above (passed
    #    metric_snapshots). No duplicate computation needed here — the signal
    #    is already in `signals` if it fired and wasn't suppressed.

    # Compute progress.
    completed_titles = set(completed_task_dates.keys()) if completed_task_dates else None
    current_progress = compute_goal_progress(goal, completed_titles)

    # Compute progress_delta.
    progress_delta = _compute_progress_delta(goal, today, metric_snapshots, completed_titles)

    # Compute days_since_last_activity.
    days_since_activity = _compute_days_since_last_activity(
        metric_snapshots, completed_task_dates, today,
    )

    # Count overdue measurements.
    overdue_count = _count_overdue_measurements(goal, today, metric_snapshots)

    # Resolve health state.
    health_state = _health_from_signals(signals)

    # Dominant signal = highest-scoring.
    dominant = max(signals, key=lambda s: s.score) if signals else None

    return GoalHealthAssessment(
        goal_title=goal.title,
        health_state=health_state,
        signals=signals,
        dominant_signal=dominant,
        progress=current_progress,
        progress_delta=progress_delta,
        days_since_last_activity=days_since_activity,
        measurement_overdue_count=overdue_count,
        evaluated_at=now,
    )


def _compute_progress_delta(
    goal: Goal,
    today: date,
    metric_snapshots: list[MetricSnapshot],
    completed_task_titles: set[str] | None,
) -> float | None:
    """Compute the progress delta over the lookback window (design §8.2)."""
    if goal.status != "active":
        return None

    has_metric = (
        goal.metric_name
        and goal.target_value is not None
        and goal.direction
        and goal.start_value is not None
        and goal.current_value is not None
    )
    has_tasks = bool(goal.related_tasks)
    if not has_metric and not has_tasks:
        return None

    now = datetime.now().astimezone()
    lookback_start = now - timedelta(days=PROGRESS_LOOKBACK_DAYS)

    current_progress = compute_goal_progress(goal, completed_task_titles)
    if current_progress is None:
        return None

    if has_metric:
        relevant = [s for s in metric_snapshots if s.metric_name == goal.metric_name]
        past_snapshots = [s for s in relevant if s.timestamp <= lookback_start]
        if not past_snapshots:
            return None  # insufficient history
        past_snapshot = max(past_snapshots, key=lambda s: s.timestamp)
        past_goal = Goal(
            title=goal.title,
            status=goal.status,
            deadline=goal.deadline,
            metric_name=goal.metric_name,
            metric_unit=goal.metric_unit,
            start_value=goal.start_value,
            current_value=past_snapshot.value,
            target_value=goal.target_value,
            direction=goal.direction,
            related_tasks=goal.related_tasks,
            milestones=goal.milestones,
            measurement_requirements=goal.measurement_requirements,
            research_artifact_titles=goal.research_artifact_titles,
        )
        past_progress = compute_goal_progress(past_goal, completed_task_titles)
        if past_progress is None:
            return None
        return current_progress - past_progress

    # Task-based: use current completed state (conservative, §13.4).
    return current_progress


def _compute_days_since_last_activity(
    metric_snapshots: list[MetricSnapshot],
    completed_task_dates: dict[str, date] | None,
    today: date,
) -> int | None:
    """Days since the most recent metric snapshot or task completion.

    Returns 0 if activity happened today. Returns None if no activity
    exists at all (no snapshots and no completions).
    """
    now = datetime.now().astimezone()
    candidates: list[datetime] = []
    for s in metric_snapshots:
        candidates.append(s.timestamp)
    if completed_task_dates:
        for d in completed_task_dates.values():
            candidates.append(
                datetime.combine(d, datetime.min.time()).astimezone()
            )
    if not candidates:
        return None
    most_recent = max(candidates)
    delta = now - most_recent
    return max(0, delta.days)


def _count_overdue_measurements(
    goal: Goal,
    today: date,
    metric_snapshots: list[MetricSnapshot],
) -> int:
    """Count how many measurement requirements are overdue (design §9)."""
    if not goal.measurement_requirements:
        return 0
    now = datetime.now().astimezone()
    overdue = 0
    for req in goal.measurement_requirements:
        metric = req.get("metric")
        if not metric:
            continue
        frequency = req.get("frequency", "daily")
        interval_days = req.get("interval_days")
        if frequency == "custom" and interval_days is None:
            continue
        if frequency not in _FREQUENCY_INTERVAL_DAYS and frequency != "custom":
            continue
        if frequency == "custom":
            interval = interval_days
        else:
            interval = _FREQUENCY_INTERVAL_DAYS[frequency]
        assert interval is not None  # guaranteed by guards above
        due_after = interval + MEASUREMENT_DUE_GRACE_DAYS
        metric_snaps = [s for s in metric_snapshots if s.metric_name == metric]
        if not metric_snaps:
            overdue += 1
            continue
        most_recent = max(metric_snaps, key=lambda s: s.timestamp)
        if (now - most_recent.timestamp).days >= due_after:
            overdue += 1
    return overdue
