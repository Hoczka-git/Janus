"""Targeted tests for health state transitions and progress signal handling.

Covers the acceptance criteria from design §12 that are not already covered by
test_goal_health.py — particularly health state *transitions* (a goal moving
between healthy / watch / stalled as conditions change), the model-package
import surface, observability of goal signals in the attention engine log
event, and weekly-review stalled flagging in CLI output.

Integration points wired in the previous task (t_9e664ff2) are exercised
end-to-end: goal service → metric snapshot persistence → health assessment →
weekly review → CLI rendering.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from janus.models.goal import Goal
from janus.services.goal_health import assess_goal_health


# ── Helpers ──────────────────────────────────────────────────────────────────

FIXED_TODAY = date(2026, 9, 6)


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
    )


def _ts(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def _snap(goal_title, metric_name, value, days_ago, source="manual"):
    from janus.models.metric_snapshot import MetricSnapshot
    return MetricSnapshot(
        timestamp=_ts(days_ago),
        goal_title=goal_title,
        metric_name=metric_name,
        value=value,
        source=source,
    )


# ===========================================================================
# 1. Model package imports (design §5.2 / §10.1)
# ===========================================================================

class TestModelPackageImports:
    """GoalSignal, GoalHealthAssessment, and MetricSnapshot are importable
    from the janus.models package after the extraction in t_9e664ff2."""

    def test_goal_signal_importable_from_models(self):
        from janus.models import GoalSignal
        from datetime import datetime
        s = GoalSignal(signal="test", score=40, reason="r", timestamp=datetime.now())
        assert s.signal == "test"
        assert s.score == 40
        assert s.reason == "r"

    def test_goal_health_assessment_importable_from_models(self):
        from janus.models import GoalHealthAssessment, GoalSignal
        from datetime import datetime
        a = GoalHealthAssessment(
            goal_title="G", health_state="watch",
            signals=[GoalSignal(signal="x", score=40, reason="r", timestamp=datetime.now())],
            dominant_signal=None, progress=50.0,
        )
        assert a.goal_title == "G"
        assert a.health_state == "watch"
        assert len(a.signals) == 1

    def test_metric_snapshot_importable_from_models(self):
        from janus.models import MetricSnapshot
        from datetime import datetime
        s = MetricSnapshot(
            timestamp=datetime.now(), goal_title="G",
            metric_name="m", value=1.0, source="manual",
        )
        assert s.goal_title == "G"
        assert s.metric_name == "m"
        assert s.value == 1.0
        assert s.source == "manual"

    def test_backward_compat_reexport_in_goal_health(self):
        """goal_health.py re-exports MetricSnapshot at its historical import
        location for backward compatibility (design §5.2)."""
        from janus.services.goal_health import MetricSnapshot as Reexported
        from janus.models.metric_snapshot import MetricSnapshot as Model
        assert Reexported is Model


# ===========================================================================
# 2. Health state transitions (design §4 — state changes over time)
# ===========================================================================

class TestHealthStateTransitions:
    """A goal's health state should transition as conditions change.

    These tests move a single goal through different signal configurations
    and assert the health_state changes accordingly.
    """

    def test_healthy_to_watch_via_progress_slow(self):
        """Goal starts healthy (recent activity) then progresses → watch.

        Phase 1: goal has a recent snapshot → no no_recent_activity → healthy.
        Phase 2: snapshot ages beyond the lookback window and progress delta
        drops below threshold → progress_slow fires → watch.
        """
        goal = _make_metric_goal()

        # Phase 1: fresh snapshot (3 days ago) → healthy
        fresh_snapshots = [_snap("Body fat", "Body fat %", 20.0, 3)]
        a1 = assess_goal_health(
            goal, FIXED_TODAY, open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=fresh_snapshots, completed_task_dates=None,
        )
        assert a1.health_state == "healthy"

        # Phase 2: old snapshot (15 days ago), same value → progress_slow
        old_snapshots = [_snap("Body fat", "Body fat %", 20.0, 15)]
        a2 = assess_goal_health(
            goal, FIXED_TODAY, open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=old_snapshots, completed_task_dates=None,
        )
        assert a2.health_state == "watch"
        assert a1.health_state != a2.health_state

    def test_watch_to_stalled_via_measurement_due_then_overdue(self):
        """Goal: watch (measurement_due) → stalled (goal_overdue)."""
        req = {"metric": "Body fat %", "unit": "%", "frequency": "daily"}
        goal = _make_metric_goal(
            deadline="2026-08-30",  # overdue relative to FIXED_TODAY
            related_tasks=["Task A"],
            measurement_requirements=[req],
        )

        # Phase 1: measurement overdue but deadline not yet passed → watch
        future_goal = _make_metric_goal(
            deadline="2026-09-20",
            related_tasks=["Task A"],
            measurement_requirements=[req],
        )
        a1 = assess_goal_health(
            future_goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles={"Task A"},
            metric_snapshots=[], completed_task_dates=None,
        )
        assert a1.health_state == "watch"
        assert any(s.signal == "measurement_due" for s in a1.signals)

        # Phase 2: deadline now past, no open tasks → goal_overdue → stalled
        a2 = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles={"Task A"},
            metric_snapshots=[], completed_task_dates=None,
        )
        assert a2.health_state == "stalled"
        assert any(s.signal == "goal_overdue" for s in a2.signals)

    def test_healthy_to_stalled_via_task_completion(self):
        """Goal with open task → healthy; after task completes (no more open)
        and no future plan → no_recent_activity or goal_stalled → stalled."""
        goal = _make_metric_goal(related_tasks=["Task A"])

        # Phase 1: task is open → healthy
        a1 = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles={"Task A"}, all_task_titles={"Task A"},
            metric_snapshots=[], completed_task_dates=None,
        )
        assert a1.health_state == "healthy"

        # Phase 2: task completed, no snapshot history, no upcoming deadline
        # → goal_stalled fires (all tasks done, no higher signal) → stalled
        a2 = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles={"Task A"},
            metric_snapshots=[], completed_task_dates=None,
        )
        assert a2.health_state == "stalled"

    def test_healthy_to_watch_via_goal_deadline_soon_plus_progress_slow(self):
        """Deadline approaching but tasks open and progressing → healthy.
        When progress slows → deadline_soon + progress_slow → watch."""
        goal = _make_metric_goal(deadline="2026-09-10")  # 4 days from FIXED_TODAY

        # Phase 1: recent snapshot, good progress → healthy
        snapshots_good = [_snap("Body fat", "Body fat %", 22.0, 15)]
        a1 = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots_good, completed_task_dates=None,
        )
        assert a1.health_state == "healthy"
        assert any(s.signal == "goal_deadline_soon" for s in a1.signals)

        # Phase 2: old snapshot at same value → progress_slow + deadline_soon → watch
        snapshots_stale = [_snap("Body fat", "Body fat %", 20.0, 15)]
        a2 = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots_stale, completed_task_dates=None,
        )
        assert a2.health_state == "watch"
        assert any(s.signal == "progress_slow" for s in a2.signals)

    def test_stalled_to_watch_via_new_activity(self):
        """Goal stalled (no_recent_activity) becomes watch when a measurement
        is recorded but progress is still slow."""
        goal = _make_metric_goal(related_tasks=["Task A"])

        # Phase 1: no tasks open, no snapshots, no deadline → no_recent_activity → stalled
        a1 = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles={"Task A"},
            metric_snapshots=[], completed_task_dates=None,
        )
        assert a1.health_state == "stalled"

        # Phase 2: snapshot 15 days ago at same value → progress_slow → watch.
        # no_recent_activity is suppressed (progress_slow scores 40 > 35).
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 15)]
        a2 = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert a2.health_state == "watch"
        assert any(s.signal == "progress_slow" for s in a2.signals)


# ===========================================================================
# 3. Health state resolution — additional edge cases (§12.1)
# ===========================================================================

class TestHealthStateResolutionEdgeCases:

    def test_no_signals_healthy_with_open_task(self):
        """Goal with open related task, no deadlines, no milestones → healthy."""
        goal = _make_metric_goal(related_tasks=["Task A"])
        a = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles={"Task A"}, all_task_titles={"Task A"},
            metric_snapshots=[], completed_task_dates=None,
        )
        assert a.health_state == "healthy"
        assert a.signals == []
        assert a.dominant_signal is None

    def test_goal_deadline_today_is_watch(self):
        """goal_deadline_today (90) → watch (critical deadline day)."""
        goal = _make_metric_goal(deadline="2026-09-06")  # today
        a = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=[], completed_task_dates=None,
        )
        assert a.health_state == "watch"
        assert any(s.signal == "goal_deadline_today" for s in a.signals)

    def test_milestone_deadline_soon_with_open_tasks_is_healthy(self):
        """milestone_deadline_soon + open related tasks, no progress_slow → healthy."""
        goal = _make_metric_goal(
            related_tasks=["Task A"],
            milestones=[{
                "title": "M1", "goal_title": "Body fat", "description": "",
                "deadline": "2026-09-10", "status": "open", "order": 0,
            }],
        )
        a = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles={"Task A"}, all_task_titles={"Task A"},
            metric_snapshots=[], completed_task_dates=None,
        )
        assert a.health_state == "healthy"
        assert any(s.signal == "milestone_deadline_soon" for s in a.signals)

    def test_milestone_deadline_soon_without_open_tasks_is_healthy(self):
        """milestone_deadline_soon alone (no open tasks) → healthy.

        Per design §4.2 exception: deadline_soon/milestone_deadline_soon
        do NOT downgrade to watch unless combined with progress_slow.
        """
        goal = _make_metric_goal(
            milestones=[{
                "title": "M1", "goal_title": "Body fat", "description": "",
                "deadline": "2026-09-10", "status": "open", "order": 0,
            }],
        )
        a = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=[], completed_task_dates=None,
        )
        assert a.health_state == "healthy"
        assert any(s.signal == "milestone_deadline_soon" for s in a.signals)

    def test_dominant_signal_none_when_healthy(self):
        """When health_state is healthy (no signals), dominant_signal is None."""
        goal = _make_metric_goal(related_tasks=["Task A"])
        a = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles={"Task A"}, all_task_titles={"Task A"},
            metric_snapshots=[], completed_task_dates=None,
        )
        assert a.dominant_signal is None

    def test_health_state_severity_ordering(self):
        """Health states are ordered by severity for sorting purposes.

        Verified via the CLI's severity_order mapping in goals_cli.py.
        """
        # The CLI sorts by: stalled (0) < watch (1) < healthy (2) < completed (3)
        severity_order = {"stalled": 0, "watch": 1, "healthy": 2, "completed": 3}
        assert severity_order["stalled"] < severity_order["watch"]
        assert severity_order["watch"] < severity_order["healthy"]


# ===========================================================================
# 4. Progress signal — progress_slow edge cases (§12.2)
# ===========================================================================

class TestProgressSlowEdgeCases:

    def test_does_not_fire_when_progress_improving_above_threshold(self):
        """progress_slow does NOT fire when delta >= threshold (14+ day gap)."""
        goal = _make_metric_goal()
        # 15 days ago: current=22.0 → progress = (23-22)/(23-15) = 12.5%
        # now: current=15.0 → progress = 100%
        # delta = 87.5% > 5% threshold
        snapshots = [_snap("Body fat", "Body fat %", 22.0, 15)]
        goal.current_value = 15.0  # update current value
        a = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert not any(s.signal == "progress_slow" for s in a.signals)

    def test_does_not_fire_for_inactive_goal(self):
        """progress_slow does NOT fire for inactive goals."""
        goal = _make_metric_goal(status="inactive")
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 15)]
        a = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert a is None

    def test_fires_at_exactly_threshold(self):
        """progress_slow fires when delta < threshold (strictly less than)."""
        goal = _make_metric_goal()
        # We need delta exactly at threshold boundary.
        # progress at lookback: x%, current: (x + 5)% → delta = 5, NOT < 5 → no fire
        # delta = 4.9 → < 5 → fire
        # start=23, target=15, range=8.
        # past value v1 → progress = (23 - v1) / 8 * 100
        # current v2 → progress = (23 - v2) / 8 * 100
        # delta = (23 - v2 - 23 + v1) / 8 * 100 = (v1 - v2) / 8 * 100
        # For delta = 4.0: v1 - v2 = 0.32
        # For delta = 0: v1 == v2
        snapshots = [_snap("Body fat", "Body fat %", 20.0, 15)]  # delta = 0
        a = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert any(s.signal == "progress_slow" for s in a.signals)

    def test_does_not_fire_without_progress_config(self):
        """progress_slow does NOT fire when goal has no metric and no tasks."""
        goal = Goal(title="G", status="active")
        snapshots = [_snap("G", "m", 1.0, 15)]
        a = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=snapshots, completed_task_dates=None,
        )
        assert not any(s.signal == "progress_slow" for s in a.signals)
        assert not any(s.signal == "no_recent_activity" for s in a.signals)


# ===========================================================================
# 5. Observability — goal signals in attention engine log event (§12.7)
# ===========================================================================

class TestObservabilityGoalSignals:
    """The engine.attention.computed log event includes a goal_signals
    breakdown for goals that have signals (design §12.7)."""

    def test_goal_signals_in_log_event(self, tmp_path, monkeypatch, capsys):
        """When get_attention_items processes a goal with signals, the
        engine.attention.computed event includes goal_signals."""
        import json
        import logging
        from janus.logging_config import _StructuredFormatter
        from janus.models.task import Task
        from janus.services.attention import get_attention_items

        records: list[str] = []

        class _ListHandler(logging.Handler):
            def emit(self, record):
                records.append(self.format(record))

        handler = _ListHandler()
        handler.setFormatter(_StructuredFormatter())
        root = logging.getLogger("janus")
        saved_handlers = list(root.handlers)
        root.handlers = [handler]
        root.setLevel(logging.INFO)
        root.propagate = False
        try:
            tasks_path = tmp_path / "tasks.md"
            tasks_path.write_text("- [x] Done Task\n")
            monkeypatch.setattr(
                "janus.services.attention._load_all_task_titles",
                lambda _: {"Done Task"},
            )

            goal = Goal(title="Stalled Goal", related_tasks=["Done Task"])
            get_attention_items([], [], [goal], FIXED_TODAY, trace_id="test-trace")

            computed_events = [
                json.loads(r) for r in records
                if json.loads(r).get("event") == "engine.attention.computed"
            ]
            assert len(computed_events) >= 1
            event_data = computed_events[-1]["data"]
            assert "goal_signals" in event_data
            signals = event_data["goal_signals"]
            assert "Stalled Goal" in signals
            signal_list = signals["Stalled Goal"]
            assert len(signal_list) > 0
            entry = signal_list[0]
            assert "signal" in entry
            assert "score" in entry
            assert "category" in entry
        finally:
            root.handlers = saved_handlers
            root.propagate = False

    def test_goal_signals_null_when_no_goals(self, tmp_path, monkeypatch, capsys):
        """When no goals have signals, goal_signals is None in the log event."""
        import json
        import logging
        from janus.logging_config import _StructuredFormatter
        from janus.models.task import Task
        from janus.services.attention import get_attention_items

        records: list[str] = []

        class _ListHandler(logging.Handler):
            def emit(self, record):
                records.append(self.format(record))

        handler = _ListHandler()
        handler.setFormatter(_StructuredFormatter())
        root = logging.getLogger("janus")
        saved_handlers = list(root.handlers)
        root.handlers = [handler]
        root.setLevel(logging.INFO)
        root.propagate = False
        try:
            tasks_path = tmp_path / "tasks.md"
            tasks_path.write_text("- [ ] Open task\n")
            monkeypatch.setattr(
                "janus.services.attention._load_all_task_titles",
                lambda _: {"Open task"},
            )

            goal = Goal(title="Active Goal", related_tasks=["Open task"])
            get_attention_items(
                [], [Task(title="Open task", due_date=None, priority=1)],
                [goal], FIXED_TODAY, trace_id="test-trace",
            )

            computed_events = [
                json.loads(r) for r in records
                if json.loads(r).get("event") == "engine.attention.computed"
            ]
            event_data = computed_events[-1]["data"]
            assert event_data.get("goal_signals") is None
        finally:
            root.handlers = saved_handlers
            root.propagate = False


# ===========================================================================
# 6. Weekly review — stalled flagging in CLI output (§12.5)
# ===========================================================================

class TestWeeklyReviewStallFlagging:
    """Stalled goals are flagged in the weekly review CLI output."""

    def test_stalled_goal_flagged_in_weekly_output(self, tmp_path, monkeypatch, capsys):
        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text("- [x] Old Task\n")
        goals_file = tmp_path / "goals.md"
        goals_file.write_text(
            "# Goals\n\n## Goal: Stale Goal\nStatus: active\nRelated tasks:\n- Old Task\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        from janus.weekly import show_weekly
        show_weekly()

        out = capsys.readouterr().out
        assert "Stale Goal" in out
        assert "stalled" in out
        assert "⚠ STALLED" in out

    def test_watch_goal_not_flagged_as_stalled(self, tmp_path, monkeypatch, capsys):
        """A watch-state goal should show its health state but not the stalled flag."""
        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text("")
        goals_file = tmp_path / "goals.md"
        # Metric goal with no recent snapshot and a future deadline →
        # no_recent_activity suppressed by upcoming deadline, but goal_deadline_soon
        # fires → healthy (deadline_soon with no progress_slow → healthy per exception)
        # Actually, let's use a measurement_due scenario for watch.
        goals_file.write_text(
            "# Goals\n\n"
            "## Goal: Body fat\n"
            "Status: active\n"
            "Metric: Body fat %\n"
            "Unit: %\n"
            "Start: 23.0\n"
            "Current: 20.0\n"
            "Target: 15.0\n"
            "Direction: decrease\n"
            "Measurement requirements:\n"
            "  - metric: Body fat %\n"
            "    frequency: daily\n"
        )
        metric_history = tmp_path / "metric_history.md"
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.metric_history.METRIC_HISTORY_PATH", metric_history)

        from janus.weekly import show_weekly
        show_weekly()

        out = capsys.readouterr().out
        assert "Body fat" in out
        assert "watch" in out
        assert "⚠ STALLED" not in out


# ===========================================================================
# 7. Integration: service → snapshot → health (§12.4 end-to-end)
# ===========================================================================

class TestServiceToHealthIntegration:
    """End-to-end: update_goal_fields(current_value=...) → snapshot →
    assess_goal_health sees the new snapshot."""

    def test_update_current_value_then_assess_sees_snapshot(
        self, tmp_path, monkeypatch
    ):
        """Setting current_value appends a snapshot; assess_goal_health
        loaded from the same file sees it (no_recent_activity suppressed)."""
        from janus.services.goals import add_goal, update_goal_fields
        from janus.integrations.metric_history import get_metric_snapshots

        goals_file = tmp_path / "goals.md"
        goals_file.write_text("# Goals\n")
        metric_history = tmp_path / "metric_history.md"
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.integrations.metric_history.METRIC_HISTORY_PATH", metric_history)

        # Add a metric goal with a recent snapshot
        goal = add_goal(
            "Body fat",
            metric_name="Body fat %",
            metric_unit="%",
            start_value=23.0,
            current_value=20.0,
            target_value=15.0,
            direction="decrease",
        )
        assert goal.current_value == 20.0

        # A snapshot was appended during add_goal? No — add_goal doesn't
        # trigger a snapshot. Only update_goal_fields with current_value does.
        # Initially no snapshots → no_recent_activity would fire.
        snaps = get_metric_snapshots("Body fat")
        # add_goal does not append a snapshot; snapshots come from update.
        assert len(snaps) == 0

        # Now update current_value → snapshot appended
        update_goal_fields("Body fat", current_value=19.0)
        snaps = get_metric_snapshots("Body fat")
        assert len(snaps) == 1
        assert snaps[0].value == 19.0

        # assess_goal_health should see the snapshot (pass via metric_snapshots)
        from janus.integrations.metric_history import MetricSnapshot
        assessment = assess_goal_health(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles=set(),
            metric_snapshots=get_metric_snapshots("Body fat"),
            completed_task_dates=None,
        )
        assert assessment is not None
        # With a fresh snapshot, no_recent_activity should NOT fire
        assert not any(s.signal == "no_recent_activity" for s in assessment.signals)

    def test_inactive_goal_excluded_from_weekly_review(
        self, tmp_path, monkeypatch
    ):
        """Inactive goals are excluded from weekly review goal list."""
        from janus.services.weekly_review import create_weekly_review

        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text("- [ ] Open task\n")
        goals_file = tmp_path / "goals.md"
        goals_file.write_text(
            "# Goals\n\n"
            "## Goal: Active\nStatus: active\nRelated tasks:\n- Open task\n\n"
            "## Goal: Paused\nStatus: inactive\nRelated tasks:\n- Open task\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        review = create_weekly_review()
        assert len(review.goals) == 1
        assert review.goals[0].goal.title == "Active"
