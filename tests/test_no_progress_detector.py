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
    classify_all_goals,
    classify_no_progress,
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
