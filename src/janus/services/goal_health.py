"""Goal health assessment — composite health state and progress signals.

This module is the single entry point for computing a goal's health state from
the current set of signals firing for that goal.  It delegates the existing
deadline/stall/inactivity signals to ``assess_goal_stall()`` (attention engine)
and adds three new signals:

* ``progress_slow``  — open tasks exist but progress delta over the lookback
  window is below threshold.
* ``measurement_due`` — a measurement requirement's frequency window has
  elapsed without a fresh snapshot.
* ``no_recent_activity`` — active goal with no metric snapshot and no task
  completion within the inactivity window.

The resulting ``GoalHealthAssessment`` is a derived, on-demand view — it is
NOT persisted.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from janus.models.goal import Goal
from janus.services.attention import assess_goal_stall, StallSignal, _parse_deadline
from janus.services.goal_progress import compute_goal_progress
from janus.integrations.metric_history import MetricSnapshot, load_snapshots

# ─── Thresholds & timing (§6.3) ───────────────────────────────────────────────

#: Days before a deadline that triggers ``goal_deadline_soon``.
DEADLINE_SOON_WINDOW_DAYS = 7

#: Default inactivity window — days without metric/task activity before
#: ``no_recent_activity`` fires.
DEFAULT_INACTIVITY_WINDOW_DAYS = 30

#: Minimum progress (percentage points) over the lookback window to avoid
#: the ``progress_slow`` signal.
PROGRESS_SLOW_THRESHOLD = 5.0

#: Lookback window (days) over which progress delta is measured.
PROGRESS_LOOKBACK_DAYS = 14

#: Grace period (days) after a measurement frequency interval before
#: ``measurement_due`` fires.
MEASUREMENT_DUE_GRACE_DAYS = 2

#: Mapping of measurement frequency strings to interval days.
_FREQUENCY_INTERVAL_DAYS = {
    "daily": 1,
    "twice_weekly": 3,
    "weekly": 7,
    "biweekly": 14,
    "monthly": 30,
}


# ─── Signal data model (§5.2) ───────────────────────────────────────────────

@dataclass
class GoalSignal:
    """A single signal emitted for a goal at a point in time.

    ``signal`` matches the ``StallSignal.signal`` identifier so that
    existing signals and new signals share a common vocabulary.
    """

    signal: str
    score: int
    reason: str
    timestamp: datetime
    stale_after: timedelta | None = None


# ─── Health state constants ─────────────────────────────────────────────────

HEALTH_HEALTHY = "healthy"
HEALTH_WATCH = "watch"
HEALTH_STALLED = "stalled"
HEALTH_COMPLETED = "completed"

#: Severity order (lowest to highest) used by the resolution rule (§4.2).
#: Higher score = more severe.
_SIGNAL_SEVERITY: dict[str, int] = {
    "goal_deadline_soon": 60,
    "milestone_deadline_soon": 55,
    "measurement_due": 45,
    "progress_slow": 40,
    "goal_stalled": 40,
    "goal_inactive": 30,
    "no_recent_activity": 35,
    "milestone_slipped": 50,
    "goal_overdue": 100,
    "goal_deadline_today": 90,
}

#: Map signal → health state when that signal is the dominant one.
_SIGNAL_HEALTH: dict[str, str] = {
    "goal_deadline_soon": HEALTH_WATCH,
    "milestone_deadline_soon": HEALTH_WATCH,
    "measurement_due": HEALTH_WATCH,
    "progress_slow": HEALTH_WATCH,
    "goal_stalled": HEALTH_STALLED,
    "milestone_slipped": HEALTH_STALLED,
    "goal_overdue": HEALTH_STALLED,
    "no_recent_activity": HEALTH_STALLED,
    "goal_inactive": HEALTH_WATCH,
    "goal_deadline_today": HEALTH_STALLED,
}


# ─── Result dataclass (§5.4) ────────────────────────────────────────────────

@dataclass
class GoalHealthAssessment:
    """The full health assessment for a single goal."""

    goal_title: str
    health_state: str | None  # healthy | watch | stalled | completed | None
    signals: list[GoalSignal] = field(default_factory=list)
    dominant_signal: GoalSignal | None = None
    progress: float | None = None
    progress_delta: float | None = None
    days_since_last_activity: int | None = None
    measurement_overdue_count: int = 0
    evaluated_at: datetime = field(default_factory=lambda: datetime.now().astimezone())


# ─── Constants for signal categories ────────────────────────────────────────

#: Signals that, by themselves, do NOT downgrade a goal that has open related
#: tasks and is making progress (§4.2 exception).
_SOFT_SIGNALS = {"goal_deadline_soon", "milestone_deadline_soon"}


# ─── New signal computation functions ───────────────────────────────────────

def _compute_progress_slow_signal(
    goal: Goal,
    today: date,
    metric_snapshots: list[MetricSnapshot],
) -> GoalSignal | None:
    """Compute the ``progress_slow`` signal (§8).

    Fires when the goal is active, has progress configuration, the lookback
    window has elapsed, and the progress delta is below the threshold.
    """
    if goal.status != "active":
        return None

    # Need progress configuration: metric OR task-based with completed tasks.
    has_metric = (
        goal.metric_name
        and goal.target_value is not None
        and goal.direction is not None
        and goal.start_value is not None
        and goal.current_value is not None
    )
    has_tasks = len(goal.related_tasks) > 0
    if not has_metric and not has_tasks:
        return None

    current_progress = compute_goal_progress(goal)
    if current_progress is None:
        return None

    # Determine the earliest timestamp that the lookback window starts at.
    # For metric goals, we need a snapshot at or before the lookback start.
    if has_metric:
        lookback_start = today - timedelta(days=PROGRESS_LOOKBACK_DAYS)
        lookback_start_dt = datetime.combine(
            lookback_start, datetime.min.time(), tzinfo=timezone.utc
        )

        # Find the most recent snapshot at or before the lookback start.
        past_snapshots = [
            s for s in metric_snapshots
            if s.timestamp <= lookback_start_dt
        ]
        if not past_snapshots:
            # Not enough history — lookback window hasn't elapsed for this goal.
            return None

        past_snapshot = max(past_snapshots, key=lambda s: s.timestamp)

        # Recompute progress using the past metric value.
        past_goal = Goal(
            title=goal.title,
            description=goal.description,
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
            inactivity_window_days=goal.inactivity_window_days,
        )
        past_progress = compute_goal_progress(past_goal)
        if past_progress is None:
            return None

        # Only compute delta if the lookback window has actually elapsed
        # since the oldest snapshot.
        oldest_snapshot = min(metric_snapshots, key=lambda s: s.timestamp)
        if (today - oldest_snapshot.timestamp.date()).days < PROGRESS_LOOKBACK_DAYS:
            return None

    else:
        # Task-based goal — without completion timestamps we use current
        # state. Per spec §13.4 this is imprecise: if no tasks are completed
        # yet, progress is 0 and delta is 0, which would always fire.
        # We suppress progress_slow when there's no meaningful history.
        completed_count = sum(
            1 for rt in goal.related_tasks
            if _is_task_completed(rt)
        )
        if completed_count == 0:
            return None  # No completed tasks yet — can't assess slowness.

        past_progress = 0.0
        if completed_count == len(goal.related_tasks):
            # All tasks were completed — delta is 100, not slow.
            past_progress = 0.0  # they were all 0 before the last completion

    progress_delta = current_progress - past_progress

    # Out of scope: negative delta indicating regression (§13.3).
    # progress_slow does NOT fire for regression.
    if progress_delta < 0:
        return None

    if progress_delta < PROGRESS_SLOW_THRESHOLD:
        return GoalSignal(
            signal="progress_slow",
            score=40,
            timestamp=datetime.now().astimezone(),
            reason=(
                f"Progress {progress_delta:.1f}% over last "
                f"{PROGRESS_LOOKBACK_DAYS} days (threshold: "
                f"{PROGRESS_SLOW_THRESHOLD:.0f}%)"
            ),
        )

    return None


def _is_task_completed(task_title: str) -> bool:
    """Check if a task title is completed by reading tasks.md.

    This is a lightweight helper used only for task-based progress_slow
    estimation.  In the initial implementation task completion timestamps
    are not recorded (see spec §14.1), so this just checks current state.
    """
    from janus.integrations.markdown_tasks import TASKS_PATH

    if not TASKS_PATH.exists():
        return False
    titles = _get_completed_task_titles(TASKS_PATH)
    return task_title in titles


def _get_completed_task_titles(tasks_path) -> set[str]:
    """Return the set of completed task titles from a tasks.md file."""
    titles: set[str] = set()
    if not tasks_path.exists():
        return titles
    with tasks_path.open() as f:
        for line in f:
            line = line.strip()
            if line.startswith("- [x]"):
                content = line[5:].strip()
                title = content.split(" | ")[0].strip()
                if title:
                    titles.add(title)
    return titles


# ─── measurement_due signal (§9) ────────────────────────────────────────────

def _compute_measurement_due_signal(
    goal: Goal,
    today: date,
    metric_snapshots: list[MetricSnapshot],
) -> tuple[GoalSignal | None, int]:
    """Compute the ``measurement_due`` signal (§9).

    Returns ``(signal, overdue_count)``.
    """
    if goal.status != "active":
        return None, 0
    if not goal.measurement_requirements:
        return None, 0

    overdue_metrics: list[str] = []

    for req in goal.measurement_requirements:
        metric = req.get("metric")
        if not metric:
            continue

        frequency = req.get("frequency", "daily")
        interval_days = req.get("interval_days")
        if frequency not in _FREQUENCY_INTERVAL_DAYS and frequency != "custom":
            continue  # Unknown frequency — skip
        if frequency == "custom":
            if not interval_days or interval_days <= 0:
                continue
            interval = interval_days
        else:
            interval = _FREQUENCY_INTERVAL_DAYS[frequency]

        # Find the most recent snapshot for this metric on this goal.
        matching = [
            s for s in metric_snapshots
            if s.goal_title == goal.title
            and s.metric_name == metric
        ]
        if not matching:
            # No snapshot at all → due.
            overdue_metrics.append(metric)
            continue

        latest = max(matching, key=lambda s: s.timestamp)
        latest_date = latest.timestamp.date()
        due_date = today - timedelta(days=interval - MEASUREMENT_DUE_GRACE_DAYS)

        if latest_date < due_date:
            overdue_metrics.append(metric)

    if not overdue_metrics:
        return None, 0

    return GoalSignal(
        signal="measurement_due",
        score=45,
        timestamp=datetime.now().astimezone(),
        reason=(
            f"Measurement overdue for: {', '.join(overdue_metrics)}"
        ),
    ), len(overdue_metrics)


# ─── no_recent_activity signal (§6.2.2) ─────────────────────────────────────

def _compute_no_recent_activity_signal(
    goal: Goal,
    today: date,
    metric_snapshots: list[MetricSnapshot],
    completed_task_dates: dict[str, date] | None,
    open_task_titles: set[str],
) -> GoalSignal | None:
    """Compute the ``no_recent_activity`` signal (§6.2.2).

    Fires when ALL of:
    - Goal status is active.
    - No metric snapshot within the inactivity window.
    - No related task completed within the inactivity window.
    - No upcoming milestone deadline.
    - No upcoming goal deadline (more than the inactivity window in the future).

    Per §6.1, a goal with at least one open related task is NOT stalled and
    this signal does NOT fire.
    """
    if goal.status != "active":
        return None

    # A goal with no tracking configuration cannot have "recent activity".
    has_metric = bool(goal.metric_name)
    has_tasks = len(goal.related_tasks) > 0
    has_milestones = len(goal.milestones or []) > 0
    has_deadline = _parse_deadline(goal.deadline) is not None
    if not (has_metric or has_tasks or has_milestones or has_deadline):
        return None

    # §6.1: a goal with at least one open related task is not stalled.
    has_open_related = any(rt in open_task_titles for rt in goal.related_tasks)
    if has_open_related:
        return None

    inactivity_window = goal.inactivity_window_days or DEFAULT_INACTIVITY_WINDOW_DAYS
    window_start = today - timedelta(days=inactivity_window)

    # Check for recent metric snapshot.
    recent_snapshot_exists = any(
        s.goal_title == goal.title
        and s.timestamp.date() >= window_start
        for s in metric_snapshots
    )
    if recent_snapshot_exists:
        return None

    # Check for recent task completion.
    has_recent_completion = False
    if completed_task_dates:
        for rt in goal.related_tasks:
            completion_date = completed_task_dates.get(rt)
            if completion_date and completion_date >= window_start:
                has_recent_completion = True
                break
    if has_recent_completion:
        return None

    # Check for upcoming goal deadline. Per §6.2.2: a deadline within the
    # inactivity window IS upcoming (the goal is actively approaching it).
    # Only deadlines MORE than the window in the future count as "not upcoming"
    # for the purpose of this signal — if the deadline is soon, the goal is
    # actively being worked toward and should not fire no_recent_activity.
    goal_deadline = _parse_deadline(goal.deadline)
    if goal_deadline is not None and today <= goal_deadline <= today + timedelta(days=inactivity_window):
        return None  # deadline is upcoming → not stalled

    # Check for upcoming milestone deadlines.
    milestones = _milestone_objs(goal)
    has_future_milestone = False
    for m in milestones:
        m_deadline = _parse_deadline(m.deadline) if m.deadline else None
        if m_deadline is not None and m_deadline > today and m.status not in ("completed", "skipped"):
            has_future_milestone = True
            break
        if m.status in ("open", "in_progress") and m_deadline is None:
            has_future_milestone = True
            break
    if has_future_milestone:
        return None

    return GoalSignal(
        signal="no_recent_activity",
        score=35,
        timestamp=datetime.now().astimezone(),
        reason=(
            f"No metric snapshot or task completion in the last "
            f"{inactivity_window} days"
        ),
    )


def _milestone_objs(goal: Goal):
    """Construct ordered Milestone objects from goal.milestones dicts.

    Reuses the same logic as attention.py.
    """
    from janus.models.milestone import Milestone

    mss = []
    for d in goal.milestones:
        filtered = {k: v for k, v in dict(d).items() if k != "related_tasks"}
        mss.append(Milestone(**filtered))
    mss.sort(key=lambda m: m.order)
    return mss


# ─── Health state resolution (§4.2) ─────────────────────────────────────────

def _resolve_health_state(
    signals: list[GoalSignal],
    goal: Goal,
    today: date,
    open_task_titles: set[str],
) -> str:
    """Determine the health state from the full set of signals (§4.2).

    Resolution order uses the highest-severity signal.  The ``goal_deadline_soon``
    and ``milestone_deadline_soon`` exception (§4.2 exception) applies: these
    soft signals do NOT downgrade to ``watch`` if the goal has open related
    tasks AND no ``progress_slow`` signal.
    """
    if not signals:
        return HEALTH_HEALTHY

    signal_names = {s.signal for s in signals}
    has_open_related = any(rt in open_task_titles for rt in goal.related_tasks)

    # Check for any higher-severity (critical/stalled) signals first.
    stalled_signals = {
        "goal_stalled", "milestone_slipped", "goal_overdue",
        "no_recent_activity", "goal_deadline_today",
    }
    if signal_names & stalled_signals:
        return HEALTH_STALLED

    # Check for watch-level signals (excluding soft signals).
    watch_signals = {
        "progress_slow", "measurement_due", "goal_inactive",
    }
    if signal_names & watch_signals:
        return HEALTH_WATCH

    # Only soft signals remain (deadline_soon / milestone_deadline_soon).
    if signal_names & _SOFT_SIGNALS:
        # Exception: if goal has open related tasks AND no progress_slow,
        # these soft signals do NOT downgrade to watch.
        if has_open_related and "progress_slow" not in signal_names:
            return HEALTH_HEALTHY
        return HEALTH_WATCH

    return HEALTH_HEALTHY


# ─── days_since_last_activity (§4.4 / §12.5) ────────────────────────────────

def _compute_days_since_last_activity(
    goal: Goal,
    today: date,
    metric_snapshots: list[MetricSnapshot],
    completed_task_dates: dict[str, date] | None,
) -> int | None:
    """Days since the last metric snapshot or task completion for this goal."""
    latest_date: date | None = None

    # Metric snapshots.
    for s in metric_snapshots:
        if s.goal_title == goal.title:
            snap_date = s.timestamp.date()
            if latest_date is None or snap_date > latest_date:
                latest_date = snap_date

    # Completed task dates.
    if completed_task_dates:
        for rt in goal.related_tasks:
            completion_date = completed_task_dates.get(rt)
            if completion_date is not None:
                if latest_date is None or completion_date > latest_date:
                    latest_date = completion_date

    if latest_date is None:
        return None

    return (today - latest_date).days


# ─── Main entry point (§11.1) ───────────────────────────────────────────────

def assess_goal_health(
    goal: Goal,
    today: date,
    open_task_titles: set[str],
    all_task_titles: set[str],
    metric_snapshots: list[MetricSnapshot] | None = None,
    completed_task_dates: dict[str, date] | None = None,
) -> GoalHealthAssessment:
    """Assess a single goal's health state (§11.1).

    Args:
        goal: The goal to assess.  Caller should filter for ``status == "active"``.
        today: Current date.
        open_task_titles: Set of currently-open task titles.
        all_task_titles: Set of all task titles (open + completed).
        metric_snapshots: Pre-loaded snapshots for this goal.  If None,
            loaded from ``metric_history``.
        completed_task_dates: Mapping of task title → completion date.
            If None, task-based progress delta is not computed.

    Returns a ``GoalHealthAssessment`` with the computed health state, all
    signals, and supporting data.  Inactive goals return health_state=None
    and completed goals return ``completed``.
    """
    evaluated_at = datetime.now().astimezone()

    # Completed goals — always completed, no signals evaluated (§4.1).
    if goal.status == "completed":
        return GoalHealthAssessment(
            goal_title=goal.title,
            health_state=HEALTH_COMPLETED,
            signals=[],
            dominant_signal=None,
            progress=compute_goal_progress(goal),
            progress_delta=None,
            days_since_last_activity=None,
            measurement_overdue_count=0,
            evaluated_at=evaluated_at,
        )

    # Inactive goals are excluded from health evaluation (§4.1).
    if goal.status == "inactive":
        return GoalHealthAssessment(
            goal_title=goal.title,
            health_state=None,
            signals=[],
            dominant_signal=None,
            progress=None,
            progress_delta=None,
            days_since_last_activity=None,
            measurement_overdue_count=0,
            evaluated_at=evaluated_at,
        )

    # Load metric snapshots if not provided.
    if metric_snapshots is None:
        metric_snapshots = load_snapshots()

    # ── 1. Existing signals from assess_goal_stall (§5.3) ──
    stall_signals = assess_goal_stall(goal, today, open_task_titles, all_task_titles)

    signals: list[GoalSignal] = []
    for stall_sig, category in stall_signals:
        sig = GoalSignal(
            signal=stall_sig.signal,
            score=stall_sig.score,
            reason=stall_sig.reason,
            timestamp=evaluated_at,
        )
        signals.append(sig)

    # Collect existing signal names for suppression logic.
    existing_signal_names = {s.signal for s in signals}

    # Determine the highest existing score for suppression checks.
    max_existing_score = max((s.score for s in signals), default=0)

    # ── 2. New signals (§5.4) ──
    # progress_slow — only when no higher-severity signal is present.
    progress_slow_sig = _compute_progress_slow_signal(
        goal, today, metric_snapshots
    )
    if progress_slow_sig is not None:
        if max_existing_score >= 45:
            # A higher-severity signal (deadline/stalled/milestone) is firing.
            progress_slow_sig = None
        else:
            signals.append(progress_slow_sig)

    # measurement_due.
    measurement_signal, overdue_count = _compute_measurement_due_signal(
        goal, today, metric_snapshots
    )
    if measurement_signal is not None and max_existing_score >= 55:
        # Suppressed by higher-severity signal.
        measurement_signal = None
        overdue_count = 0
    if measurement_signal is not None:
        signals.append(measurement_signal)

    # no_recent_activity — suppressed by deadline/milestone signals and by
    # signals indicating the goal is actively tracked (§4.3).
    # Per §6.2.2: suppressed by any deadline/milestone signal and by
    # goal_inactive (stronger signal wins).  Also suppressed when
    # measurement_due or progress_slow fire — those indicate the goal has
    # active measurement/tracking, so no_recent_activity is redundant.
    if max_existing_score < 50:
        nra_sig = _compute_no_recent_activity_signal(
            goal, today, metric_snapshots, completed_task_dates, open_task_titles
        )
        if nra_sig is not None:
            # Also suppress if goal_inactive, goal_stalled, measurement_due,
            # or progress_slow is present.
            suppress_signals = {
                "goal_inactive", "goal_stalled",
                "measurement_due", "progress_slow",
            }
            if not ({s.signal for s in signals} & suppress_signals):
                signals.append(nra_sig)

    # ── 3. Resolve health state ──
    health_state = _resolve_health_state(signals, goal, today, open_task_titles)

    # ── 4. Determine dominant signal (highest severity) ──
    dominant: GoalSignal | None = None
    if signals:
        dominant = max(signals, key=lambda s: _SIGNAL_SEVERITY.get(s.signal, 0))

    # ── 5. Compute supporting metrics ──
    current_progress = compute_goal_progress(goal)

    # progress_delta for metric-based goals (§7.4, §9).
    progress_delta = None
    if goal.metric_name and current_progress is not None:
        lookback_start = today - timedelta(days=PROGRESS_LOOKBACK_DAYS)
        lookback_start_dt = datetime.combine(
            lookback_start, datetime.min.time(), tzinfo=timezone.utc
        )
        past_snapshots = [
            s for s in metric_snapshots
            if s.goal_title == goal.title
            and s.timestamp <= lookback_start_dt
        ]
        if past_snapshots:
            past_snapshot = max(past_snapshots, key=lambda s: s.timestamp)
            past_goal = Goal(
                title=goal.title,
                description=goal.description,
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
                inactivity_window_days=goal.inactivity_window_days,
            )
            past_progress = compute_goal_progress(past_goal)
            if past_progress is not None:
                progress_delta = current_progress - past_progress

    days_since_activity = _compute_days_since_last_activity(
        goal, today, metric_snapshots, completed_task_dates
    )

    return GoalHealthAssessment(
        goal_title=goal.title,
        health_state=health_state,
        signals=signals,
        dominant_signal=dominant,
        progress=current_progress,
        progress_delta=progress_delta,
        days_since_last_activity=days_since_activity,
        measurement_overdue_count=overdue_count,
        evaluated_at=evaluated_at,
    )


# ─── Batch assessment helper ────────────────────────────────────────────────

def assess_all_goals_health(
    goals: list[Goal],
    today: date,
    open_task_titles: set[str],
    all_task_titles: set[str],
    metric_snapshots: list[MetricSnapshot] | None = None,
    completed_task_dates: dict[str, date] | None = None,
) -> list[GoalHealthAssessment]:
    """Assess health for all goals, returning only active ones in order.

    Inactive and completed goals are excluded from the list (their health
    is not meaningful for the ``goal health`` CLI command).  Completed goals
    return ``completed`` state; inactive goals are skipped entirely.
    """
    assessments: list[GoalHealthAssessment] = []
    for goal in goals:
        if goal.status == "inactive":
            continue
        assessment = assess_goal_health(
            goal, today, open_task_titles, all_task_titles,
            metric_snapshots=metric_snapshots,
            completed_task_dates=completed_task_dates,
        )
        assessments.append(assessment)
    return assessments


#: Severity ranking for CLI sorting (stalled first, then watch, then healthy).
_HEALTH_SEVERITY = {
    HEALTH_STALLED: 0,
    HEALTH_WATCH: 1,
    HEALTH_HEALTHY: 2,
}
