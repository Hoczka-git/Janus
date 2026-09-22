"""Tests for the Goal Integrity Audit service and CLI.

Spec: docs/design/goal_integrity_audit.md §12

All tests use direct function calls (no CLI, no persistence) for the service-layer
tests, and monkeypatched fixtures for CLI tests.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from janus.models.goal import Goal
from janus.models.task import Task
from janus.models.metric_snapshot import MetricSnapshot
from janus.models.goal_integrity_report import GoalIntegrityReport, GoalIntegrityIssue
from janus.services.goal_integrity import (
    audit_goal_integrity,
    GOAL_WITHOUT_TASKS,
    UNKNOWN_GOAL_REFERENCE,
    INVALID_METRIC,
    STALE_ACTIVITY,
)
from janus.services.goal_integrity import INACTIVITY_WINDOW_DAYS


# ── Shared helpers ────────────────────────────────────────────────────────────

NOW = datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)


def _metric_goal(
    title,
    *,
    recent_activity=None,
    related_tasks=None,
):
    """Build an active goal with a complete, valid metric configuration."""
    return Goal(
        title=title,
        status="active",
        metric_name="Body fat %",
        metric_unit="%",
        start_value=23.0,
        current_value=20.0,
        target_value=15.0,
        direction="decrease",
        related_tasks=related_tasks or [],
        recent_activity=recent_activity,
    )


def _task_goal(title, related=None):
    """Build an active goal that uses the task-based path (no metric)."""
    return Goal(
        title=title,
        status="active",
        related_tasks=related or [],
    )


def _task(title, goal_ref=None):
    """Build a Task, optionally referencing *goal_ref* via extra_metadata."""
    return Task(
        title=title,
        extra_metadata=[f"goal: {goal_ref}"] if goal_ref else None,
    )


# ── 1. Healthy goals/tasks ────────────────────────────────────────────────────

class TestHealthyGoals:
    def test_healthy_metric_goal_no_issues(self):
        """§12(1): A fully-valid metric goal with recent activity is clean."""
        goal = _metric_goal(
            "Lean",
            recent_activity=[
                {"task_id": "t1", "completed_at": NOW.isoformat()},
            ],
        )
        report = audit_goal_integrity(goals=[goal], tasks=[], now=NOW)
        assert report.goals_checked == 1
        assert report.error_count == 0
        assert report.warning_count == 0
        assert report.issues == []

    def test_healthy_task_goal_with_open_task(self):
        """§12(1): An active task-based goal with an open related task is healthy."""
        goal = _task_goal("Japan trip", related=["Book flights"])
        task = _task("Book flights")
        report = audit_goal_integrity(goals=[goal], tasks=[task], now=NOW)
        assert report.error_count == 0
        assert report.warning_count == 0
        assert report.issues == []

    def test_healthy_checks_present_for_metric_goal(self):
        """Healthy goals produce info-level healthy checks."""
        goal = _metric_goal(
            "Lean",
            recent_activity=[{"task_id": "t1", "completed_at": NOW.isoformat()}],
        )
        report = audit_goal_integrity(goals=[goal], tasks=[], now=NOW)
        assert len(report.healthy_checks) >= 1


# ── 2. Active goal without tasks ──────────────────────────────────────────────

class TestGoalWithoutTasks:
    def test_active_goal_no_tasks_warns(self):
        """§12(2): An active goal with no related tasks → GOAL_WITHOUT_TASKS warning."""
        goal = _task_goal("Lonely goal", related=[])
        report = audit_goal_integrity(goals=[goal], tasks=[], now=NOW)
        assert report.warning_count == 1
        issue = report.issues[0]
        assert issue.code == GOAL_WITHOUT_TASKS
        assert issue.severity == "warning"
        assert issue.goal_id == "Lonely goal"

    def test_completed_goal_no_tasks_not_flagged(self):
        """§6.1: Completed goals are not flagged for GOAL_WITHOUT_TASKS."""
        goal = Goal(
            title="Done goal",
            status="completed",
            related_tasks=[],
        )
        report = audit_goal_integrity(goals=[goal], tasks=[], now=NOW)
        assert report.issues == []

    def test_inactive_goal_no_tasks_not_flagged(self):
        """§6.1: Inactive goals are not flagged for GOAL_WITHOUT_TASKS."""
        goal = Goal(
            title="Paused goal",
            status="inactive",
            related_tasks=[],
        )
        report = audit_goal_integrity(goals=[goal], tasks=[], now=NOW)
        assert report.issues == []


# ── 3. Task referencing an unknown goal ──────────────────────────────────────

class TestUnknownGoalReference:
    def test_task_refs_unknown_goal_errors(self):
        """§12(3): A task referencing a non-existent goal → UNKNOWN_GOAL_REFERENCE error."""
        goal = _task_goal("Real goal", related=["Real task"])
        task = _task("Ghost task", goal_ref="Ghost goal")
        report = audit_goal_integrity(goals=[goal], tasks=[task], now=NOW)
        errs = [i for i in report.issues if i.code == UNKNOWN_GOAL_REFERENCE]
        assert len(errs) == 1
        assert errs[0].severity == "error"
        assert errs[0].goal_id == "Ghost goal"
        assert errs[0].task_id == "Ghost task"

    def test_task_refs_existing_goal_no_issue(self):
        """§12(1): A task referencing a real goal is healthy (no UNKNOWN_GOAL_REFERENCE)."""
        goal = _task_goal("Real goal", related=["Real task"])
        task = _task("Real task", goal_ref="Real goal")
        report = audit_goal_integrity(goals=[goal], tasks=[task], now=NOW)
        assert not any(i.code == UNKNOWN_GOAL_REFERENCE for i in report.issues)


# ── 4. Invalid metric ─────────────────────────────────────────────────────────

class TestInvalidMetric:
    def test_metric_name_without_values_errors(self):
        """§12(4): A goal with metric_name but missing required fields → INVALID_METRIC."""
        goal = Goal(
            title="Bad metric",
            status="active",
            metric_name="Foo",
            start_value=1,
            target_value=2,
            direction=None,  # missing all of: direction
        )
        report = audit_goal_integrity(goals=[goal], tasks=[], now=NOW)
        errs = [i for i in report.issues if i.code == INVALID_METRIC]
        assert len(errs) == 1
        assert errs[0].severity == "error"
        assert errs[0].goal_id == "Bad metric"

    def test_metric_no_metric_name_no_issue(self):
        """§6.3: A goal with no metric_name at all should not get INVALID_METRIC."""
        goal = _task_goal("No metric goal")
        report = audit_goal_integrity(goals=[goal], tasks=[], now=NOW)
        assert not any(i.code == INVALID_METRIC for i in report.issues)

    def test_inconsistent_direction_errors(self):
        """INVALID_METRIC also covers direction/value inconsistency
        (e.g. 'increase' with target < start)."""
        goal = Goal(
            title="Dir conflict",
            status="active",
            metric_name="Savings",
            start_value=100,
            current_value=50,
            target_value=50,  # target < start but direction=increase
            direction="increase",
        )
        report = audit_goal_integrity(goals=[goal], tasks=[], now=NOW)
        errs = [i for i in report.issues if i.code == INVALID_METRIC]
        assert len(errs) == 1


# ── 5. Stale activity ────────────────────────────────────────────────────────

class TestStaleActivity:
    def test_stale_activity_warns(self):
        """§12(5): An active goal with old recent_activity → STALE_ACTIVITY warning."""
        old_ts = NOW - timedelta(days=60)
        goal = _metric_goal(
            "Stale",
            recent_activity=[
                {"task_id": "t1", "completed_at": old_ts.isoformat()},
            ],
        )
        report = audit_goal_integrity(goals=[goal], tasks=[], now=NOW)
        errs = [i for i in report.issues if i.code == STALE_ACTIVITY]
        assert len(errs) == 1
        assert errs[0].severity == "warning"
        assert errs[0].goal_id == "Stale"

    def test_recent_activity_not_stale(self):
        """§12(1): Recent activity within the window → no STALE_ACTIVITY."""
        goal = _metric_goal(
            "Fresh",
            recent_activity=[
                {"task_id": "t1", "completed_at": NOW.isoformat()},
            ],
        )
        report = audit_goal_integrity(goals=[goal], tasks=[], now=NOW)
        assert not any(i.code == STALE_ACTIVITY for i in report.issues)

    def test_no_activity_history_not_stale(self):
        """§6.4: A goal with no activity at all is not flagged as stale
        (stale implies activity once existed)."""
        goal = _metric_goal("No history", recent_activity=[])
        report = audit_goal_integrity(goals=[goal], tasks=[], now=NOW)
        assert not any(i.code == STALE_ACTIVITY for i in report.issues)


# ── 6. Multiple simultaneous issue types ─────────────────────────────────────

class TestMultipleIssues:
    def test_multiple_issue_types(self):
        """§12(6): A report can contain multiple issue types at once."""
        goals = [
            _task_goal("Lonely"),           # GOAL_WITHOUT_TASKS
            Goal(                           # INVALID_METRIC
                title="Bad metric",
                status="active",
                metric_name="Foo",
                start_value=1,
                target_value=None,
                direction=None,
                current_value=None,
            ),
            _metric_goal(                   # STALE_ACTIVITY
                "Stale",
                recent_activity=[
                    {"task_id": "t", "completed_at": (NOW - timedelta(days=60)).isoformat()},
                ],
            ),
        ]
        tasks = [_task("Ghost task", goal_ref="Nonexistent goal")]  # UNKNOWN_GOAL_REFERENCE
        report = audit_goal_integrity(goals=goals, tasks=tasks, now=NOW)

        codes = {i.code for i in report.issues}
        assert codes == {
            GOAL_WITHOUT_TASKS,
            INVALID_METRIC,
            STALE_ACTIVITY,
            UNKNOWN_GOAL_REFERENCE,
        }
        assert report.error_count == 2  # INVALID_METRIC + UNKNOWN_GOAL_REFERENCE
        # GOAL_WITHOUT_TASKS fires for both "Lonely" (no metric) and "Bad metric"
        # (invalid metric → task-based path, no tasks).
        assert report.warning_count == 3  # GOAL_WITHOUT_TASKS x2 + STALE_ACTIVITY


# ── 7. Deterministic output ───────────────────────────────────────────────────

class TestDeterminism:
    def test_same_input_same_output(self):
        """§12(7): The audit produces identical output for identical input."""
        goal = _metric_goal(
            "Stale",
            recent_activity=[
                {"task_id": "t1", "completed_at": (NOW - timedelta(days=60)).isoformat()},
            ],
        )
        task = _task("Ghost", goal_ref="Nope")
        run1 = audit_goal_integrity(goals=[goal], tasks=[task], now=NOW)
        run2 = audit_goal_integrity(goals=[goal], tasks=[task], now=NOW)
        assert run1.to_dict() == run2.to_dict()


# ── 8. Explicit `now` handling ────────────────────────────────────────────────

class TestExplicitNow:
    def test_now_affects_stale_detection(self):
        """§12(8): The same goal/data yields different results depending on `now`."""
        old_ts = NOW - timedelta(days=60)
        goal = _metric_goal(
            "Stale",
            recent_activity=[
                {"task_id": "t1", "completed_at": old_ts.isoformat()},
            ],
        )
        # With now=NOW (60 days after activity) → stale
        report_stale = audit_goal_integrity(goals=[goal], tasks=[], now=NOW)
        assert any(i.code == STALE_ACTIVITY for i in report_stale.issues)

        # With now just after activity → not stale
        soon = old_ts + timedelta(days=1)
        report_fresh = audit_goal_integrity(goals=[goal], tasks=[], now=soon)
        assert not any(i.code == STALE_ACTIVITY for i in report_fresh.issues)


# ── Service model tests ───────────────────────────────────────────────────────

class TestReportModel:
    def test_report_counts(self):
        report = GoalIntegrityReport(goals_checked=3, tasks_checked=5)
        assert report.error_count == 0
        assert report.warning_count == 0
        assert report.info_count == 0
        assert report.has_errors is False

    def test_report_to_dict_keys(self):
        report = GoalIntegrityReport(goals_checked=1, tasks_checked=1, evaluated_at=NOW)
        d = report.to_dict()
        assert set(d.keys()) == {
            "goals_checked", "tasks_checked", "issues", "healthy_checks",
            "error_count", "warning_count", "info_count", "evaluated_at",
        }

    def test_issue_to_dict(self):
        issue = GoalIntegrityIssue(
            code="TEST", severity="error", goal_id="g1", task_id="t1",
            message="msg", details={"k": "v"},
        )
        d = issue.to_dict()
        assert d == {
            "code": "TEST", "severity": "error", "goal_id": "g1",
            "task_id": "t1", "message": "msg", "details": {"k": "v"},
        }


# ── CLI tests ─────────────────────────────────────────────────────────────────

def _setup_cli_fixtures(tmp_path, monkeypatch, goals_content, tasks_content):
    """Write goals.md and tasks.md into tmp_path and patch the integration paths."""
    goals_file = tmp_path / "goals.md"
    tasks_file = tmp_path / "tasks.md"
    goals_file.write_text(goals_content)
    tasks_file.write_text(tasks_content)
    monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
    monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
    monkeypatch.setattr("janus.services.goals.GOALS_PATH", goals_file)


class TestGoalAuditCLI:
    def test_human_readable_output(self, tmp_path, monkeypatch, capsys):
        """§12(9): Human-readable CLI output contains expected sections."""
        _setup_cli_fixtures(
            tmp_path, monkeypatch,
            "# Goals\n",
            "- [ ] Test task\n",
        )
        from janus.goals_cli import handle_goal_audit
        handle_goal_audit([])
        captured = capsys.readouterr()
        assert "Goal Integrity Audit" in captured.out
        assert "Goals checked:" in captured.out
        assert "Tasks checked:" in captured.out
        assert "Errors:" in captured.out
        assert "Warnings:" in captured.out
        assert "Info:" in captured.out

    def test_json_output(self, tmp_path, monkeypatch, capsys):
        """§12(10): JSON CLI output is valid machine-readable JSON."""
        _setup_cli_fixtures(
            tmp_path, monkeypatch,
            "# Goals\n",
            "- [ ] Test task | goal: Nonexistent goal\n",
        )
        from janus.goals_cli import handle_goal_audit
        handle_goal_audit(["--json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["goals_checked"] >= 0
        assert "issues" in data
        assert "error_count" in data
        assert "warning_count" in data

    def test_exit_code_with_errors(self, tmp_path, monkeypatch, capsys):
        """§12(11): CLI exits non-zero when error-severity issues are present."""
        _setup_cli_fixtures(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: Real goal\nStatus: active\n",
            "- [ ] Ghost task | goal: Ghost goal\n",
        )
        from janus.goals_cli import handle_goal_audit
        with pytest.raises(SystemExit) as exc:
            handle_goal_audit([])
        assert exc.value.code != 0

    def test_exit_code_with_warnings_only(self, tmp_path, monkeypatch, capsys):
        """§12(12): CLI exits 0 when only warnings (no errors) are present."""
        # An active goal with no related tasks → GOAL_WITHOUT_TASKS warning only.
        _setup_cli_fixtures(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: Lonely goal\nStatus: active\n",
            "- [ ] Some task\n",
        )
        from janus.goals_cli import handle_goal_audit
        # Should NOT raise SystemExit (warnings don't fail)
        handle_goal_audit([])

    def test_no_goals_no_issues(self, tmp_path, monkeypatch, capsys):
        """CLI with empty goals file → no issues, exit 0."""
        _setup_cli_fixtures(
            tmp_path, monkeypatch,
            "# Goals\n",
            "- [ ] Test task\n",
        )
        from janus.goals_cli import handle_goal_audit
        handle_goal_audit([])
        captured = capsys.readouterr()
        assert "No issues found." in captured.out
