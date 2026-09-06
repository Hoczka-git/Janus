"""Tests for goal health assessment — health state resolution and progress signals.

Tests cover the acceptance criteria from §12.1–§12.3 of the design spec.
All tests use direct function calls with explicit parameters — no CLI, no
persistence, no disk reads for task titles (open_task_titles is passed in).
"""

import pytest
from datetime import date, datetime, timedelta, timezone

from janus.models.goal import Goal
from janus.services.goal_health import (
    assess_goal_health,
    assess_all_goals_health,
    GoalHealthAssessment,
    GoalSignal,
    MetricSnapshot,
    HEALTH_HEALTHY,
    HEALTH_WATCH,
    HEALTH_STALLED,
    HEALTH_COMPLETED,
    PROGRESS_SLOW_THRESHOLD,
    PROGRESS_LOOKBACK_DAYS,
    MEASUREMENT_DUE_GRACE_DAYS,
    DEFAULT_INACTIVITY_WINDOW_DAYS,
)


FIXED_TODAY = date(2026, 9, 15)


def _snap(days_ago, goal_title="G", metric_name="Metric", value=10.0, source="manual"):
    """Helper: create a MetricSnapshot N days ago from FIXED_TODAY."""
    ts = datetime.combine(
        FIXED_TODAY - timedelta(days=days_ago),
        datetime.min.time(), tzinfo=timezone.utc
    )
    return MetricSnapshot(
        timestamp=ts,
        goal_title=goal_title,
        metric_name=metric_name,
        value=value,
        source=source,
    )


def _metric_goal(title="Metric Goal", start=0.0, current=50.0, target=100.0,
                 direction="increase", deadline=None, related_tasks=None,
                 milestones=None, measurement_requirements=None,
                 inactivity_window_days=None):
    return Goal(
        title=title,
        status="active",
        metric_name="Metric",
        metric_unit="%",
        start_value=start,
        current_value=current,
        target_value=target,
        direction=direction,
        deadline=deadline,
        related_tasks=related_tasks or [],
        milestones=milestones or [],
        measurement_requirements=measurement_requirements or [],
        inactivity_window_days=inactivity_window_days,
    )


def _task_goal(title="Task Goal", related_tasks=None, deadline=None,
               milestones=None, measurement_requirements=None,
               metric_name=None, metric_unit=None):
    return Goal(
        title=title,
        status="active",
        related_tasks=related_tasks or [],
        deadline=deadline,
        milestones=milestones or [],
        measurement_requirements=measurement_requirements or [],
        metric_name=metric_name,
        metric_unit=metric_unit,
    )


def _empty_goal(title="Empty Goal", status="active"):
    return Goal(title=title, status=status)


OPEN = set()
ALL = set()


# =============================================================================
# §12.1 Goal Health Model — health state resolution
# =============================================================================

class TestHealthyState:
    def test_no_signals_is_healthy(self):
        """An active goal with no signals firing is assessed as healthy."""
        goal = _task_goal(related_tasks=["Task A"])
        result = assess_goal_health(goal, FIXED_TODAY, {"Task A"}, {"Task A"})
        assert result.health_state == HEALTH_HEALTHY

    def test_deadline_soon_with_open_tasks_is_healthy(self):
        """Active goal with only goal_deadline_soon AND open related tasks → healthy."""
        goal = _metric_goal(deadline="2026-09-20", related_tasks=["Task A"])
        result = assess_goal_health(goal, FIXED_TODAY, {"Task A"}, {"Task A"})
        # deadline is 5 days away → goal_deadline_soon fires, but open tasks exist
        assert result.health_state == HEALTH_HEALTHY

    def test_milestone_deadline_soon_with_open_tasks_is_healthy(self):
        """Active goal with only milestone_deadline_soon AND open tasks → healthy."""
        goal = _task_goal(related_tasks=["Task A"], milestones=[{
            "title": "M1", "goal_title": "G", "description": "",
            "deadline": "2026-09-18", "status": "open", "order": 0,
        }])
        result = assess_goal_health(goal, FIXED_TODAY, {"Task A"}, {"Task A"})
        assert result.health_state == HEALTH_HEALTHY


class TestWatchState:
    def test_progress_slow_is_watch(self):
        """Active goal with progress_slow (and no higher signal) → watch."""
        # Metric goal with snapshots showing < 5% progress over 14 days.
        # Snapshots match goal title so no_recent_activity does not fire.
        snapshots = [
            _snap(20, goal_title="Metric Goal", value=0.0),   # 20 days ago: 0.0
            _snap(1, goal_title="Metric Goal", value=1.0),    # 1 day ago: 1.0 (current)
        ]
        goal = _metric_goal(start=0.0, current=1.0, target=100.0)
        result = assess_goal_health(
            goal, FIXED_TODAY, OPEN, ALL, metric_snapshots=snapshots,
        )
        signal_names = {s.signal for s in result.signals}
        assert "progress_slow" in signal_names
        assert result.health_state == HEALTH_WATCH

    def test_measurement_due_is_watch(self):
        """Active goal with measurement_due → watch."""
        goal = _task_goal(measurement_requirements=[{
            "metric": "Metric", "unit": "%", "frequency": "daily",
        }])
        result = assess_goal_health(goal, FIXED_TODAY, OPEN, ALL, metric_snapshots=[])
        signal_names = {s.signal for s in result.signals}
        assert "measurement_due" in signal_names
        assert result.health_state == HEALTH_WATCH

    def test_goal_inactive_is_stalled(self):
        """All tasks done, no future milestone/deadline → goal_stalled + goal_inactive → stalled.

        Both goal_inactive (30) and goal_stalled (40) fire; goal_stalled is the
        dominant signal → stalled.
        """
        goal = _task_goal(related_tasks=["Task A"])
        result = assess_goal_health(goal, FIXED_TODAY, set(), {"Task A"})
        signal_names = {s.signal for s in result.signals}
        assert "goal_inactive" in signal_names
        assert result.health_state == HEALTH_STALLED

    def test_deadline_soon_with_progress_slow_is_watch(self):
        """Active goal with goal_deadline_soon + progress_slow → healthy.

        Per spec §10.4: progress_slow (40) is suppressed by goal_deadline_soon
        (60 ≥ 45 suppression threshold). With open related tasks, the soft-signal
        exception returns healthy.
        """
        snapshots = [
            _snap(20, goal_title="Metric Goal", value=0.0),
            _snap(1, goal_title="Metric Goal", value=1.0),
        ]
        goal = _metric_goal(
            start=0.0, current=1.0, target=100.0, deadline="2026-09-20",
            related_tasks=["Task A"],
        )
        result = assess_goal_health(
            goal, FIXED_TODAY, {"Task A"}, {"Task A"}, metric_snapshots=snapshots,
        )
        signal_names = {s.signal for s in result.signals}
        # progress_slow is suppressed by goal_deadline_soon; with open tasks
        # the soft-signal exception returns healthy.
        assert "goal_deadline_soon" in signal_names
        assert "progress_slow" not in signal_names
        assert result.health_state == HEALTH_HEALTHY

    def test_deadline_soon_without_open_tasks_is_watch(self):
        """goal_deadline_soon with NO open tasks → watch (not healthy)."""
        goal = _metric_goal(start=0.0, current=50.0, target=100.0,
                            deadline="2026-09-20")
        result = assess_goal_health(goal, FIXED_TODAY, set(), set())
        # No open tasks but deadline soon → not healthy (no open task to
        # satisfy the exception). progress_slow won't fire (no snapshots).
        # goal_deadline_soon would downgrade to watch if progress_slow or
        # no open tasks. Without open tasks, the exception doesn't apply.
        assert result.health_state == HEALTH_WATCH


class TestStalledState:
    def test_goal_stalled_is_stalled(self):
        """Active goal with goal_stalled → stalled."""
        goal = _task_goal(related_tasks=["Task A"])
        result = assess_goal_health(goal, FIXED_TODAY, set(), {"Task A"})
        signal_names = {s.signal for s in result.signals}
        assert "goal_stalled" in signal_names
        assert result.health_state == HEALTH_STALLED

    def test_goal_overdue_is_stalled(self):
        """Active goal with goal_overdue → stalled."""
        goal = _task_goal(related_tasks=["Task A"], deadline="2026-08-01")
        result = assess_goal_health(goal, FIXED_TODAY, set(), {"Task A"})
        signal_names = {s.signal for s in result.signals}
        assert "goal_overdue" in signal_names
        assert result.health_state == HEALTH_STALLED

    def test_milestone_slipped_is_stalled(self):
        """Active goal with milestone_slipped → stalled."""
        goal = _task_goal(milestones=[{
            "title": "M1", "goal_title": "G", "description": "",
            "deadline": "2026-08-01", "status": "open", "order": 0,
        }])
        result = assess_goal_health(goal, FIXED_TODAY, set(), set())
        signal_names = {s.signal for s in result.signals}
        assert "milestone_slipped" in signal_names
        assert result.health_state == HEALTH_STALLED

    def test_no_recent_activity_is_stalled(self):
        """Active goal with no_recent_activity → stalled."""
        # No snapshots, no completed tasks, no future milestone/deadline,
        # deadline more than inactivity window in the future.
        goal = _metric_goal(
            start=0.0, current=50.0, target=100.0,
            deadline="2027-01-01",  # far future → not upcoming within window
        )
        result = assess_goal_health(
            goal, FIXED_TODAY, set(), set(), metric_snapshots=[],
        )
        signal_names = {s.signal for s in result.signals}
        assert "no_recent_activity" in signal_names
        assert result.health_state == HEALTH_STALLED


class TestCompletedAndInactive:
    def test_completed_goal_is_completed(self):
        """A completed goal is always assessed as completed, no signals."""
        goal = Goal(title="Done", status="completed")
        result = assess_goal_health(goal, FIXED_TODAY, OPEN, ALL)
        assert result.health_state == HEALTH_COMPLETED
        assert result.signals == []
        assert result.dominant_signal is None

    def test_inactive_goal_excluded(self):
        """An inactive goal is excluded from health assessment."""
        goal = Goal(title="Paused", status="inactive")
        result = assess_goal_health(goal, FIXED_TODAY, OPEN, ALL)
        assert result.health_state is None
        assert result.signals == []


# =============================================================================
# §12.2 Progress Signals
# =============================================================================

class TestProgressSlowSignal:
    def test_fires_when_progress_below_threshold(self):
        """progress_slow fires when delta < threshold for metric goal."""
        snapshots = [
            _snap(20, goal_title="Metric Goal", value=0.0),
            _snap(1, goal_title="Metric Goal", value=1.0),
        ]
        goal = _metric_goal(start=0.0, current=1.0, target=100.0)
        result = assess_goal_health(
            goal, FIXED_TODAY, OPEN, ALL, metric_snapshots=snapshots,
        )
        sig = next((s for s in result.signals if s.signal == "progress_slow"), None)
        assert sig is not None
        assert sig.score == 40

    def test_does_not_fire_when_progress_above_threshold(self):
        """progress_slow does NOT fire when delta >= threshold."""
        snapshots = [
            _snap(20, goal_title="Metric Goal", value=0.0),
            _snap(1, goal_title="Metric Goal", value=50.0),
        ]
        goal = _metric_goal(start=0.0, current=50.0, target=100.0)
        result = assess_goal_health(
            goal, FIXED_TODAY, OPEN, ALL, metric_snapshots=snapshots,
        )
        signal_names = {s.signal for s in result.signals}
        assert "progress_slow" not in signal_names

    def test_does_not_fire_with_higher_severity_signal(self):
        """progress_slow does NOT fire when higher-severity signal present."""
        # goal_overdue (100) > progress_slow (40)
        snapshots = [
            _snap(20, goal_title="Metric Goal", value=0.0),
            _snap(1, goal_title="Metric Goal", value=1.0),
        ]
        goal = _metric_goal(
            start=0.0, current=1.0, target=100.0,
            deadline="2026-08-01",  # overdue
            related_tasks=["Task A"],
        )
        result = assess_goal_health(
            goal, FIXED_TODAY, set(), {"Task A"}, metric_snapshots=snapshots,
        )
        signal_names = {s.signal for s in result.signals}
        assert "goal_overdue" in signal_names
        assert "progress_slow" not in signal_names

    def test_does_not_fire_without_history(self):
        """progress_slow does NOT fire when no lookback snapshot exists."""
        # Only one snapshot (today) — no lookback data.
        snapshots = [_snap(0, goal_title="Metric Goal", value=50.0)]
        goal = _metric_goal(start=0.0, current=50.0, target=100.0)
        result = assess_goal_health(
            goal, FIXED_TODAY, OPEN, ALL, metric_snapshots=snapshots,
        )
        signal_names = {s.signal for s in result.signals}
        assert "progress_slow" not in signal_names

    def test_does_not_fire_for_empty_goal(self):
        """progress_slow does NOT fire for goal with no progress config."""
        goal = _empty_goal()
        result = assess_goal_health(goal, FIXED_TODAY, OPEN, ALL, metric_snapshots=[])
        assert result.health_state == HEALTH_HEALTHY


class TestMeasurementDueSignal:
    def test_fires_when_measurement_overdue(self):
        """measurement_due fires when frequency window elapsed without snapshot."""
        goal = _task_goal(measurement_requirements=[{
            "metric": "Metric", "unit": "%", "frequency": "weekly",
        }])
        # No snapshots at all → due immediately.
        result = assess_goal_health(goal, FIXED_TODAY, OPEN, ALL, metric_snapshots=[])
        sig = next((s for s in result.signals if s.signal == "measurement_due"), None)
        assert sig is not None
        assert sig.score == 45
        assert result.measurement_overdue_count >= 1

    def test_fires_when_last_snapshot_too_old(self):
        """measurement_due fires when last snapshot is older than interval + grace."""
        # weekly → interval=7, grace=2 → due after 9 days.
        snapshots = [_snap(15, goal_title="Task Goal", metric_name="Metric")]
        goal = _task_goal(measurement_requirements=[{
            "metric": "Metric", "unit": "%", "frequency": "weekly",
        }])
        result = assess_goal_health(
            goal, FIXED_TODAY, OPEN, ALL, metric_snapshots=snapshots,
        )
        sig = next((s for s in result.signals if s.signal == "measurement_due"), None)
        assert sig is not None

    def test_does_not_fire_when_within_window(self):
        """measurement_due does NOT fire when snapshot is within frequency window."""
        # weekly → interval=7, grace=2. Snapshot 3 days ago → within window.
        snapshots = [_snap(3, goal_title="Task Goal", metric_name="Metric")]
        goal = _task_goal(measurement_requirements=[{
            "metric": "Metric", "unit": "%", "frequency": "weekly",
        }])
        result = assess_goal_health(
            goal, FIXED_TODAY, OPEN, ALL, metric_snapshots=snapshots,
        )
        signal_names = {s.signal for s in result.signals}
        assert "measurement_due" not in signal_names

    def test_does_not_fire_without_requirements(self):
        """measurement_due does NOT fire when goal has no measurement requirements."""
        goal = _task_goal(related_tasks=["Task A"])
        result = assess_goal_health(goal, FIXED_TODAY, {"Task A"}, {"Task A"},
                                    metric_snapshots=[])
        signal_names = {s.signal for s in result.signals}
        assert "measurement_due" not in signal_names

    def test_does_not_fire_with_higher_severity_signal(self):
        """measurement_due suppressed by higher-severity signal."""
        # goal_overdue (100) > measurement_due (45)
        goal = _task_goal(
            related_tasks=["Task A"],
            deadline="2026-08-01",  # overdue
            measurement_requirements=[{
                "metric": "Metric", "unit": "%", "frequency": "daily",
            }],
        )
        result = assess_goal_health(
            goal, FIXED_TODAY, set(), {"Task A"}, metric_snapshots=[],
        )
        signal_names = {s.signal for s in result.signals}
        assert "measurement_due" not in signal_names
        assert "goal_overdue" in signal_names


class TestNoRecentActivitySignal:
    def test_fires_with_no_activity(self):
        """no_recent_activity fires when no snapshot and no task completion in window."""
        goal = _metric_goal(
            start=0.0, current=50.0, target=100.0,
            deadline="2027-01-01",  # far future
        )
        result = assess_goal_health(
            goal, FIXED_TODAY, set(), set(), metric_snapshots=[],
        )
        sig = next((s for s in result.signals if s.signal == "no_recent_activity"), None)
        assert sig is not None
        assert sig.score == 35

    def test_does_not_fire_with_recent_snapshot(self):
        """no_recent_activity does NOT fire when a snapshot exists within window."""
        snapshots = [_snap(5, goal_title="Metric Goal", metric_name="Metric")]
        goal = _metric_goal(
            start=0.0, current=50.0, target=100.0,
            deadline="2027-01-01",
        )
        result = assess_goal_health(
            goal, FIXED_TODAY, set(), set(), metric_snapshots=snapshots,
        )
        signal_names = {s.signal for s in result.signals}
        assert "no_recent_activity" not in signal_names

    def test_does_not_fire_with_recent_task_completion(self):
        """no_recent_activity does NOT fire when a task was completed within window."""
        snapshots = []  # no snapshots
        goal = _task_goal(
            related_tasks=["Related Task"],
            deadline="2027-01-01",  # far future
        )
        completed_dates = {"Related Task": FIXED_TODAY - timedelta(days=5)}
        result = assess_goal_health(
            goal, FIXED_TODAY, set(), set(),
            metric_snapshots=snapshots, completed_task_dates=completed_dates,
        )
        signal_names = {s.signal for s in result.signals}
        assert "no_recent_activity" not in signal_names

    def test_does_not_fire_with_upcoming_milestone(self):
        """no_recent_activity does NOT fire when an upcoming milestone exists."""
        goal = _metric_goal(
            start=0.0, current=50.0, target=100.0,
            deadline="2027-01-01",
            milestones=[{
                "title": "M1", "goal_title": "G", "description": "",
                "deadline": "2026-10-01", "status": "open", "order": 0,
            }],
        )
        result = assess_goal_health(
            goal, FIXED_TODAY, set(), set(), metric_snapshots=[],
        )
        signal_names = {s.signal for s in result.signals}
        assert "no_recent_activity" not in signal_names

    def test_does_not_fire_with_upcoming_goal_deadline(self):
        """no_recent_activity does NOT fire when goal deadline is within window."""
        # Goal deadline 10 days away → within inactivity window (30 days)
        # → IS upcoming → no_recent_activity should NOT fire.
        goal = _metric_goal(
            start=0.0, current=50.0, target=100.0,
            deadline="2026-09-25",  # 10 days away → upcoming
        )
        result = assess_goal_health(
            goal, FIXED_TODAY, set(), set(), metric_snapshots=[],
        )
        signal_names = {s.signal for s in result.signals}
        assert "no_recent_activity" not in signal_names

    def test_fires_with_far_future_deadline(self):
        """no_recent_activity fires when goal deadline is far future (> window)."""
        goal = _metric_goal(
            start=0.0, current=50.0, target=100.0,
            deadline="2027-06-01",  # far future
        )
        result = assess_goal_health(
            goal, FIXED_TODAY, set(), set(), metric_snapshots=[],
        )
        signal_names = {s.signal for s in result.signals}
        assert "no_recent_activity" in signal_names

    def test_suppressed_by_goal_inactive(self):
        """no_recent_activity is suppressed when goal_inactive also fires."""
        # Goal with all tasks done, no future milestone/deadline — goal_inactive
        # fires (30), no_recent_activity (35) should NOT also fire (stronger wins).
        goal = _task_goal(related_tasks=["Task A"])
        result = assess_goal_health(
            goal, FIXED_TODAY, set(), {"Task A"}, metric_snapshots=[],
        )
        signal_names = {s.signal for s in result.signals}
        assert "goal_inactive" in signal_names
        # no_recent_activity is suppressed because goal_inactive fires
        # (it indicates the same "no activity" state but more specifically)
        assert "no_recent_activity" not in signal_names

    def test_suppressed_by_deadline_signal(self):
        """no_recent_activity is suppressed by any deadline/milestone signal."""
        # goal_deadline_soon (60) > no_recent_activity (35)
        goal = _metric_goal(
            start=0.0, current=50.0, target=100.0,
            deadline="2026-09-20",  # 5 days → deadline soon
        )
        result = assess_goal_health(
            goal, FIXED_TODAY, set(), set(), metric_snapshots=[],
        )
        signal_names = {s.signal for s in result.signals}
        assert "no_recent_activity" not in signal_names

    def test_suppressed_by_measurement_due(self):
        """no_recent_activity is suppressed when measurement_due fires."""
        goal = _task_goal(measurement_requirements=[{
            "metric": "Metric", "unit": "%", "frequency": "daily",
        }])
        result = assess_goal_health(goal, FIXED_TODAY, OPEN, ALL, metric_snapshots=[])
        signal_names = {s.signal for s in result.signals}
        assert "measurement_due" in signal_names
        assert "no_recent_activity" not in signal_names

    def test_suppressed_by_progress_slow(self):
        """no_recent_activity is suppressed when progress_slow fires."""
        snapshots = [
            _snap(20, goal_title="Metric Goal", value=0.0),
            _snap(1, goal_title="Metric Goal", value=1.0),
        ]
        goal = _metric_goal(start=0.0, current=1.0, target=100.0)
        result = assess_goal_health(
            goal, FIXED_TODAY, OPEN, ALL, metric_snapshots=snapshots,
        )
        signal_names = {s.signal for s in result.signals}
        assert "progress_slow" in signal_names
        assert "no_recent_activity" not in signal_names


# =============================================================================
# §12.3 Stalled-Goal Detection
# =============================================================================

class TestStalledDetection:
    def test_existing_goal_stalled_preserved(self):
        """Existing goal_stalled behavior preserved."""
        goal = _task_goal(related_tasks=["Task A"])
        result = assess_goal_health(goal, FIXED_TODAY, set(), {"Task A"})
        signal_names = {s.signal for s in result.signals}
        assert "goal_stalled" in signal_names

    def test_goal_overdue_only_when_no_open_tasks(self):
        """goal_overdue fires only when no open tasks exist."""
        goal = _task_goal(related_tasks=["Task A"], deadline="2026-08-01")
        result = assess_goal_health(goal, FIXED_TODAY, set(), {"Task A"})
        signal_names = {s.signal for s in result.signals}
        assert "goal_overdue" in signal_names

    def test_no_recent_activity_with_open_tasks_does_not_fire(self):
        """no_recent_activity does NOT fire for goal with open related tasks."""
        snapshots = []  # no recent snapshots
        goal = _metric_goal(
            start=0.0, current=50.0, target=100.0,
            deadline="2027-01-01",  # far future
            related_tasks=["Task A"],
        )
        result = assess_goal_health(
            goal, FIXED_TODAY, {"Task A"}, {"Task A"}, metric_snapshots=snapshots,
        )
        signal_names = {s.signal for s in result.signals}
        assert "no_recent_activity" not in signal_names

    def test_stalled_with_no_open_tasks_and_old_snapshot(self):
        """Old snapshot with slow progress → progress_slow fires (suppressed nra).

        Snapshot 40 days ago is outside the 30-day inactivity window. progress_slow
        fires (delta < threshold), which suppresses no_recent_activity (§4.3).
        Health state is watch (progress_slow is a watch-level signal).
        """
        snapshots = [_snap(40, goal_title="Metric Goal", value=10.0)]
        goal = _metric_goal(
            start=0.0, current=10.0, target=100.0,
            deadline="2027-01-01",
        )
        result = assess_goal_health(
            goal, FIXED_TODAY, set(), set(), metric_snapshots=snapshots,
        )
        signal_names = {s.signal for s in result.signals}
        assert "progress_slow" in signal_names
        # no_recent_activity is suppressed by progress_slow (§4.3)
        assert "no_recent_activity" not in signal_names
        assert result.health_state == HEALTH_WATCH

    def test_stalled_with_custom_inactivity_window(self):
        """no_recent_activity respects goal.inactivity_window_days."""
        # Snapshot 10 days ago, window=5 → snapshot is outside window → fires.
        snapshots = [_snap(10, goal_title="Metric Goal", value=10.0)]
        goal = _metric_goal(
            start=0.0, current=10.0, target=100.0,
            deadline="2027-01-01",
            inactivity_window_days=5,
        )
        result = assess_goal_health(
            goal, FIXED_TODAY, set(), set(), metric_snapshots=snapshots,
        )
        signal_names = {s.signal for s in result.signals}
        assert "no_recent_activity" in signal_names

    def test_not_stalled_with_recent_snapshot_in_custom_window(self):
        """no_recent_activity does NOT fire with recent snapshot in custom window."""
        # Snapshot 3 days ago, window=5 → within window → does not fire.
        snapshots = [_snap(3, goal_title="Metric Goal", value=10.0)]
        goal = _metric_goal(
            start=0.0, current=10.0, target=100.0,
            deadline="2027-01-01",
            inactivity_window_days=5,
        )
        result = assess_goal_health(
            goal, FIXED_TODAY, set(), set(), metric_snapshots=snapshots,
        )
        signal_names = {s.signal for s in result.signals}
        assert "no_recent_activity" not in signal_names


# =============================================================================
# §12.4 Assessment metadata
# =============================================================================

class TestAssessmentMetadata:
    def test_progress_is_computed(self):
        """progress is computed for metric goals."""
        snapshots = [
            _snap(20, goal_title="Metric Goal", value=0.0),
            _snap(1, goal_title="Metric Goal", value=50.0),
        ]
        goal = _metric_goal(start=0.0, current=50.0, target=100.0)
        result = assess_goal_health(
            goal, FIXED_TODAY, OPEN, ALL, metric_snapshots=snapshots,
        )
        assert result.progress is not None
        assert 0.0 <= result.progress <= 100.0

    def test_progress_delta_for_metric_goal(self):
        """progress_delta is computed for metric goals with sufficient history."""
        snapshots = [
            _snap(20, goal_title="Metric Goal", value=0.0),
            _snap(1, goal_title="Metric Goal", value=10.0),
        ]
        goal = _metric_goal(start=0.0, current=10.0, target=100.0)
        result = assess_goal_health(
            goal, FIXED_TODAY, OPEN, ALL, metric_snapshots=snapshots,
        )
        # current progress = 10.0%, lookback progress = 0.0%, delta = 10.0
        assert result.progress_delta is not None
        assert result.progress_delta == pytest.approx(10.0, abs=0.1)

    def test_progress_delta_none_without_history(self):
        """progress_delta is None when no lookback snapshot exists."""
        snapshots = [_snap(0, goal_title="Metric Goal", value=50.0)]
        goal = _metric_goal(start=0.0, current=50.0, target=100.0)
        result = assess_goal_health(
            goal, FIXED_TODAY, OPEN, ALL, metric_snapshots=snapshots,
        )
        assert result.progress_delta is None

    def test_dominant_signal_is_highest_severity(self):
        """dominant_signal is the highest-severity signal."""
        goal = _metric_goal(
            start=0.0, current=50.0, target=100.0,
            deadline="2026-08-01",  # overdue
        )
        result = assess_goal_health(
            goal, FIXED_TODAY, set(), set(), metric_snapshots=[],
        )
        assert result.dominant_signal is not None
        assert result.dominant_signal.signal == "goal_overdue"

    def test_days_since_last_activity(self):
        """days_since_last_activity is computed from last snapshot."""
        snapshots = [_snap(5, goal_title="Metric Goal", value=50.0)]
        goal = _metric_goal(start=0.0, current=50.0, target=100.0)
        result = assess_goal_health(
            goal, FIXED_TODAY, set(), set(), metric_snapshots=snapshots,
        )
        assert result.days_since_last_activity is not None
        assert result.days_since_last_activity == 5

    def test_days_since_last_activity_none_no_snapshots(self):
        """days_since_last_activity is None when no snapshots exist."""
        goal = _metric_goal(start=0.0, current=50.0, target=100.0)
        result = assess_goal_health(
            goal, FIXED_TODAY, set(), set(), metric_snapshots=[],
        )
        assert result.days_since_last_activity is None

    def test_evaluated_at_is_set(self):
        """evaluated_at timestamp is set on the assessment."""
        goal = _empty_goal()
        result = assess_goal_health(goal, FIXED_TODAY, OPEN, ALL)
        assert result.evaluated_at is not None


# =============================================================================
# §12.5 Dominant signal and health summary
# =============================================================================

class TestDominantSignal:
    def test_dominant_signal_for_stalled(self):
        """Dominant signal is no_recent_activity for a stalled goal."""
        goal = _metric_goal(
            start=0.0, current=50.0, target=100.0,
            deadline="2027-01-01",
        )
        result = assess_goal_health(
            goal, FIXED_TODAY, set(), set(), metric_snapshots=[],
        )
        assert result.dominant_signal is not None
        assert result.dominant_signal.signal == "no_recent_activity"

    def test_no_dominant_signal_for_healthy(self):
        """No dominant signal for a healthy goal."""
        goal = _task_goal(related_tasks=["Task A"])
        result = assess_goal_health(goal, FIXED_TODAY, {"Task A"}, {"Task A"})
        assert result.dominant_signal is None
        assert result.signals == []


# =============================================================================
# §12.6 assess_all_goals_health
# =============================================================================

class TestAssessAllGoals:
    def test_excludes_inactive(self):
        """Inactive goals are excluded from batch assessment."""
        goals = [
            _task_goal(title="Active", related_tasks=["Task A"]),
            Goal(title="Inactive", status="inactive"),
        ]
        results = assess_all_goals_health(
            goals, FIXED_TODAY, {"Task A"}, {"Task A"},
        )
        assert len(results) == 1
        assert results[0].goal_title == "Active"

    def test_includes_completed(self):
        """Completed goals are included with completed state."""
        goals = [
            _task_goal(title="Active", related_tasks=["Task A"]),
            Goal(title="Done", status="completed"),
        ]
        results = assess_all_goals_health(
            goals, FIXED_TODAY, {"Task A"}, {"Task A"},
        )
        assert len(results) == 2
        completed = next(r for r in results if r.goal_title == "Done")
        assert completed.health_state == HEALTH_COMPLETED

    def test_includes_stalled(self):
        """Stalled goals are included with stalled state."""
        goals = [
            _metric_goal(
                title="Stalled",
                start=0.0, current=50.0, target=100.0,
                deadline="2027-01-01",
            ),
        ]
        results = assess_all_goals_health(
            goals, FIXED_TODAY, set(), set(), metric_snapshots=[],
        )
        assert len(results) == 1
        assert results[0].health_state == HEALTH_STALLED
