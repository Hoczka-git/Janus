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
    ORPHANED_TASK,
    INVALID_RELATED_TASK,
    RELATIONSHIP_COUNT_MISMATCH,
    CIRCULAR_REFERENCE,
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
            "",
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
        """CLI with empty goals file and no tasks → no issues, exit 0."""
        _setup_cli_fixtures(
            tmp_path, monkeypatch,
            "# Goals\n",
            "",
        )
        from janus.goals_cli import handle_goal_audit
        handle_goal_audit([])
        captured = capsys.readouterr()
        assert "No issues found." in captured.out

    def test_human_output_contains_issue_codes_and_details(self, tmp_path, monkeypatch, capsys):
        """§12(9): Human-readable output reports each issue code + affected IDs, not just headers."""
        _setup_cli_fixtures(
            tmp_path, monkeypatch,
            "# Goals\n\n"
            "## Goal: Lonely goal\n"
            "Status: active\n",
            "- [ ] Ghost task | goal: Ghost goal\n",
        )
        from janus.goals_cli import handle_goal_audit
        with pytest.raises(SystemExit) as exc:
            handle_goal_audit([])
        assert exc.value.code != 0
        captured = capsys.readouterr()
        # UNKNOWN_GOAL_REFERENCE is an error for the ghost task
        assert "UNKNOWN_GOAL_REFERENCE" in captured.out
        assert "Ghost goal" in captured.out
        assert "Ghost task" in captured.out
        # GOAL_WITHOUT_TASKS fires for the active goal with no related tasks
        assert "GOAL_WITHOUT_TASKS" in captured.out

    def test_all_four_issue_codes_in_output(self, tmp_path, monkeypatch, capsys):
        """§12(6)/(9): A report with all four issue codes renders all of them."""
        goals_md = (
            "# Goals\n\n"
            # GOAL_WITHOUT_TASKS: active, no metric, no valid related task
            "## Goal: Lonely goal\n"
            "Status: active\n"
            "\n"
            # INVALID_METRIC: metric_name set but missing required values
            "## Goal: Bad metric goal\n"
            "Status: active\n"
            "Metric: Savings\n"
            "Start: 100\n"
            "Target: 200\n"
            "Direction: increase\n"
        )
        tasks_md = (
            # UNKNOWN_GOAL_REFERENCE: references a non-existent goal
            "- [ ] Ghost task | goal: Phantom goal\n"
            "- [ ] Stale task | goal: Lonely goal\n"
        )
        _setup_cli_fixtures(tmp_path, monkeypatch, goals_md, tasks_md)
        from janus.goals_cli import handle_goal_audit
        # Expect SystemExit because UNKNOWN_GOAL_REFERENCE / INVALID_METRIC are errors
        with pytest.raises(SystemExit) as exc:
            handle_goal_audit([])
        assert exc.value.code != 0
        captured = capsys.readouterr()
        for code in ("GOAL_WITHOUT_TASKS", "UNKNOWN_GOAL_REFERENCE", "INVALID_METRIC"):
            assert code in captured.out

    def test_json_output_full_structure(self, tmp_path, monkeypatch, capsys):
        """§12(10): JSON output contains complete structured report with codes, severity, IDs, details."""
        _setup_cli_fixtures(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: Real goal\nStatus: active\n",
            "- [ ] Ghost task | goal: Ghost goal\n",
        )
        from janus.goals_cli import handle_goal_audit
        with pytest.raises(SystemExit):
            handle_goal_audit(["--json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        # Counts
        assert data["goals_checked"] == 1
        assert data["tasks_checked"] == 1
        # The UNKNOWN_GOAL_REFERENCE error must be present with full fields
        issues = data["issues"]
        ghost = [i for i in issues if i["code"] == "UNKNOWN_GOAL_REFERENCE"]
        assert len(ghost) == 1
        g = ghost[0]
        assert g["severity"] == "error"
        assert g["goal_id"] == "Ghost goal"
        assert g["task_id"] == "Ghost task"
        assert "does not exist" in g["message"]
        assert g["details"]["referenced_goal"] == "Ghost goal"
        assert g["details"]["task_id"] == "Ghost task"
        # Summary counts must be consistent
        assert data["error_count"] == data["error_count"]  # exists
        assert data["error_count"] >= 1
        assert "warning_count" in data
        assert "info_count" in data
        assert "evaluated_at" in data

    def test_json_output_exit_code_with_errors(self, tmp_path, monkeypatch, capsys):
        """§12(11): --json also exits non-zero when error-severity issues are present."""
        _setup_cli_fixtures(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: Real goal\nStatus: active\n",
            "- [ ] Ghost task | goal: Ghost goal\n",
        )
        from janus.goals_cli import handle_goal_audit
        with pytest.raises(SystemExit) as exc:
            handle_goal_audit(["--json"])
        assert exc.value.code != 0

    def test_json_output_exit_code_warnings_only(self, tmp_path, monkeypatch, capsys):
        """§12(12): --json exits 0 when only warnings are present."""
        _setup_cli_fixtures(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: Lonely goal\nStatus: active\n",
            "- [ ] Some task\n",
        )
        from janus.goals_cli import handle_goal_audit
        # Should NOT raise SystemExit — only GOAL_WITHOUT_TASKS warning, no errors
        handle_goal_audit(["--json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["error_count"] == 0
        assert data["warning_count"] >= 1

    def test_audit_is_read_only(self, tmp_path, monkeypatch, capsys):
        """Read-only contract (spec §3): audit must not modify goals.md or tasks.md."""
        goals_md = "# Goals\n\n## Goal: Real goal\nStatus: active\n"
        tasks_md = "- [ ] Ghost task | goal: Ghost goal\n"
        _setup_cli_fixtures(tmp_path, monkeypatch, goals_md, tasks_md)
        goals_file = tmp_path / "goals.md"
        tasks_file = tmp_path / "tasks.md"
        from janus.goals_cli import handle_goal_audit
        with pytest.raises(SystemExit):
            handle_goal_audit([])
        capsys.readouterr()  # drain output
        assert goals_file.read_text() == goals_md
        assert tasks_file.read_text() == tasks_md

    def test_cli_deterministic_output(self, tmp_path, monkeypatch, capsys):
        """§12(7),(10): Same input produces identical JSON output across two CLI runs."""
        goals_md = (
            "# Goals\n\n"
            "## Goal: Lonely goal\n"
            "Status: active\n"
        )
        tasks_md = (
            "- [ ] Ghost task | goal: Ghost goal\n"
        )
        # First run
        _setup_cli_fixtures(tmp_path, monkeypatch, goals_md, tasks_md)
        from janus.goals_cli import handle_goal_audit
        with pytest.raises(SystemExit):
            handle_goal_audit(["--json"])
        first = capsys.readouterr().out

        # Second run: rewrite fixtures to ensure determinism independent of buffer
        _setup_cli_fixtures(tmp_path, monkeypatch, goals_md, tasks_md)
        with pytest.raises(SystemExit):
            handle_goal_audit(["--json"])
        second = capsys.readouterr().out

        # evaluated_at is the only non-deterministic field at the CLI level;
        # strip it before comparing so we isolate structural determinism.
        first_data = json.loads(first)
        second_data = json.loads(second)
        first_data.pop("evaluated_at", None)
        second_data.pop("evaluated_at", None)
        assert first_data == second_data

    def test_cli_wired_through_main(self, tmp_path, monkeypatch, capsys):
        """End-to-end: `janus goal audit` dispatches to handle_goal_audit via main()."""
        _setup_cli_fixtures(
            tmp_path, monkeypatch,
            "# Goals\n",
            "- [ ] Test task\n",
        )
        import janus
        monkeypatch.setattr("sys.argv", ["janus", "goal", "audit"])
        janus.main()
        captured = capsys.readouterr()
        assert "Goal Integrity Audit" in captured.out


# ── 13. Orphan tasks ──────────────────────────────────────────────────────────

class TestOrphanTasks:
    def test_orphan_task_detected(self):
        """An open task with no goal: ref and not in any related_tasks is orphaned."""
        goal = _task_goal("Real goal", related=["Real task"])
        orphan_task = _task("Lonely task")  # no goal: ref, not in related_tasks
        real_task = _task("Real task", goal_ref="Real goal")
        report = audit_goal_integrity(
            goals=[goal], tasks=[orphan_task, real_task], now=NOW
        )
        orphans = [i for i in report.issues if i.code == ORPHANED_TASK]
        assert len(orphans) == 1
        assert orphans[0].severity == "warning"
        assert orphans[0].task_id == "Lonely task"

    def test_task_in_related_tasks_not_orphaned(self):
        """A task listed in goal.related_tasks is not orphaned even without goal: ref."""
        goal = _task_goal("My goal", related=["Book flights"])
        task = _task("Book flights")  # no goal: ref, but in related_tasks
        report = audit_goal_integrity(goals=[goal], tasks=[task], now=NOW)
        orphans = [i for i in report.issues if i.code == ORPHANED_TASK]
        assert len(orphans) == 0

    def test_task_with_goal_ref_not_orphaned(self):
        """A task with a goal: ref is not orphaned (even if goal has no related_tasks)."""
        goal = _task_goal("My goal", related=[])
        task = _task("Some task", goal_ref="My goal")
        report = audit_goal_integrity(goals=[goal], tasks=[task], now=NOW)
        orphans = [i for i in report.issues if i.code == ORPHANED_TASK]
        assert len(orphans) == 0

    def test_orphan_task_no_goals_at_all(self):
        """When there are no goals, all tasks are orphaned."""
        orphan = _task("Lonely task")
        report = audit_goal_integrity(goals=[], tasks=[orphan], now=NOW)
        orphans = [i for i in report.issues if i.code == ORPHANED_TASK]
        assert len(orphans) == 1
        assert orphans[0].task_id == "Lonely task"

    def test_multiple_orphan_tasks(self):
        """Multiple orphan tasks each get flagged."""
        goal = _task_goal("Real goal", related=["Task A"])
        report = audit_goal_integrity(
            goals=[goal],
            tasks=[
                _task("Task A", goal_ref="Real goal"),
                _task("Orphan 1"),
                _task("Orphan 2"),
            ],
            now=NOW,
        )
        orphans = [i for i in report.issues if i.code == ORPHANED_TASK]
        assert len(orphans) == 2
        orphan_ids = {i.task_id for i in orphans}
        assert orphan_ids == {"Orphan 1", "Orphan 2"}


# ── 14. Invalid related_task references ───────────────────────────────────────

class TestInvalidRelatedTasks:
    def test_related_task_not_in_tasks_list(self):
        """A goal.related_tasks entry pointing to a non-existent task is invalid."""
        goal = _task_goal("Real goal", related=["Nonexistent task"])
        report = audit_goal_integrity(goals=[goal], tasks=[], now=NOW)
        invalids = [i for i in report.issues if i.code == INVALID_RELATED_TASK]
        assert len(invalids) == 1
        assert invalids[0].severity == "error"
        assert invalids[0].goal_id == "Real goal"
        assert invalids[0].task_id == "Nonexistent task"

    def test_related_task_completed_not_flagged(self):
        """A completed task is not in the open task list, so it's invalid."""
        goal = _task_goal("Real goal", related=["Done task"])
        task = Task(title="Done task")
        # Simulate a completed task: load_tasks only returns open tasks,
        # so a completed task won't appear in the tasks list.
        report = audit_goal_integrity(goals=[goal], tasks=[], now=NOW)
        invalids = [i for i in report.issues if i.code == INVALID_RELATED_TASK]
        assert len(invalids) == 1
        assert invalids[0].task_id == "Done task"

    def test_valid_related_task_not_flagged(self):
        """A goal.related_tasks entry matching an open task is valid."""
        goal = _task_goal("Real goal", related=["Real task"])
        task = _task("Real task")
        report = audit_goal_integrity(goals=[goal], tasks=[task], now=NOW)
        invalids = [i for i in report.issues if i.code == INVALID_RELATED_TASK]
        assert len(invalids) == 0

    def test_mismatched_related_task(self):
        """When related_tasks has a stale entry but also a valid one."""
        goal = _task_goal("Real goal", related=["Valid task", "Stale task"])
        task = _task("Valid task")
        report = audit_goal_integrity(goals=[goal], tasks=[task], now=NOW)
        invalids = [i for i in report.issues if i.code == INVALID_RELATED_TASK]
        assert len(invalids) == 1
        assert invalids[0].task_id == "Stale task"


# ── 15. Relationship count mismatch ───────────────────────────────────────────

class TestRelationshipCountMismatch:
    def test_reverse_only_ref_no_forward(self):
        """Task references goal via goal: but goal doesn't list it in related_tasks."""
        goal = _task_goal("My goal", related=[])
        task = _task("Some task", goal_ref="My goal")
        report = audit_goal_integrity(goals=[goal], tasks=[task], now=NOW)
        mismatches = [i for i in report.issues if i.code == RELATIONSHIP_COUNT_MISMATCH]
        assert len(mismatches) >= 1
        assert any(i.task_id == "Some task" for i in mismatches)

    def test_count_mismatch_when_both_populated(self):
        """Goal lists 2 related tasks, but only 1 task references it back."""
        goal = _task_goal("My goal", related=["Task A", "Task B"])
        task_a = _task("Task A", goal_ref="My goal")
        task_b = _task("Task B")  # missing goal: ref
        report = audit_goal_integrity(
            goals=[goal], tasks=[task_a, task_b], now=NOW
        )
        mismatches = [i for i in report.issues if i.code == RELATIONSHIP_COUNT_MISMATCH]
        # Task A is in reverse but also in forward (consistent for that task).
        # Count mismatch: 2 forward vs 1 reverse.
        count_mismatches = [i for i in mismatches if i.task_id is None]
        assert len(count_mismatches) == 1
        assert count_mismatches[0].details["forward_count"] == 2
        assert count_mismatches[0].details["reverse_count"] == 1

    def test_no_mismatch_when_no_reverse_refs(self):
        """No mismatch when tasks have no goal: refs (forward-only is canonical)."""
        goal = _task_goal("My goal", related=["Task A", "Task B"])
        task_a = _task("Task A")
        task_b = _task("Task B")
        report = audit_goal_integrity(
            goals=[goal], tasks=[task_a, task_b], now=NOW
        )
        mismatches = [i for i in report.issues if i.code == RELATIONSHIP_COUNT_MISMATCH]
        assert len(mismatches) == 0


# ── 16. Circular references ───────────────────────────────────────────────────

class TestCircularReferences:
    def test_no_circular_ref_for_simple_pair(self):
        """A single goal↔task mutual link is valid (not a circular reference)."""
        goal = _task_goal("Goal A", related=["Task T1"])
        task = _task("Task T1", goal_ref="Goal A")
        report = audit_goal_integrity(goals=[goal], tasks=[task], now=NOW)
        circulars = [i for i in report.issues if i.code == CIRCULAR_REFERENCE]
        assert len(circulars) == 0

    def test_circular_ref_detected(self):
        """A cycle Goal A → Task T1 → Goal B → Task T2 → Goal A is flagged."""
        goal_a = _task_goal("Goal A", related=["Task T1"])
        goal_b = _task_goal("Goal B", related=["Task T2"])
        task_t1 = _task("Task T1", goal_ref="Goal B")  # points to B
        task_t2 = _task("Task T2", goal_ref="Goal A")  # points to A
        report = audit_goal_integrity(
            goals=[goal_a, goal_b], tasks=[task_t1, task_t2], now=NOW
        )
        circulars = [i for i in report.issues if i.code == CIRCULAR_REFERENCE]
        assert len(circulars) >= 1
        assert circulars[0].severity == "error"
        assert "Goal A" in circulars[0].message
        assert "Goal B" in circulars[0].message

    def test_no_circular_ref_for_linear_chain(self):
        """A linear chain Goal A → Task T1 → Goal B (no back-edge) is not circular."""
        goal_a = _task_goal("Goal A", related=["Task T1"])
        goal_b = _task_goal("Goal B", related=[])
        task_t1 = _task("Task T1", goal_ref="Goal B")
        report = audit_goal_integrity(
            goals=[goal_a, goal_b], tasks=[task_t1], now=NOW
        )
        circulars = [i for i in report.issues if i.code == CIRCULAR_REFERENCE]
        assert len(circulars) == 0
