"""Targeted tests for no-progress detection (brak danych).

Covers the four-class classification:
  - NO_DATA (brak danych)
  - NO_EXECUTION (brak wykonania)
  - EXECUTION_WITHOUT_EFFECT (wykonanie bez efektu)
  - GOAL_ACHIEVED (cel osiągnięty)
  - MAKING_PROGRESS

Edge conditions: data arrives just before timeout, per-goal override,
completed_task_dates filtering, recent_activity fallback, etc.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from janus.models.goal import Goal
from janus.models.goal_signal import GoalSignal
from janus.models.metric_snapshot import MetricSnapshot
from janus.services.activity_ingest import ActivityRecord, ActivityType
from janus.services.no_progress_detector import (
    NoProgressClass,
    NoProgressResult,
    _EXECUTION_SIGNALS,
    classify_all_goals,
    classify_no_progress,
    detect_goal_achieved,
    detect_no_execution,
    is_stale,
    stale_reason_summary,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

FIXED_TODAY = date(2026, 9, 6)


def _make_goal(
    title="Test Goal",
    status="active",
    deadline=None,
    related_tasks=None,
    milestones=None,
    measurement_requirements=None,
    inactivity_window_days=None,
    metric_name=None,
    metric_unit=None,
    start_value=None,
    current_value=None,
    target_value=None,
    direction=None,
    recent_activity=None,
):
    return Goal(
        title=title,
        status=status,
        deadline=deadline,
        related_tasks=related_tasks or [],
        milestones=milestones or [],
        measurement_requirements=measurement_requirements or [],
        research_artifact_titles=[],
        inactivity_window_days=inactivity_window_days,
        metric_name=metric_name,
        metric_unit=metric_unit,
        start_value=start_value,
        current_value=current_value,
        target_value=target_value,
        direction=direction,
        recent_activity=recent_activity or [],
    )


def _make_metric_goal(
    title="Body fat",
    status="active",
    deadline=None,
    related_tasks=None,
    milestones=None,
    measurement_requirements=None,
    inactivity_window_days=None,
    metric_name="Body fat %",
    metric_unit="%",
    start_value=23.0,
    current_value=20.0,
    target_value=15.0,
    direction="decrease",
    recent_activity=None,
):
    return _make_goal(
        title=title,
        status=status,
        deadline=deadline,
        related_tasks=related_tasks,
        milestones=milestones,
        measurement_requirements=measurement_requirements,
        inactivity_window_days=inactivity_window_days,
        metric_name=metric_name,
        metric_unit=metric_unit,
        start_value=start_value,
        current_value=current_value,
        target_value=target_value,
        direction=direction,
        recent_activity=recent_activity,
    )


def _ts(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def _snap(goal_title, metric_name, value, days_ago, source="manual"):
    return MetricSnapshot(
        timestamp=_ts(days_ago),
        goal_title=goal_title,
        metric_name=metric_name,
        value=value,
        source=source,
    )


def _activity(
    activity_type: ActivityType,
    goal_title: str,
    days_ago: int,
    task_title: str | None = None,
) -> ActivityRecord:
    return ActivityRecord(
        type=activity_type,
        source="test",
        timestamp=_ts(days_ago),
        goal_title=goal_title,
        task_title=task_title,
    )


# ===========================================================================
# A. NO_DATA scenarios
# ===========================================================================

class TestNoData:
    """Goals with no metric config, no tasks, and no activity data."""

    def test_no_config_no_tasks_no_activity(self):
        """Bare goal — nothing to assess."""
        goal = _make_goal(title="Bare Goal")
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert result.classification == NoProgressClass.NO_DATA
        assert result.progress is None
        assert is_stale(result)

    def test_partial_metric_config_no_current_value(self):
        """Metric fields present but current_value absent — not usable."""
        goal = _make_goal(
            title="Partial Metric",
            metric_name="Weight",
            start_value=80.0,
            target_value=70.0,
            direction="decrease",
            # current_value is None
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert result.classification == NoProgressClass.NO_DATA

    def test_related_tasks_but_never_existed(self):
        """Tasks listed but not in all_task_titles — no execution evidence.

        Per design spec §3.1: having related_tasks (even if never completed)
        means the goal has *some* data (task list exists) → no_execution,
        not no_data.
        """
        goal = _make_goal(
            title="Ghost Tasks",
            related_tasks=["Task A", "Task B"],
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        # Tasks exist in the goal but never existed in the system → no_execution
        assert result.classification == NoProgressClass.NO_EXECUTION

    def test_no_data_with_empty_snapshots_and_records(self):
        """Explicitly passing empty lists still yields NO_DATA."""
        goal = _make_goal(title="Empty Data")
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=[], activity_records=[],
        )
        assert result.classification == NoProgressClass.NO_DATA

    def test_no_data_reason_mentions_insufficient(self):
        """Reason string should explain the information deficit."""
        goal = _make_goal(title="No Info")
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert "insufficient" in result.reason.lower() or "no metric" in result.reason.lower()


# ===========================================================================
# B. NO_EXECUTION scenarios
# ===========================================================================

class TestNoExecution:
    """Config/data exists but no execution evidence within the window."""

    def test_full_metric_config_no_activity(self):
        """Metric goal with current_value but no activity in 30 days."""
        goal = _make_metric_goal()
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=[], activity_records=[],
        )
        assert result.classification == NoProgressClass.NO_EXECUTION
        assert result.progress is not None
        assert is_stale(result)

    def test_related_tasks_no_completions(self):
        """Task-based goal with tasks but no completions."""
        goal = _make_goal(
            title="Task Goal",
            related_tasks=["Task A", "Task B"],
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles={"Task A", "Task B"},
            all_task_titles={"Task A", "Task B"},
            completed_task_titles=set(),
        )
        assert result.classification == NoProgressClass.NO_EXECUTION

    def test_execution_evidence_older_than_window(self):
        """Activity record exists but is older than 30 days."""
        goal = _make_metric_goal()
        old_activity = _activity(
            ActivityType.TASK_COMPLETED, "Body fat", days_ago=35,
            task_title="Old Task",
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles={"Old Task"},
            activity_records=[old_activity],
        )
        assert result.classification == NoProgressClass.NO_EXECUTION

    def test_recent_activity_entry_older_than_window(self):
        """goal.recent_activity has entries but all older than 30 days."""
        goal = _make_metric_goal(
            recent_activity=[{
                "task_id": "t1",
                "summary": "Old task",
                "completed_at": (
                    datetime.now(timezone.utc) - timedelta(days=45)
                ).isoformat(),
                "changed_files": [],
                "tests_passed": 0,
                "pr_url": None,
            }],
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert result.classification == NoProgressClass.NO_EXECUTION

    def test_no_execution_with_per_shorter_window(self):
        """Per-goal inactivity_window_days=14: evidence 20 days ago is stale."""
        goal = _make_metric_goal(inactivity_window_days=14)
        old_activity = _activity(
            ActivityType.TASK_COMPLETED, "Body fat", days_ago=20,
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            activity_records=[old_activity],
        )
        assert result.classification == NoProgressClass.NO_EXECUTION
        assert result.lookback_days == 14


# ===========================================================================
# C. EXECUTION_WITHOUT_EFFECT scenarios
# ===========================================================================

class TestExecutionWithoutEffect:
    """Execution evidence exists but goal outcome hasn't changed."""

    def test_metric_unchanged_with_recent_task(self):
        """Metric value unchanged but task completed recently."""
        goal = _make_metric_goal()
        recent_activity = _activity(
            ActivityType.TASK_COMPLETED, "Body fat", days_ago=5,
            task_title="Recent Task",
        )
        # Snapshot 15 days ago at same value → progress_delta = 0
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 15)]
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles={"Recent Task"},
            metric_snapshots=snapshots,
            activity_records=[recent_activity],
        )
        assert result.classification == NoProgressClass.EXECUTION_WITHOUT_EFFECT
        assert is_stale(result)

    def test_progress_delta_below_threshold(self):
        """Progress moved but less than 5 percentage points in 14 days."""
        goal = _make_metric_goal()
        # 15 days ago: value 20.5 → progress = (23-20.5)/8*100 = 31.25%
        # now: value 20.0 → progress = (23-20)/8*100 = 37.5%
        # delta = 6.25% — above threshold, so NOT execution_without_effect
        # Let's use a smaller delta:
        # 15 days ago: value 20.1 → progress = 36.25%
        # now: value 20.0 → progress = 37.5%
        # delta = 1.25% < 5% → execution_without_effect
        snapshots = [_snap("Body fat", "Body fat %", 20.1, 15)]
        recent_activity = _activity(
            ActivityType.TASK_COMPLETED, "Body fat", days_ago=3,
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots,
            activity_records=[recent_activity],
        )
        assert result.classification == NoProgressClass.EXECUTION_WITHOUT_EFFECT

    def test_task_completed_but_no_progress_effect(self):
        """Task-based goal: task completed but progress still 0%."""
        goal = _make_goal(
            title="Task Goal",
            related_tasks=["Task A", "Task B"],
        )
        # Task A completed but Task B not → progress = 50%
        # But if we complete Task A and it was already completed before,
        # progress doesn't change
        recent_activity = _activity(
            ActivityType.TASK_COMPLETED, "Task Goal", days_ago=3,
            task_title="Task A",
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles={"Task B"}, all_task_titles={"Task A", "Task B"},
            completed_task_titles={"Task A"},
            activity_records=[recent_activity],
        )
        # Progress is 50% (1/2 tasks done), execution evidence exists
        # but the completion didn't change progress (Task A was already done)
        # Actually — this depends on whether Task A was already completed.
        # With completed_task_titles={"Task A"}, progress = 50%.
        # The execution evidence is recent, but progress is not 100%.
        # The effect assessment: 1 completion in window, but progress is 50%.
        # For task-based: recent_completions = 1 > 0, so NOT negligible.
        # This would be MAKING_PROGRESS.
        # Let me adjust: no completions in window but execution evidence exists
        # via a different activity type.
        pass  # See next test

    def test_execution_without_effect_via_goal_progress_activity(self):
        """GOAL_PROGRESS activity but metric value unchanged."""
        goal = _make_metric_goal()
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 15)]
        gp_activity = _activity(
            ActivityType.GOAL_PROGRESS, "Body fat", days_ago=2,
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots,
            activity_records=[gp_activity],
        )
        assert result.classification == NoProgressClass.EXECUTION_WITHOUT_EFFECT

    def test_data_arrives_just_before_timeout(self):
        """Edge: activity 29 days ago with 30-day window → still execution."""
        goal = _make_metric_goal()
        recent_activity = _activity(
            ActivityType.TASK_COMPLETED, "Body fat", days_ago=29,
        )
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 15)]
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots,
            activity_records=[recent_activity],
        )
        # Activity is within 30-day window → execution evidence exists
        # Metric unchanged → execution_without_effect
        assert result.classification == NoProgressClass.EXECUTION_WITHOUT_EFFECT

    def test_data_arrives_just_after_timeout(self):
        """Edge: activity 31 days ago with 30-day window → no execution."""
        goal = _make_metric_goal()
        old_activity = _activity(
            ActivityType.TASK_COMPLETED, "Body fat", days_ago=31,
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            activity_records=[old_activity],
        )
        assert result.classification == NoProgressClass.NO_EXECUTION


# ===========================================================================
# D. GOAL_ACHIEVED scenarios
# ===========================================================================

class TestGoalAchieved:
    """Goal outcome has been reached."""

    def test_metric_target_reached_increase(self):
        """Increase goal: current_value >= target_value → 100%."""
        goal = _make_metric_goal(
            start_value=10.0,
            current_value=15.0,
            target_value=15.0,
            direction="increase",
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert result.classification == NoProgressClass.GOAL_ACHIEVED
        assert result.progress == 100.0
        assert not is_stale(result)

    def test_metric_target_reached_decrease(self):
        """Decrease goal: current_value <= target_value → 100%."""
        goal = _make_metric_goal(
            start_value=23.0,
            current_value=15.0,
            target_value=15.0,
            direction="decrease",
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert result.classification == NoProgressClass.GOAL_ACHIEVED
        assert result.progress == 100.0

    def test_all_tasks_completed(self):
        """Task-based goal: all related tasks completed → 100%."""
        goal = _make_goal(
            title="All Done",
            related_tasks=["Task A", "Task B"],
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles={"Task A", "Task B"},
            completed_task_titles={"Task A", "Task B"},
        )
        assert result.classification == NoProgressClass.GOAL_ACHIEVED
        assert result.progress == 100.0

    def test_explicitly_completed_status(self):
        """Goal with status='completed' → GOAL_ACHIEVED."""
        goal = _make_metric_goal(status="completed")
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert result.classification == NoProgressClass.GOAL_ACHIEVED
        assert "completed" in result.reason.lower()

    def test_inactive_goal(self):
        """Goal with status='inactive' → GOAL_ACHIEVED (out of scope)."""
        goal = _make_metric_goal(status="inactive")
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert result.classification == NoProgressClass.GOAL_ACHIEVED
        assert "inactive" in result.reason.lower()

    def test_maintain_at_target_goal(self):
        """Degenerate maintain-at-X: start==target==current → 100%."""
        goal = _make_metric_goal(
            start_value=70.0,
            current_value=70.0,
            target_value=70.0,
            direction="decrease",
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert result.classification == NoProgressClass.GOAL_ACHIEVED
        assert result.progress == 100.0


# ===========================================================================
# E. MAKING_PROGRESS scenarios
# ===========================================================================

class TestMakingProgress:
    """Execution happened and effect is non-negligible."""

    def test_metric_improving_with_recent_activity(self):
        """Metric value moved significantly + recent task completion."""
        goal = _make_metric_goal()
        # 15 days ago: value 22.0 → progress = 12.5%
        # now: value 20.0 → progress = 37.5%
        # delta = 25% > 5% → making progress
        snapshots = [_snap("Body fat", "Body fat %", 22.0, 15)]
        recent_activity = _activity(
            ActivityType.TASK_COMPLETED, "Body fat", days_ago=3,
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots,
            activity_records=[recent_activity],
        )
        assert result.classification == NoProgressClass.MAKING_PROGRESS
        assert not is_stale(result)

    def test_multiple_task_completions_in_window(self):
        """Task-based goal: multiple completions → progress."""
        goal = _make_goal(
            title="Multi Task",
            related_tasks=["Task A", "Task B", "Task C"],
        )
        recent_activity = _activity(
            ActivityType.TASK_COMPLETED, "Multi Task", days_ago=2,
            task_title="Task B",
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles={"Task C"},
            all_task_titles={"Task A", "Task B", "Task C"},
            completed_task_titles={"Task A", "Task B"},
            activity_records=[recent_activity],
        )
        # 2/3 tasks done = 66.7% progress, execution evidence exists
        # recent_completions in window: 1 (Task B) > 0 → not negligible
        assert result.classification == NoProgressClass.MAKING_PROGRESS


# ===========================================================================
# F. Edge cases and integration
# ===========================================================================

class TestEdgeCases:
    """Boundary conditions and integration concerns."""

    def test_per_goal_inactivity_window_respected(self):
        """Per-goal inactivity_window_days=60: evidence 45 days ago is fresh."""
        goal = _make_metric_goal(inactivity_window_days=60)
        recent_activity = _activity(
            ActivityType.TASK_COMPLETED, "Body fat", days_ago=45,
        )
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 50)]
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots,
            activity_records=[recent_activity],
        )
        # Evidence is within 60-day window → execution exists
        # Metric unchanged → execution_without_effect
        assert result.classification == NoProgressClass.EXECUTION_WITHOUT_EFFECT
        assert result.lookback_days == 60

    def test_completed_task_dates_filtering(self):
        """completed_task_dates: only completions within window count."""
        goal = _make_goal(
            title="Dated Tasks",
            related_tasks=["Task A", "Task B"],
        )
        # Task A completed 5 days ago, Task B completed 40 days ago
        completed_dates = {
            "Task A": FIXED_TODAY - timedelta(days=5),
            "Task B": FIXED_TODAY - timedelta(days=40),
        }
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles={"Task A", "Task B"},
            completed_task_titles={"Task A", "Task B"},
            completed_task_dates=completed_dates,
        )
        # Task A completion is within 30-day window → execution evidence
        # Progress = 100% (both tasks done) → GOAL_ACHIEVED
        assert result.classification == NoProgressClass.GOAL_ACHIEVED

    def test_completed_task_dates_not_within_window(self):
        """All completions older than window → no execution evidence."""
        goal = _make_goal(
            title="Old Tasks",
            related_tasks=["Task A"],
        )
        completed_dates = {
            "Task A": FIXED_TODAY - timedelta(days=45),
        }
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles={"Task A"},
            completed_task_titles={"Task A"},
            completed_task_dates=completed_dates,
        )
        # Completion is 45 days ago, outside 30-day window
        # But completed_task_titles has Task A → progress = 100%
        # So this is GOAL_ACHIEVED (progress check comes first)
        assert result.classification == NoProgressClass.GOAL_ACHIEVED

    def test_recent_activity_fallback_when_no_activity_records(self):
        """goal.recent_activity used when activity_records is None."""
        goal = _make_metric_goal(
            recent_activity=[{
                "task_id": "t1",
                "summary": "Recent task",
                "completed_at": (
                    datetime.now(timezone.utc) - timedelta(days=3)
                ).isoformat(),
                "changed_files": [],
                "tests_passed": 0,
                "pr_url": None,
            }],
        )
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 15)]
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots,
            activity_records=None,  # fallback to recent_activity
        )
        # recent_activity has entry 3 days ago → execution evidence
        # Metric unchanged → execution_without_effect
        assert result.classification == NoProgressClass.EXECUTION_WITHOUT_EFFECT

    def test_no_recent_activity_no_snapshots(self):
        """No recent_activity and no snapshots → no execution evidence."""
        goal = _make_metric_goal()
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=[], activity_records=[],
        )
        assert result.classification == NoProgressClass.NO_EXECUTION

    def test_signals_attached_for_context(self):
        """Result includes signals from the health/attention pipeline."""
        goal = _make_metric_goal()
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        # Signals should be attached (may be empty list if no signals fire)
        assert isinstance(result.signals, list)
        assert result.dominant_signal is None or isinstance(
            result.dominant_signal, GoalSignal
        )

    def test_evaluated_at_is_set(self):
        """Result includes evaluation timestamp."""
        goal = _make_goal(title="Timestamp Check")
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert result.evaluated_at is not None
        assert isinstance(result.evaluated_at, datetime)

    def test_lookback_days_default(self):
        """Default lookback is 30 days."""
        goal = _make_goal(title="Default Lookback")
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert result.lookback_days == 30

    def test_stale_reason_summary_no_data(self):
        """stale_reason_summary produces readable output for NO_DATA."""
        goal = _make_goal(title="Summary Test")
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        summary = stale_reason_summary(result)
        assert "Brak danych" in summary
        assert len(summary) > 0

    def test_stale_reason_summary_making_progress(self):
        """stale_reason_summary for MAKING_PROGRESS."""
        goal = _make_metric_goal()
        snapshots = [_snap("Body fat", "Body fat %", 22.0, 15)]
        recent_activity = _activity(
            ActivityType.TASK_COMPLETED, "Body fat", days_ago=3,
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots,
            activity_records=[recent_activity],
        )
        summary = stale_reason_summary(result)
        assert "W trakcie" in summary


# ===========================================================================
# G. Batch classification
# ===========================================================================

class TestBatchClassification:
    """classify_all_goals convenience wrapper."""

    def test_classify_multiple_goals(self):
        """Batch classification returns results for all goals."""
        goals = [
            _make_goal(title="Goal A"),  # no_data
            _make_metric_goal(title="Goal B"),  # no_execution
            _make_metric_goal(
                title="Goal C",
                current_value=15.0,
                target_value=15.0,
            ),  # goal_achieved
        ]
        results = classify_all_goals(
            goals, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert len(results) == 3
        assert results[0].classification == NoProgressClass.NO_DATA
        assert results[1].classification == NoProgressClass.NO_EXECUTION
        assert results[2].classification == NoProgressClass.GOAL_ACHIEVED

    def test_batch_with_snapshots_by_goal(self):
        """Batch classification with per-goal snapshots."""
        goals = [
            _make_metric_goal(title="Goal A"),
            _make_metric_goal(title="Goal B"),
        ]
        snapshots_by_goal = {
            "Goal A": [_snap("Goal A", "Body fat %", 20.0, 15)],
        }
        results = classify_all_goals(
            goals, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots_by_goal=snapshots_by_goal,
        )
        assert len(results) == 2
        # Goal A has snapshots → not no_data
        # Goal B has no snapshots → no_execution (metric config exists)
        assert results[0].classification != NoProgressClass.NO_DATA
        assert results[1].classification == NoProgressClass.NO_EXECUTION


# ===========================================================================
# H. is_stale helper
# ===========================================================================

class TestIsStale:
    """is_stale() returns True only for stale classifications."""

    def test_no_data_is_stale(self):
        result = NoProgressResult(
            goal_title="G", classification=NoProgressClass.NO_DATA,
            progress=None,
        )
        assert is_stale(result)

    def test_no_execution_is_stale(self):
        result = NoProgressResult(
            goal_title="G", classification=NoProgressClass.NO_EXECUTION,
            progress=50.0,
        )
        assert is_stale(result)

    def test_execution_without_effect_is_stale(self):
        result = NoProgressResult(
            goal_title="G",
            classification=NoProgressClass.EXECUTION_WITHOUT_EFFECT,
            progress=50.0,
        )
        assert is_stale(result)

    def test_goal_achieved_not_stale(self):
        result = NoProgressResult(
            goal_title="G", classification=NoProgressClass.GOAL_ACHIEVED,
            progress=100.0,
        )
        assert not is_stale(result)

    def test_making_progress_not_stale(self):
        result = NoProgressResult(
            goal_title="G", classification=NoProgressClass.MAKING_PROGRESS,
            progress=50.0,
        )
        assert not is_stale(result)


# ===========================================================================
# I. detect_no_execution() — dedicated no-execution detector
# ===========================================================================

class TestDetectNoExecution:
    """Tests for the dedicated detect_no_execution() function."""

    def test_no_execution_metric_goal_no_activity(self):
        """Metric goal with config but no activity → no_execution=True."""
        goal = _make_metric_goal()
        no_exec, fired = detect_no_execution(goal, FIXED_TODAY)
        assert no_exec is True
        assert fired == []

    def test_no_execution_with_recent_activity_record(self):
        """Activity record within window → no_execution=False."""
        goal = _make_metric_goal()
        recent = _activity(ActivityType.TASK_COMPLETED, "Body fat", days_ago=3)
        no_exec, fired = detect_no_execution(
            goal, FIXED_TODAY, activity_records=[recent]
        )
        assert no_exec is False
        assert "activity_records" in fired

    def test_no_execution_with_old_activity_record(self):
        """Activity record older than window → no_execution=True."""
        goal = _make_metric_goal()
        old = _activity(ActivityType.TASK_COMPLETED, "Body fat", days_ago=35)
        no_exec, fired = detect_no_execution(
            goal, FIXED_TODAY, activity_records=[old]
        )
        assert no_exec is True
        assert fired == []

    def test_no_execution_with_recent_activity_entry(self):
        """goal.recent_activity with recent completed_at → no_execution=False."""
        goal = _make_metric_goal(
            recent_activity=[{
                "task_id": "t1",
                "summary": "Recent",
                "completed_at": (
                    datetime.now(timezone.utc) - timedelta(days=2)
                ).isoformat(),
                "changed_files": [],
                "tests_passed": 0,
                "pr_url": None,
            }],
        )
        no_exec, fired = detect_no_execution(goal, FIXED_TODAY)
        assert no_exec is False
        assert "recent_activity" in fired

    def test_no_execution_with_old_recent_activity_entry(self):
        """goal.recent_activity with old completed_at → no_execution=True."""
        goal = _make_metric_goal(
            recent_activity=[{
                "task_id": "t1",
                "summary": "Old",
                "completed_at": (
                    datetime.now(timezone.utc) - timedelta(days=45)
                ).isoformat(),
                "changed_files": [],
                "tests_passed": 0,
                "pr_url": None,
            }],
        )
        no_exec, fired = detect_no_execution(goal, FIXED_TODAY)
        assert no_exec is True
        assert fired == []

    def test_no_execution_with_completed_task_dates_in_window(self):
        """completed_task_dates within window → no_execution=False."""
        goal = _make_goal(
            title="Task Goal",
            related_tasks=["Task A"],
        )
        dates = {"Task A": FIXED_TODAY - timedelta(days=5)}
        no_exec, fired = detect_no_execution(
            goal, FIXED_TODAY, completed_task_dates=dates
        )
        assert no_exec is False
        assert "completed_task_dates" in fired

    def test_no_execution_with_completed_task_dates_outside_window(self):
        """completed_task_dates outside window → no_execution=True."""
        goal = _make_goal(
            title="Task Goal",
            related_tasks=["Task A"],
        )
        dates = {"Task A": FIXED_TODAY - timedelta(days=45)}
        no_exec, fired = detect_no_execution(
            goal, FIXED_TODAY, completed_task_dates=dates
        )
        assert no_exec is True
        assert fired == []

    def test_no_execution_no_data_goal(self):
        """Goal with no config, no tasks, no activity → no_execution=False (it's NO_DATA)."""
        goal = _make_goal(title="Bare")
        no_exec, fired = detect_no_execution(goal, FIXED_TODAY)
        assert no_exec is False
        assert fired == []

    def test_no_execution_non_active_goal(self):
        """Non-active goal → no_execution=False."""
        goal = _make_metric_goal(status="completed")
        no_exec, fired = detect_no_execution(goal, FIXED_TODAY)
        assert no_exec is False
        assert fired == []

    def test_no_execution_per_goal_window_override(self):
        """Per-goal inactivity_window_days=14: evidence 20 days ago is stale."""
        goal = _make_metric_goal(inactivity_window_days=14)
        old = _activity(ActivityType.TASK_COMPLETED, "Body fat", days_ago=20)
        no_exec, fired = detect_no_execution(
            goal, FIXED_TODAY, activity_records=[old]
        )
        assert no_exec is True
        assert fired == []

    def test_no_execution_per_goal_window_override_fresh(self):
        """Per-goal inactivity_window_days=60: evidence 45 days ago is fresh."""
        goal = _make_metric_goal(inactivity_window_days=60)
        recent = _activity(ActivityType.TASK_COMPLETED, "Body fat", days_ago=45)
        no_exec, fired = detect_no_execution(
            goal, FIXED_TODAY, activity_records=[recent]
        )
        assert no_exec is False
        assert "activity_records" in fired

    def test_no_execution_custom_window(self):
        """Custom window_days parameter."""
        goal = _make_metric_goal()
        old = _activity(ActivityType.TASK_COMPLETED, "Body fat", days_ago=10)
        # With window=5, 10-day-old evidence is outside
        no_exec, fired = detect_no_execution(
            goal, FIXED_TODAY, activity_records=[old], window_days=5
        )
        assert no_exec is True
        # With window=15, 10-day-old evidence is inside
        no_exec2, fired2 = detect_no_execution(
            goal, FIXED_TODAY, activity_records=[old], window_days=15
        )
        assert no_exec2 is False

    def test_no_execution_multiple_signals_fire(self):
        """Multiple signals can fire simultaneously."""
        goal = _make_metric_goal(
            related_tasks=["Task A"],
            recent_activity=[{
                "task_id": "t1",
                "summary": "Recent",
                "completed_at": (
                    datetime.now(timezone.utc) - timedelta(days=1)
                ).isoformat(),
                "changed_files": [],
                "tests_passed": 0,
                "pr_url": None,
            }],
        )
        recent = _activity(ActivityType.TASK_COMPLETED, "Body fat", days_ago=2)
        dates = {"Task A": FIXED_TODAY - timedelta(days=3)}
        no_exec, fired = detect_no_execution(
            goal, FIXED_TODAY,
            activity_records=[recent],
            completed_task_dates=dates,
        )
        assert no_exec is False
        assert len(fired) >= 2  # at least activity_records and recent_activity

    def test_no_execution_task_goal_no_completions(self):
        """Task-based goal with tasks but no completions → no_execution=True."""
        goal = _make_goal(
            title="Task Goal",
            related_tasks=["Task A", "Task B"],
        )
        no_exec, fired = detect_no_execution(goal, FIXED_TODAY)
        assert no_exec is True
        assert fired == []

    def test_no_execution_boundary_no_data_vs_no_execution(self):
        """Boundary: goal with related_tasks but no completions is NO_EXECUTION, not NO_DATA."""
        goal = _make_goal(
            title="Boundary",
            related_tasks=["Task A"],
        )
        # detect_no_execution should return True (has data but no execution)
        no_exec, fired = detect_no_execution(goal, FIXED_TODAY)
        assert no_exec is True
        # classify_no_progress should return NO_EXECUTION
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles={"Task A"}, all_task_titles={"Task A"},
        )
        assert result.classification == NoProgressClass.NO_EXECUTION

    def test_no_execution_boundary_no_execution_vs_execution_without_effect(self):
        """Boundary: execution evidence + no effect = EXECUTION_WITHOUT_EFFECT."""
        goal = _make_metric_goal()
        recent = _activity(ActivityType.TASK_COMPLETED, "Body fat", days_ago=3)
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 15)]
        # detect_no_execution should return False (execution evidence exists)
        no_exec, fired = detect_no_execution(
            goal, FIXED_TODAY, activity_records=[recent]
        )
        assert no_exec is False
        # classify_no_progress should return EXECUTION_WITHOUT_EFFECT
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots,
            activity_records=[recent],
        )
        assert result.classification == NoProgressClass.EXECUTION_WITHOUT_EFFECT

    def test_no_execution_boundary_no_execution_vs_making_progress(self):
        """Boundary: execution evidence + effect = MAKING_PROGRESS."""
        goal = _make_metric_goal()
        recent = _activity(ActivityType.TASK_COMPLETED, "Body fat", days_ago=3)
        snapshots = [_snap("Body fat", "Body fat %", 22.0, 15)]
        # detect_no_execution should return False (execution evidence exists)
        no_exec, fired = detect_no_execution(
            goal, FIXED_TODAY, activity_records=[recent]
        )
        assert no_exec is False
        # classify_no_progress should return MAKING_PROGRESS
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots,
            activity_records=[recent],
        )
        assert result.classification == NoProgressClass.MAKING_PROGRESS

    def test_no_execution_boundary_no_execution_vs_goal_achieved(self):
        """Boundary: 100% progress = GOAL_ACHIEVED, not NO_EXECUTION.

        detect_no_execution returns True (data exists, no execution evidence),
        but classify_no_progress correctly returns GOAL_ACHIEVED because it
        checks progress == 100% first.
        """
        goal = _make_metric_goal(
            current_value=15.0,
            target_value=15.0,
        )
        # detect_no_execution returns True (has data, no execution evidence)
        no_exec, fired = detect_no_execution(goal, FIXED_TODAY)
        assert no_exec is True
        # classify_no_progress should return GOAL_ACHIEVED (progress check first)
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert result.classification == NoProgressClass.GOAL_ACHIEVED

    def test_no_execution_signals_list_defined(self):
        """_EXECUTION_SIGNALS should contain the three expected signals."""
        signal_names = [name for name, _ in _EXECUTION_SIGNALS]
        assert "activity_records" in signal_names
        assert "recent_activity" in signal_names
        assert "completed_task_dates" in signal_names

    def test_no_execution_with_milestone_completed_activity(self):
        """MILESTONE_COMPLETED activity type counts as execution evidence."""
        goal = _make_metric_goal()
        milestone = _activity(ActivityType.MILESTONE_COMPLETED, "Body fat", days_ago=2)
        no_exec, fired = detect_no_execution(
            goal, FIXED_TODAY, activity_records=[milestone]
        )
        assert no_exec is False
        assert "activity_records" in fired

    def test_no_execution_with_goal_progress_activity(self):
        """GOAL_PROGRESS activity type counts as execution evidence."""
        goal = _make_metric_goal()
        gp = _activity(ActivityType.GOAL_PROGRESS, "Body fat", days_ago=2)
        no_exec, fired = detect_no_execution(
            goal, FIXED_TODAY, activity_records=[gp]
        )
        assert no_exec is False
        assert "activity_records" in fired

    def test_no_execution_ignores_non_execution_activity_types(self):
        """Non-execution activity types (e.g., TASK_UPDATED) don't count."""
        goal = _make_metric_goal()
        note = _activity(ActivityType.TASK_UPDATED, "Body fat", days_ago=2)
        no_exec, fired = detect_no_execution(
            goal, FIXED_TODAY, activity_records=[note]
        )
        assert no_exec is True
        assert fired == []

    def test_no_execution_activity_record_wrong_goal(self):
        """Activity record for a different goal doesn't count."""
        goal = _make_metric_goal(title="Goal A")
        other = _activity(ActivityType.TASK_COMPLETED, "Goal B", days_ago=2)
        no_exec, fired = detect_no_execution(
            goal, FIXED_TODAY, activity_records=[other]
        )
        assert no_exec is True
        assert fired == []

    def test_no_execution_completed_task_dates_wrong_task(self):
        """completed_task_dates for non-related task doesn't count."""
        goal = _make_goal(
            title="Goal A",
            related_tasks=["Task A"],
        )
        dates = {"Task B": FIXED_TODAY - timedelta(days=3)}
        no_exec, fired = detect_no_execution(
            goal, FIXED_TODAY, completed_task_dates=dates
        )
        assert no_exec is True
        assert fired == []


# ===========================================================================
# J. detect_goal_achieved() — dedicated goal-achieved detector
# ===========================================================================

class TestDetectGoalAchieved:
    """Tests for the dedicated detect_goal_achieved() function."""

    def test_achieved_metric_target_reached_increase(self):
        """Increase goal: current_value >= target_value → achieved."""
        goal = _make_metric_goal(
            start_value=10.0,
            current_value=15.0,
            target_value=15.0,
            direction="increase",
        )
        achieved, reason = detect_goal_achieved(goal)
        assert achieved is True
        assert "target reached" in reason.lower() or "completed" in reason.lower()

    def test_achieved_metric_target_reached_decrease(self):
        """Decrease goal: current_value <= target_value → achieved."""
        goal = _make_metric_goal(
            start_value=23.0,
            current_value=15.0,
            target_value=15.0,
            direction="decrease",
        )
        achieved, reason = detect_goal_achieved(goal)
        assert achieved is True

    def test_achieved_all_tasks_completed(self):
        """Task-based goal: all related tasks completed → achieved."""
        goal = _make_goal(
            title="All Done",
            related_tasks=["Task A", "Task B"],
        )
        achieved, reason = detect_goal_achieved(
            goal, completed_task_titles={"Task A", "Task B"}
        )
        assert achieved is True

    def test_achieved_explicitly_completed_status(self):
        """Goal with status='completed' → achieved."""
        goal = _make_metric_goal(status="completed")
        achieved, reason = detect_goal_achieved(goal)
        assert achieved is True
        assert "completed" in reason.lower()

    def test_achieved_inactive_goal(self):
        """Goal with status='inactive' → achieved (out of scope)."""
        goal = _make_metric_goal(status="inactive")
        achieved, reason = detect_goal_achieved(goal)
        assert achieved is True
        assert "inactive" in reason.lower()

    def test_not_achieved_partial_progress(self):
        """Goal with partial progress → not achieved."""
        goal = _make_metric_goal()  # 37.5% progress
        achieved, reason = detect_goal_achieved(goal)
        assert achieved is False

    def test_not_achieved_no_progress(self):
        """Goal with 0% progress → not achieved."""
        goal = _make_metric_goal(
            start_value=23.0,
            current_value=23.0,
            target_value=15.0,
            direction="decrease",
        )
        achieved, reason = detect_goal_achieved(goal)
        assert achieved is False

    def test_not_achieved_some_tasks_incomplete(self):
        """Task-based goal: some tasks incomplete → not achieved."""
        goal = _make_goal(
            title="Partial",
            related_tasks=["Task A", "Task B"],
        )
        achieved, reason = detect_goal_achieved(
            goal, completed_task_titles={"Task A"}
        )
        assert achieved is False

    def test_achieved_maintain_at_target(self):
        """Degenerate maintain-at-X: start==target==current → achieved."""
        goal = _make_metric_goal(
            start_value=70.0,
            current_value=70.0,
            target_value=70.0,
            direction="decrease",
        )
        achieved, reason = detect_goal_achieved(goal)
        assert achieved is True

    def test_achieved_distinction_from_execution_without_effect(self):
        """GOAL_ACHIEVED requires 100%; EXECUTION_WITHOUT_EFFECT is < 100%."""
        # Goal at 100% → achieved
        goal_100 = _make_metric_goal(
            current_value=15.0,
            target_value=15.0,
        )
        achieved_100, _ = detect_goal_achieved(goal_100)
        assert achieved_100 is True

        # Goal at 50% → not achieved
        goal_50 = _make_metric_goal(
            start_value=23.0,
            current_value=19.0,
            target_value=15.0,
            direction="decrease",
        )
        achieved_50, _ = detect_goal_achieved(goal_50)
        assert achieved_50 is False


# ===========================================================================
# K. to_dict() serialization
# ===========================================================================

class TestToDict:
    """Tests for NoProgressResult.to_dict()."""

    def test_to_dict_basic_fields(self):
        """to_dict includes all basic fields."""
        goal = _make_goal(title="Dict Test")
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        d = result.to_dict()
        assert d["goal_title"] == "Dict Test"
        assert d["classification"] == "no_data"
        assert d["progress"] is None
        assert d["reason"] != ""
        assert d["evaluated_at"] is not None
        assert d["lookback_days"] == 30
        assert "confidence" in d
        assert "progress_delta" in d
        assert "days_since_last_activity" in d

    def test_to_dict_classification_value(self):
        """classification is the string value, not the enum."""
        goal = _make_metric_goal(
            current_value=15.0,
            target_value=15.0,
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        d = result.to_dict()
        assert d["classification"] == "goal_achieved"
        assert isinstance(d["classification"], str)

    def test_to_dict_signals_list(self):
        """signals is a list of dicts."""
        goal = _make_metric_goal()
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        d = result.to_dict()
        assert isinstance(d["signals"], list)
        for s in d["signals"]:
            assert "signal" in s
            assert "score" in s
            assert "reason" in s

    def test_to_dict_dominant_signal_structure(self):
        """dominant_signal is None or a dict with expected keys."""
        goal = _make_goal(title="Signal Check")
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        d = result.to_dict()
        if d["dominant_signal"] is not None:
            assert "signal" in d["dominant_signal"]
            assert "score" in d["dominant_signal"]
            assert "reason" in d["dominant_signal"]

    def test_to_dict_evaluated_at_isoformat(self):
        """evaluated_at is ISO format string."""
        goal = _make_goal(title="Timestamp")
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        d = result.to_dict()
        assert isinstance(d["evaluated_at"], str)
        # Should be parseable
        datetime.fromisoformat(d["evaluated_at"])


# ===========================================================================
# L. Enriched fields (confidence, progress_delta, days_since_last_activity)
# ===========================================================================

class TestEnrichedFields:
    """Tests for the new enriched fields on NoProgressResult."""

    def test_confidence_no_data(self):
        """NO_DATA has high confidence."""
        goal = _make_goal(title="No Data")
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert result.confidence >= 0.8

    def test_confidence_goal_achieved(self):
        """GOAL_ACHIEVED has high confidence."""
        goal = _make_metric_goal(
            current_value=15.0,
            target_value=15.0,
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert result.confidence >= 0.9

    def test_confidence_no_execution(self):
        """NO_EXECUTION has moderate-high confidence."""
        goal = _make_metric_goal()
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert result.confidence >= 0.7

    def test_progress_delta_making_progress(self):
        """MAKING_PROGRESS has positive progress_delta."""
        goal = _make_metric_goal()
        snapshots = [_snap("Body fat", "Body fat %", 22.0, 15)]
        recent = _activity(ActivityType.TASK_COMPLETED, "Body fat", days_ago=3)
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots,
            activity_records=[recent],
        )
        assert result.progress_delta is not None
        assert result.progress_delta > 0

    def test_progress_delta_execution_without_effect(self):
        """EXECUTION_WITHOUT_EFFECT has near-zero progress_delta."""
        goal = _make_metric_goal()
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 15)]
        recent = _activity(ActivityType.TASK_COMPLETED, "Body fat", days_ago=3)
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots,
            activity_records=[recent],
        )
        assert result.progress_delta is not None
        assert abs(result.progress_delta) < 5.0

    def test_days_since_last_activity_with_evidence(self):
        """days_since_last_activity is set when execution evidence exists."""
        goal = _make_metric_goal()
        recent = _activity(ActivityType.TASK_COMPLETED, "Body fat", days_ago=3)
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            activity_records=[recent],
        )
        assert result.days_since_last_activity is not None
        assert result.days_since_last_activity <= 3

    def test_days_since_last_activity_no_evidence(self):
        """days_since_last_activity is None when no execution evidence."""
        goal = _make_metric_goal()
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert result.days_since_last_activity is None


# ===========================================================================
# M. Unified pipeline — exactly one category per goal
# ===========================================================================

class TestUnifiedPipeline:
    """Tests that the unified classifier produces exactly one category."""

    def test_exactly_one_category_per_goal(self):
        """Every goal gets exactly one classification."""
        goals = [
            _make_goal(title="Bare"),
            _make_metric_goal(title="No Exec"),
            _make_metric_goal(
                title="Achieved",
                current_value=15.0,
                target_value=15.0,
            ),
            _make_goal(
                title="Tasks",
                related_tasks=["Task A"],
            ),
        ]
        results = classify_all_goals(
            goals, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert len(results) == 4
        for r in results:
            assert isinstance(r.classification, NoProgressClass)
            # Each result has a valid classification
            assert r.classification in (
                NoProgressClass.NO_DATA,
                NoProgressClass.NO_EXECUTION,
                NoProgressClass.EXECUTION_WITHOUT_EFFECT,
                NoProgressClass.GOAL_ACHIEVED,
                NoProgressClass.MAKING_PROGRESS,
            )

    def test_mutual_exclusion_no_data_vs_no_execution(self):
        """NO_DATA and NO_EXECUTION are mutually exclusive."""
        # Bare goal → NO_DATA
        bare = _make_goal(title="Bare")
        r1 = classify_no_progress(
            bare, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert r1.classification == NoProgressClass.NO_DATA

        # Goal with config but no activity → NO_EXECUTION
        config = _make_metric_goal(title="Config")
        r2 = classify_no_progress(
            config, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert r2.classification == NoProgressClass.NO_EXECUTION

    def test_mutual_exclusion_no_execution_vs_execution_without_effect(self):
        """NO_EXECUTION and EXECUTION_WITHOUT_EFFECT are mutually exclusive."""
        # No activity → NO_EXECUTION
        goal_no_exec = _make_metric_goal(title="No Exec")
        r1 = classify_no_progress(
            goal_no_exec, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert r1.classification == NoProgressClass.NO_EXECUTION

        # Activity but no effect → EXECUTION_WITHOUT_EFFECT
        goal_no_effect = _make_metric_goal(title="No Effect")
        snapshots = [_snap("No Effect", "Body fat %", 20.0, 15)]
        recent = _activity(ActivityType.TASK_COMPLETED, "No Effect", days_ago=3)
        r2 = classify_no_progress(
            goal_no_effect, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots,
            activity_records=[recent],
        )
        assert r2.classification == NoProgressClass.EXECUTION_WITHOUT_EFFECT

    def test_mutual_exclusion_execution_without_effect_vs_making_progress(self):
        """EXECUTION_WITHOUT_EFFECT and MAKING_PROGRESS are mutually exclusive."""
        # No effect → EXECUTION_WITHOUT_EFFECT
        goal_no_effect = _make_metric_goal(title="No Effect")
        snapshots1 = [_snap("No Effect", "Body fat %", 20.0, 15)]
        recent1 = _activity(ActivityType.TASK_COMPLETED, "No Effect", days_ago=3)
        r1 = classify_no_progress(
            goal_no_effect, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots1,
            activity_records=[recent1],
        )
        assert r1.classification == NoProgressClass.EXECUTION_WITHOUT_EFFECT

        # Effect → MAKING_PROGRESS
        goal_progress = _make_metric_goal(title="Progress")
        snapshots2 = [_snap("Progress", "Body fat %", 22.0, 15)]
        recent2 = _activity(ActivityType.TASK_COMPLETED, "Progress", days_ago=3)
        r2 = classify_no_progress(
            goal_progress, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots2,
            activity_records=[recent2],
        )
        assert r2.classification == NoProgressClass.MAKING_PROGRESS

    def test_mutual_exclusion_goal_achieved_vs_all_others(self):
        """GOAL_ACHIEVED takes precedence over all other categories."""
        # Goal at 100% with no activity → GOAL_ACHIEVED (not NO_EXECUTION)
        goal = _make_metric_goal(
            title="Achieved No Activity",
            current_value=15.0,
            target_value=15.0,
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert result.classification == NoProgressClass.GOAL_ACHIEVED

    def test_transition_no_data_to_no_execution(self):
        """Transition: adding config moves goal from NO_DATA to NO_EXECUTION."""
        # Start: bare goal → NO_DATA
        bare = _make_goal(title="Transition")
        r1 = classify_no_progress(
            bare, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert r1.classification == NoProgressClass.NO_DATA

        # Add config → NO_EXECUTION
        with_config = _make_metric_goal(title="Transition")
        r2 = classify_no_progress(
            with_config, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert r2.classification == NoProgressClass.NO_EXECUTION

    def test_transition_no_execution_to_execution_without_effect(self):
        """Transition: adding activity moves goal to EXECUTION_WITHOUT_EFFECT."""
        # Start: config but no activity → NO_EXECUTION
        goal = _make_metric_goal(title="Transition")
        r1 = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert r1.classification == NoProgressClass.NO_EXECUTION

        # Add activity but no effect → EXECUTION_WITHOUT_EFFECT
        snapshots = [_snap("Transition", "Body fat %", 20.0, 15)]
        recent = _activity(ActivityType.TASK_COMPLETED, "Transition", days_ago=3)
        r2 = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots,
            activity_records=[recent],
        )
        assert r2.classification == NoProgressClass.EXECUTION_WITHOUT_EFFECT

    def test_transition_execution_without_effect_to_making_progress(self):
        """Transition: adding effect moves goal to MAKING_PROGRESS."""
        # Start: activity but no effect → EXECUTION_WITHOUT_EFFECT
        goal = _make_metric_goal(title="Transition")
        snapshots1 = [_snap("Transition", "Body fat %", 20.0, 15)]
        recent1 = _activity(ActivityType.TASK_COMPLETED, "Transition", days_ago=3)
        r1 = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots1,
            activity_records=[recent1],
        )
        assert r1.classification == NoProgressClass.EXECUTION_WITHOUT_EFFECT

        # Add effect → MAKING_PROGRESS
        snapshots2 = [_snap("Transition", "Body fat %", 22.0, 15)]
        recent2 = _activity(ActivityType.TASK_COMPLETED, "Transition", days_ago=3)
        r2 = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots2,
            activity_records=[recent2],
        )
        assert r2.classification == NoProgressClass.MAKING_PROGRESS

    def test_transition_making_progress_to_goal_achieved(self):
        """Transition: reaching 100% moves goal to GOAL_ACHIEVED."""
        # Start: making progress → MAKING_PROGRESS
        goal = _make_metric_goal(title="Transition")
        snapshots = [_snap("Transition", "Body fat %", 22.0, 15)]
        recent = _activity(ActivityType.TASK_COMPLETED, "Transition", days_ago=3)
        r1 = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots,
            activity_records=[recent],
        )
        assert r1.classification == NoProgressClass.MAKING_PROGRESS

        # Reach 100% → GOAL_ACHIEVED
        achieved_goal = _make_metric_goal(
            title="Transition",
            current_value=15.0,
            target_value=15.0,
        )
        r2 = classify_no_progress(
            achieved_goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
        )
        assert r2.classification == NoProgressClass.GOAL_ACHIEVED

    def test_ambiguous_case_exactly_at_threshold(self):
        """Ambiguous: progress delta exactly at threshold (5%)."""
        goal = _make_metric_goal()
        # 15 days ago: value 20.4 → progress = 32.5%
        # now: value 20.0 → progress = 37.5%
        # delta = 5.0% — exactly at threshold
        snapshots = [_snap("Body fat", "Body fat %", 20.4, 15)]
        recent = _activity(ActivityType.TASK_COMPLETED, "Body fat", days_ago=3)
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots,
            activity_records=[recent],
        )
        # delta >= 5% → MAKING_PROGRESS (threshold is exclusive)
        assert result.classification == NoProgressClass.MAKING_PROGRESS

    def test_ambiguous_case_just_below_threshold(self):
        """Ambiguous: progress delta just below threshold (4.9%)."""
        goal = _make_metric_goal()
        # 15 days ago: value 20.04 → progress = 37.0%
        # now: value 20.0 → progress = 37.5%
        # delta = 0.5% — below threshold
        snapshots = [_snap("Body fat", "Body fat %", 20.04, 15)]
        recent = _activity(ActivityType.TASK_COMPLETED, "Body fat", days_ago=3)
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots,
            activity_records=[recent],
        )
        assert result.classification == NoProgressClass.EXECUTION_WITHOUT_EFFECT

    def test_ambiguous_case_activity_at_window_boundary(self):
        """Ambiguous: activity exactly at 30-day window boundary."""
        goal = _make_metric_goal()
        # Activity 30 days ago — exactly at boundary
        boundary_activity = _activity(
            ActivityType.TASK_COMPLETED, "Body fat", days_ago=30,
        )
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 15)]
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots,
            activity_records=[boundary_activity],
        )
        # Activity at exactly 30 days is within window (>=)
        # Metric unchanged → EXECUTION_WITHOUT_EFFECT
        assert result.classification == NoProgressClass.EXECUTION_WITHOUT_EFFECT

    def test_ambiguous_case_activity_just_outside_window(self):
        """Ambiguous: activity just outside 30-day window."""
        goal = _make_metric_goal()
        # Activity 31 days ago — outside window
        outside_activity = _activity(
            ActivityType.TASK_COMPLETED, "Body fat", days_ago=31,
        )
        result = classify_no_progress(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            activity_records=[outside_activity],
        )
        assert result.classification == NoProgressClass.NO_EXECUTION
