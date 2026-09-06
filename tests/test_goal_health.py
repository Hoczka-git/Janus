"""Tests for goal health assessment and stalled-goal detection.

Implements the acceptance criteria from design §12:
- §12.1 Goal Health Model (health state resolution)
- §12.2 Progress Signals (progress_slow, measurement_due, no_recent_activity)
- §12.3 Stalled-Goal Detection (existing behavior preserved, no_recent_activity)
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from janus.models.goal import Goal
from janus.services.goal_health import (
    GoalHealthAssessment,
    GoalSignal,
    assess_goal_health,
    PROGRESS_SLOW_THRESHOLD,
    PROGRESS_LOOKBACK_DAYS,
    MEASUREMENT_DUE_GRACE_DAYS,
    INACTIVITY_WINDOW_DAYS,
)
from janus.integrations.metric_history import MetricSnapshot

FIXED_TODAY = date(2026, 9, 6)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_goal(
    title="Test goal",
    status="active",
    deadline=None,
    related_tasks=None,
    milestones=None,
    metric_name=None,
    metric_unit=None,
    start_value=None,
    current_value=None,
    target_value=None,
    direction=None,
    measurement_requirements=None,
    inactivity_window_days=None,
):
    return Goal(
        title=title,
        status=status,
        deadline=deadline,
        related_tasks=related_tasks or [],
        milestones=milestones or [],
        metric_name=metric_name,
        metric_unit=metric_unit,
        start_value=start_value,
        current_value=current_value,
        target_value=target_value,
        direction=direction,
        measurement_requirements=measurement_requirements or [],
        inactivity_window_days=inactivity_window_days,
    )


def _ts(days_ago: int) -> datetime:
    """Timestamp that many days before 'now' (timezone-aware)."""
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def _snap(goal_title, metric_name, value, days_ago, source="manual"):
    return MetricSnapshot(
        timestamp=_ts(days_ago),
        goal_title=goal_title,
        metric_name=metric_name,
        value=value,
        source=source,
    )


def _make_metric_goal(**kw):
    """Create a goal with a fully-configured metric."""
    defaults = dict(
        title="Body fat",
        metric_name="Body fat %",
        metric_unit="%",
        start_value=23.0,
        current_value=20.0,
        target_value=15.0,
        direction="decrease",
    )
    defaults.update(kw)
    return _make_goal(**defaults)


# ===========================================================================
# 12.1 Goal Health Model — health state resolution
# ===========================================================================

class TestHealthStateResolution:
    def test_active_metric_goal_no_activity_is_stalled(self):
        """An active metric goal with no snapshots and no tasks → no_recent_activity → stalled.

        A goal with a metric but no recent measurements is not 'healthy' — it has
        no_recent_activity (score 35) which maps to 'stalled'.
        """
        goal = _make_metric_goal()
        assessment = assess_goal_health(
            goal, FIXED_TODAY, open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert assessment.health_state == "stalled"
        assert any(s.signal == "no_recent_activity" for s in assessment.signals)

    def test_completed_goal_is_completed(self):
        """A completed goal is always assessed as completed (no signals)."""
        goal = _make_metric_goal(status="completed")
        assessment = assess_goal_health(
            goal, FIXED_TODAY, open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert assessment.health_state == "completed"
        assert assessment.signals == []
        assert assessment.dominant_signal is None

    def test_inactive_goal_excluded_from_assessment(self):
        """An inactive goal is excluded from health assessment (returns None)."""
        goal = _make_metric_goal(status="inactive")
        assessment = assess_goal_health(
            goal, FIXED_TODAY, open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is None

    def test_deadline_soon_with_open_tasks_is_healthy(self):
        """Goal deadline within 7 days but tasks are open → healthy (not watch)."""
        goal = _make_goal(
            title="G", deadline="2026-09-10",  # within 7 days of FIXED_TODAY
            related_tasks=["Task A"],
        )
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles={"Task A"}, all_task_titles={"Task A"},
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert assessment.health_state == "healthy"
        # deadline_soon signal fires but health is healthy because open tasks exist
        assert any(s.signal == "goal_deadline_soon" for s in assessment.signals)

    def test_deadline_soon_with_progress_slow_is_watch(self):
        """Goal deadline within 7 days AND progress_slow → watch."""
        goal = _make_metric_goal(deadline="2026-09-10")
        # Snapshot from 15 days ago at same value → delta = 0 < threshold → progress_slow
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 15)]
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert assessment is not None
        # deadline_soon (60) + progress_slow (40) → deadline_soon dominates
        # → healthy (deadline_soon exception: progress_slow IS present → watch)
        assert assessment.health_state == "watch"
        assert any(s.signal == "goal_deadline_soon" for s in assessment.signals)
        assert any(s.signal == "progress_slow" for s in assessment.signals)

    def test_measurement_due_is_watch(self):
        """An active goal with measurement_due is assessed as watch."""
        req = {"metric": "weight", "unit": "kg", "frequency": "daily"}
        goal = _make_goal(
            title="G", related_tasks=["Task A"],
            metric_name="weight", measurement_requirements=[req],
        )
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles={"Task A"}, all_task_titles={"Task A"},
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert assessment.health_state == "watch"
        assert any(s.signal == "measurement_due" for s in assessment.signals)

    def test_progress_slow_is_watch(self):
        """An active goal with progress_slow (and no higher signal) → watch."""
        goal = _make_metric_goal()
        # Metric goal with no tasks. Snapshot from 15 days ago at same value.
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 15)]
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert assessment is not None
        # progress_slow (40) fires, no_recent_activity suppressed (progress_slow
        # is a higher signal and goal_inactive is not in existing signals).
        # Actually: assess_goal_stall returns no signals (no tasks). progress_slow
        # fires. no_recent_activity: suppressed because... let me check.
        # existing_signal_names is empty (no stall signals). So no_recent_activity
        # IS evaluated. But recent_snapshot = True (snapshot 15 days ago is NOT
        # within 30-day window). So no_recent_activity does NOT fire.
        # Result: progress_slow (40) → watch.
        assert assessment.health_state == "watch"
        assert any(s.signal == "progress_slow" for s in assessment.signals)

    def test_goal_stalled_is_stalled(self):
        """An active goal with goal_stalled (and no higher signal) → stalled."""
        goal = _make_goal(title="G", related_tasks=["Task A"])
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles={"Task A"},
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert assessment.health_state == "stalled"
        assert any(s.signal == "goal_stalled" for s in assessment.signals)

    def test_goal_overdue_is_stalled(self):
        """Goal deadline passed with no open tasks → stalled."""
        goal = _make_goal(
            title="G", deadline="2026-08-30",
            related_tasks=["Task A"],
        )
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles={"Task A"},
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert assessment.health_state == "stalled"
        assert any(s.signal == "goal_overdue" for s in assessment.signals)

    def test_milestone_slipped_is_stalled(self):
        """Milestone deadline passed (status open) → stalled."""
        goal = _make_goal(
            title="G",
            milestones=[{
                "title": "M1", "goal_title": "G", "description": "",
                "deadline": "2026-08-30", "status": "open", "order": 0,
            }],
        )
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert assessment.health_state == "stalled"
        assert any(s.signal == "milestone_slipped" for s in assessment.signals)

    def test_no_recent_activity_is_stalled(self):
        """Metric goal with no recent activity, no upcoming deadlines → no_recent_activity → stalled."""
        goal = _make_metric_goal()  # no related_tasks, no deadline, no milestones
        # No snapshots within inactivity window, no completed task dates
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert assessment.health_state == "stalled"
        assert any(s.signal == "no_recent_activity" for s in assessment.signals)

    def test_goal_inactive_appears_alongside_goal_stalled(self):
        """When all tasks done with no future plans, goal_inactive appears alongside goal_stalled."""
        goal = _make_goal(title="G", related_tasks=["Task A"])
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles={"Task A"},
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        signal_names = [s.signal for s in assessment.signals]
        # Both fire; goal_stalled (40) is dominant → stalled
        assert "goal_inactive" in signal_names
        assert "goal_stalled" in signal_names
        assert assessment.health_state == "stalled"

    def test_deadline_soon_without_open_tasks_is_healthy(self):
        """Deadline within 7 days but NO open related tasks → still healthy (exception fires).

        Per design §4.2, goal_deadline_soon does NOT by itself downgrade to watch
        unless combined with progress_slow. Without progress_slow, it returns healthy.
        """
        goal = _make_goal(title="G", deadline="2026-09-10", related_tasks=["Task A"])
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles={"Task A"},
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        # goal_deadline_soon fires (score 60), no progress_slow → healthy (exception)
        assert assessment.health_state == "healthy"
        assert any(s.signal == "goal_deadline_soon" for s in assessment.signals)


# ===========================================================================
# 12.2 Progress Signals
# ===========================================================================

class TestProgressSlowSignal:
    def test_fires_below_threshold(self):
        """progress_slow fires when progress delta < threshold for metric goal."""
        goal = _make_metric_goal()
        # Snapshot from 15 days ago at same value → delta = 0 < 5%
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 15)]
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert assessment is not None
        assert any(s.signal == "progress_slow" for s in assessment.signals)

    def test_does_not_fire_above_threshold(self):
        """progress_slow does NOT fire when progress delta >= threshold."""
        goal = _make_metric_goal()
        # start=23.0, current=15.0 (100%), snapshot 15 days ago at 22.0
        # past progress = (23-22)/(23-15) = 12.5%, current = (23-15)/(23-15) = 100%
        # delta = 87.5% > 5% → no progress_slow
        snapshots = [_snap("Body fat", "Body fat %", 22.0, 15)]
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert assessment is not None
        assert not any(s.signal == "progress_slow" for s in assessment.signals)

    def test_does_not_fire_without_history(self):
        """progress_slow does NOT fire when lookback window hasn't elapsed."""
        goal = _make_metric_goal()
        # Snapshot only 3 days ago — not enough history for 14-day lookback
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 3)]
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert assessment is not None
        assert not any(s.signal == "progress_slow" for s in assessment.signals)

    def test_combined_with_progress_slow_returns_watch(self):
        """progress_slow combined with goal_deadline_soon → watch (not healthy)."""
        goal = _make_metric_goal(deadline="2026-09-10")
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 15)]
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert assessment is not None
        assert any(s.signal == "progress_slow" for s in assessment.signals)
        assert any(s.signal == "goal_deadline_soon" for s in assessment.signals)
        # deadline_soon exception: progress_slow IS present → watch
        assert assessment.health_state == "watch"


class TestMeasurementDueSignal:
    def test_fires_when_no_snapshot(self):
        """measurement_due fires when no snapshot exists for a daily requirement."""
        req = {"metric": "Body fat %", "unit": "%", "frequency": "daily"}
        goal = _make_metric_goal(measurement_requirements=[req])
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert any(s.signal == "measurement_due" for s in assessment.signals)

    def test_does_not_fire_when_within_window(self):
        """measurement_due does NOT fire when snapshots are within frequency window."""
        req = {"metric": "Body fat %", "unit": "%", "frequency": "daily"}
        goal = _make_metric_goal(measurement_requirements=[req])
        # Snapshot from 1 day ago — within daily window + 2 grace = 3 days
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 1)]
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert assessment is not None
        assert not any(s.signal == "measurement_due" for s in assessment.signals)

    def test_fires_after_frequency_window(self):
        """measurement_due fires when frequency window + grace has elapsed."""
        req = {"metric": "Body fat %", "unit": "%", "frequency": "daily"}
        goal = _make_metric_goal(measurement_requirements=[req])
        # Snapshot from 5 days ago — daily (1) + grace (2) = 3, so 5 > 3
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 5)]
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert assessment is not None
        assert any(s.signal == "measurement_due" for s in assessment.signals)

    def test_does_not_fire_without_requirements(self):
        """measurement_due does NOT fire when goal has no measurement requirements."""
        goal = _make_metric_goal()
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert not any(s.signal == "measurement_due" for s in assessment.signals)

    def test_custom_frequency(self):
        """measurement_due respects custom frequency interval."""
        req = {"metric": "x", "unit": "u", "frequency": "custom", "interval_days": 10}
        goal = _make_metric_goal(metric_name="x", measurement_requirements=[req])
        # Snapshot 5 days ago — within 10 + 2 = 12
        snapshots = [_snap("Body fat", "x", 1.0, 5)]
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert assessment is not None
        assert not any(s.signal == "measurement_due" for s in assessment.signals)

        # Snapshot 15 days ago — past 10 + 2 = 12
        snapshots2 = [_snap("Body fat", "x", 1.0, 15)]
        assessment2 = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots2, completed_task_dates=None,
        )
        assert assessment2 is not None
        assert any(s.signal == "measurement_due" for s in assessment2.signals)

    def test_weekly_frequency(self):
        """measurement_due respects weekly frequency (7 + 2 grace = 9 days)."""
        req = {"metric": "Body fat %", "unit": "%", "frequency": "weekly"}
        goal = _make_metric_goal(measurement_requirements=[req])
        # Snapshot 5 days ago — within 7 + 2 = 9 → not overdue
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 5)]
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert assessment is not None
        assert not any(s.signal == "measurement_due" for s in assessment.signals)

        # Snapshot 12 days ago — past 9 → overdue
        snapshots2 = [_snap("Body fat", "Body fat %", 20.0, 12)]
        assessment2 = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots2, completed_task_dates=None,
        )
        assert assessment2 is not None
        assert any(s.signal == "measurement_due" for s in assessment2.signals)


class TestNoRecentActivitySignal:
    """no_recent_activity fires for goals with no tasks (metric-only or deadline-only).

    When a goal has related tasks that exist in all_task_titles, goal_inactive
    fires (score 30) which suppresses no_recent_activity (per §6.2.2). So
    no_recent_activity only fires for goals WITHOUT existing related tasks.
    """

    def test_fires_no_activity_no_tasks_no_deadlines(self):
        """no_recent_activity fires for a goal with no tasks, no deadlines, no snapshots."""
        goal = _make_metric_goal()  # no related_tasks, no deadline, no milestones
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert any(s.signal == "no_recent_activity" for s in assessment.signals)

    def test_fires_no_activity_no_tasks_with_snapshots_old(self):
        """no_recent_activity fires when the only snapshot is older than the window."""
        goal = _make_metric_goal()
        # Snapshot 40 days ago — well past 30-day inactivity window
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 40)]
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert assessment is not None
        assert any(s.signal == "no_recent_activity" for s in assessment.signals)

    def test_does_not_fire_with_recent_metric_snapshot(self):
        """no_recent_activity does NOT fire when a metric snapshot exists within the window."""
        goal = _make_metric_goal()
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 5)]  # 5 days ago
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert assessment is not None
        assert not any(s.signal == "no_recent_activity" for s in assessment.signals)

    def test_does_not_fire_with_upcoming_milestone(self):
        """no_recent_activity does NOT fire when an upcoming milestone exists."""
        goal = _make_metric_goal(
            milestones=[{
                "title": "M1", "goal_title": "G", "description": "",
                "deadline": "2026-10-01", "status": "open", "order": 0,
            }],
        )
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert not any(s.signal == "no_recent_activity" for s in assessment.signals)

    def test_does_not_fire_with_upcoming_goal_deadline(self):
        """no_recent_activity does NOT fire when goal deadline is within the inactivity window."""
        goal = _make_metric_goal(deadline="2026-09-20")  # ~14 days from FIXED_TODAY
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert not any(s.signal == "no_recent_activity" for s in assessment.signals)

    def test_custom_inactivity_window(self):
        """Per-goal inactivity_window_days overrides the system default (30)."""
        goal = _make_metric_goal(inactivity_window_days=7)
        # Snapshot 10 days ago — within 30-day default but outside 7-day override
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 10)]
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert assessment is not None
        assert any(s.signal == "no_recent_activity" for s in assessment.signals)

    def test_suppressed_by_goal_inactive(self):
        """no_recent_activity is suppressed when goal_inactive would also fire.

        Per spec §6.2.2: when no_recent_activity fires, goal_inactive is
        suppressed (the stronger signal wins). The reverse is also true:
        goal_inactive suppresses no_recent_activity in assess_goal_stall.
        In assess_goal_health, no_recent_activity is only evaluated when
        goal_inactive is NOT already in the existing signal names.
        """
        goal = _make_goal(title="G", related_tasks=["Task A"])
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles={"Task A"},
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        signal_names = [s.signal for s in assessment.signals]
        # goal_inactive fires (task exists in file, all done, no deadline)
        # → no_recent_activity is suppressed
        assert "goal_inactive" in signal_names
        assert "no_recent_activity" not in signal_names


# ===========================================================================
# 12.3 Stalled-Goal Detection — existing behavior preserved
# ===========================================================================

class TestStalledDetectionPreservation:
    def test_goal_stalled_preserved(self):
        """Existing goal_stalled behavior is preserved (all tasks done, no higher signal)."""
        goal = _make_goal(title="G", related_tasks=["Task A"])
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles={"Task A"},
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert any(s.signal == "goal_stalled" for s in assessment.signals)
        assert assessment.dominant_signal.signal == "goal_stalled"

    def test_goal_overdue_only_when_no_open_tasks(self):
        """goal_overdue continues to fire only when no open tasks exist."""
        goal = _make_goal(
            title="G", deadline="2026-08-30",
            related_tasks=["Task A"],
        )
        # With open task → goal_overdue should NOT fire
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles={"Task A"}, all_task_titles={"Task A"},
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert not any(s.signal == "goal_overdue" for s in assessment.signals)

    def test_goal_deadline_precedence_over_milestone(self):
        """Goal deadline signals suppress milestone deadline signals (existing precedence)."""
        goal = _make_goal(
            title="G", deadline="2026-08-30",
            related_tasks=["Task A"],
            milestones=[{
                "title": "M1", "goal_title": "G", "description": "",
                "deadline": "2026-08-25", "status": "open", "order": 0,
            }],
        )
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles={"Task A"},
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert any(s.signal == "goal_overdue" for s in assessment.signals)
        assert not any(s.signal == "milestone_slipped" for s in assessment.signals)

    def test_milestone_deadline_soon_without_goal_deadline(self):
        """milestone_deadline_soon fires when no goal deadline, milestone soon."""
        goal = _make_goal(
            title="G",
            milestones=[{
                "title": "M1", "goal_title": "G", "description": "",
                "deadline": "2026-09-10", "status": "open", "order": 0,
            }],
        )
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert any(s.signal == "milestone_deadline_soon" for s in assessment.signals)


# ===========================================================================
# GoalHealthAssessment fields
# ===========================================================================

class TestGoalHealthAssessmentFields:
    def test_dominant_signal_is_highest_scoring(self):
        """dominant_signal is the highest-scoring signal (None if healthy)."""
        goal = _make_metric_goal(deadline="2026-08-30", related_tasks=["Task A"])
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles={"Task A"},
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert assessment.dominant_signal is not None
        assert assessment.dominant_signal.score == max(
            s.score for s in assessment.signals
        )

    def test_progress_populated(self):
        """progress field is populated from compute_goal_progress."""
        goal = _make_metric_goal()
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert assessment.progress is not None
        # start=23, current=20, target=15, decrease → (23-20)/(23-15) = 3/8 = 37.5%
        assert assessment.progress == pytest.approx(37.5)

    def test_days_since_last_activity_none_when_no_data(self):
        """days_since_last_activity is None when no activity data exists."""
        goal = _make_metric_goal()
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert assessment.days_since_last_activity is None

    def test_days_since_last_activity_from_snapshot(self):
        """days_since_last_activity reflects most recent snapshot."""
        goal = _make_metric_goal()
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 3)]
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert assessment is not None
        assert assessment.days_since_last_activity == 3

    def test_progress_delta_from_snapshots(self):
        """progress_delta is computed from metric snapshots."""
        goal = _make_metric_goal()
        # 15 days ago: current=22.0 → progress = (23-22)/(23-15) = 12.5%
        # now: current=20.0 → progress = (23-20)/(23-15) = 37.5%
        # delta = 37.5 - 12.5 = 25.0
        snapshots = [_snap("Body fat", "Body fat %", 22.0, 15)]
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert assessment is not None
        assert assessment.progress_delta == pytest.approx(25.0)

    def test_measurement_overdue_count(self):
        """measurement_overdue_count counts overdue requirements."""
        reqs = [
            {"metric": "Body fat %", "unit": "%", "frequency": "daily"},
            {"metric": "waist", "unit": "cm", "frequency": "weekly"},
        ]
        goal = _make_metric_goal(measurement_requirements=reqs)
        # No snapshots → both overdue
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=[], completed_task_dates=None,
        )
        assert assessment is not None
        assert assessment.measurement_overdue_count == 2

    def test_measurement_overdue_count_partial(self):
        """measurement_overdue_count is 0 when all within window."""
        reqs = [
            {"metric": "Body fat %", "unit": "%", "frequency": "daily"},
        ]
        goal = _make_metric_goal(measurement_requirements=[reqs[0]])
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 1)]
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert assessment is not None
        assert assessment.measurement_overdue_count == 0
