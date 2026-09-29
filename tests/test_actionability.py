"""Tests for the actionability scoring filter.

Covers:
- score_actionability() scoring algorithm
- filter_actionable() batch processing
- create_tasks_for_actionable() task creation
- run_actionability_pipeline() end-to-end
- Edge cases: empty input, threshold boundary, missing fields
"""
from datetime import datetime, timezone

import pytest

from janus.models.goal_integrity_report import GoalIntegrityIssue
from janus.models.task import Task
from janus.services.actionability import (
    DEFAULT_ACTIONABILITY_THRESHOLD,
    ActionabilityReport,
    ActionabilityResult,
    create_tasks_for_actionable,
    filter_actionable,
    run_actionability_pipeline,
    score_actionability,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _issue(
    code: str = "UNKNOWN_GOAL_REFERENCE",
    severity: str = "error",
    goal_id: str | None = None,
    task_id: str | None = None,
    message: str = "Test issue",
    details: dict | None = None,
) -> GoalIntegrityIssue:
    """Build a GoalIntegrityIssue for testing."""
    return GoalIntegrityIssue(
        code=code,
        severity=severity,
        goal_id=goal_id,
        task_id=task_id,
        message=message,
        details=details,
    )


def _mock_task_creator(title: str, metadata: dict) -> Task:
    """Mock task creator that returns a Task without persistence."""
    return Task(title=title, extra_metadata=[f"goal: {metadata['goal']}"] if "goal" in metadata else None)


# ── score_actionability ──────────────────────────────────────────────────────

class TestScoreActionability:
    def test_error_with_full_context_is_actionable(self):
        """Error + repairable + goal+task + details = 50+20+10+10 = 90."""
        issue = _issue(goal_id="Test Goal", task_id="Test Task", details={"key": "value"})
        result = score_actionability(issue)
        assert result.is_actionable is True
        assert result.score == 90
        assert result.suggested_task_title is not None
        assert "Fix" in result.suggested_task_title

    def test_warning_with_no_context_is_not_actionable(self):
        """Warning + no repairable + no context + no details = 30."""
        issue = _issue(
            code="STALE_ACTIVITY",
            severity="warning",
            goal_id=None,
            task_id=None,
        )
        result = score_actionability(issue)
        assert result.is_actionable is False
        assert result.score == 30

    def test_info_severity_alone_is_not_actionable(self):
        """Info severity = 10, below default threshold of 40."""
        issue = _issue(code="STALE_ACTIVITY", severity="info")
        result = score_actionability(issue)
        assert result.is_actionable is False
        assert result.score == 10

    def test_repairable_code_bonus(self):
        """Repairable code adds 20 points."""
        issue = _issue(code="ORPHANED_TASK", severity="warning")
        result = score_actionability(issue)
        # 30 (warning) + 20 (repairable) = 50
        assert result.score == 50
        assert result.is_actionable is True

    def test_non_repairable_code_no_bonus(self):
        """Non-repairable code gets no bonus."""
        issue = _issue(code="STALE_ACTIVITY", severity="warning")
        result = score_actionability(issue)
        # 30 (warning) + 0 = 30
        assert result.score == 30
        assert result.is_actionable is False

    def test_context_bonus_with_both_ids(self):
        """Having both goal_id and task_id adds 10 points."""
        issue = _issue(
            code="STALE_ACTIVITY",
            severity="warning",
            goal_id="Goal",
            task_id="Task",
        )
        result = score_actionability(issue)
        # 30 + 10 = 40, exactly at threshold
        assert result.score == 40
        assert result.is_actionable is True

    def test_context_bonus_with_only_goal_id(self):
        """Having only goal_id (no task_id) does not get context bonus."""
        issue = _issue(
            code="STALE_ACTIVITY",
            severity="warning",
            goal_id="Goal",
            task_id=None,
        )
        result = score_actionability(issue)
        # 30 + 0 = 30
        assert result.score == 30
        assert result.is_actionable is False

    def test_details_bonus(self):
        """Having structured details adds 10 points."""
        issue = _issue(
            code="STALE_ACTIVITY",
            severity="warning",
            details={"foo": "bar"},
        )
        result = score_actionability(issue)
        # 30 + 10 = 40
        assert result.score == 40
        assert result.is_actionable is True

    def test_custom_threshold(self):
        """Custom threshold changes actionability decision."""
        issue = _issue(code="STALE_ACTIVITY", severity="warning")  # score = 30
        result = score_actionability(issue, threshold=25)
        assert result.is_actionable is True
        result = score_actionability(issue, threshold=35)
        assert result.is_actionable is False

    def test_suggested_task_title_with_both_ids(self):
        """Task title includes both goal and task when both present."""
        issue = _issue(goal_id="My Goal", task_id="My Task")
        result = score_actionability(issue)
        assert result.suggested_task_title is not None
        assert "My Goal" in result.suggested_task_title
        assert "My Task" in result.suggested_task_title

    def test_suggested_task_title_with_only_goal(self):
        """Task title includes only goal when task_id is None."""
        issue = _issue(goal_id="My Goal", task_id=None)
        result = score_actionability(issue)
        assert result.suggested_task_title is not None
        assert "My Goal" in result.suggested_task_title

    def test_suggested_task_title_with_only_task(self):
        """Task title includes only task when goal_id is None."""
        issue = _issue(goal_id=None, task_id="My Task")
        result = score_actionability(issue)
        assert result.suggested_task_title is not None
        assert "My Task" in result.suggested_task_title

    def test_suggested_task_title_with_neither(self):
        """Task title is just the code prefix when no IDs present."""
        issue = _issue(goal_id=None, task_id=None)
        result = score_actionability(issue)
        assert result.suggested_task_title is not None
        assert "Fix" in result.suggested_task_title

    def test_suggested_task_metadata_contains_goal(self):
        """Metadata includes goal reference when goal_id present."""
        issue = _issue(goal_id="Test Goal")
        result = score_actionability(issue)
        assert result.suggested_task_metadata.get("goal") == "Test Goal"

    def test_suggested_task_metadata_contains_issue_code(self):
        """Metadata always includes the issue code."""
        issue = _issue(code="ORPHANED_TASK")
        result = score_actionability(issue)
        assert result.suggested_task_metadata.get("issue_code") == "ORPHANED_TASK"

    def test_reasons_list_populated(self):
        """Reasons list contains human-readable scoring factors."""
        issue = _issue(details={"key": "value"})
        result = score_actionability(issue)
        assert len(result.reasons) > 0
        assert any("severity" in r for r in result.reasons)

    def test_non_actionable_has_no_suggested_title(self):
        """Non-actionable issues have no suggested task title."""
        issue = _issue(severity="info")
        result = score_actionability(issue)
        assert result.is_actionable is False
        assert result.suggested_task_title is None


# ── filter_actionable ────────────────────────────────────────────────────────

class TestFilterActionable:
    def test_empty_input(self):
        """Empty input returns empty report."""
        report = filter_actionable([])
        assert report.results == []
        assert report.actionable == []
        assert report.recorded == []
        assert report.actionable_count == 0
        assert report.recorded_count == 0

    def test_mixed_issues(self):
        """Mix of actionable and non-actionable issues."""
        issues = [
            _issue(code="UNKNOWN_GOAL_REFERENCE", severity="error"),  # actionable
            _issue(code="STALE_ACTIVITY", severity="info"),  # not actionable
        ]
        report = filter_actionable(issues)
        assert len(report.results) == 2
        assert report.actionable_count == 1
        assert report.recorded_count == 1

    def test_all_actionable(self):
        """All issues actionable."""
        issues = [
            _issue(code="UNKNOWN_GOAL_REFERENCE", severity="error"),
            _issue(code="INVALID_METRIC", severity="error"),
        ]
        report = filter_actionable(issues)
        assert report.actionable_count == 2
        assert report.recorded_count == 0

    def test_all_recorded(self):
        """No issues actionable."""
        issues = [
            _issue(code="STALE_ACTIVITY", severity="info"),
            _issue(code="GOAL_WITHOUT_TASKS", severity="info"),
        ]
        report = filter_actionable(issues)
        assert report.actionable_count == 0
        assert report.recorded_count == 2

    def test_evaluated_at_set(self):
        """Report has evaluated_at timestamp."""
        report = filter_actionable([])
        assert report.evaluated_at is not None
        assert isinstance(report.evaluated_at, datetime)

    def test_custom_threshold_in_filter(self):
        """Custom threshold passed through to scoring."""
        issues = [_issue(code="STALE_ACTIVITY", severity="warning")]  # score = 30
        report = filter_actionable(issues, threshold=25)
        assert report.actionable_count == 1
        report = filter_actionable(issues, threshold=35)
        assert report.recorded_count == 1


# ── create_tasks_for_actionable ─────────────────────────────────────────────

class TestCreateTasksForActionable:
    def test_creates_task_for_actionable(self):
        """Actionable issues get tasks created."""
        issues = [_issue(code="UNKNOWN_GOAL_REFERENCE", severity="error")]
        report = filter_actionable(issues)
        created = create_tasks_for_actionable(report, _mock_task_creator)
        assert len(created) == 1
        assert isinstance(created[0], Task)
        assert "Fix" in created[0].title

    def test_no_task_for_recorded(self):
        """Non-actionable issues do not get tasks created."""
        issues = [_issue(code="STALE_ACTIVITY", severity="info")]
        report = filter_actionable(issues)
        created = create_tasks_for_actionable(report, _mock_task_creator)
        assert len(created) == 0

    def test_task_has_goal_metadata(self):
        """Created task has goal reference in extra_metadata."""
        issues = [_issue(code="UNKNOWN_GOAL_REFERENCE", severity="error", goal_id="My Goal")]
        report = filter_actionable(issues)
        created = create_tasks_for_actionable(report, _mock_task_creator)
        assert len(created) == 1
        assert created[0].extra_metadata is not None
        assert any("My Goal" in m for m in created[0].extra_metadata)

    def test_empty_report_creates_no_tasks(self):
        """Empty report creates no tasks."""
        report = ActionabilityReport()
        created = create_tasks_for_actionable(report, _mock_task_creator)
        assert len(created) == 0

    def test_multiple_actionable_creates_multiple_tasks(self):
        """Multiple actionable issues each get a task."""
        issues = [
            _issue(code="UNKNOWN_GOAL_REFERENCE", severity="error"),
            _issue(code="INVALID_METRIC", severity="error"),
            _issue(code="STALE_ACTIVITY", severity="info"),
        ]
        report = filter_actionable(issues)
        created = create_tasks_for_actionable(report, _mock_task_creator)
        assert len(created) == 2

    def test_task_creator_failure_does_not_crash(self):
        """If task creator raises, other tasks are still created."""
        call_count = 0

        def flaky_creator(title: str, metadata: dict) -> Task:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Simulated failure")
            return Task(title=title)

        issues = [
            _issue(code="UNKNOWN_GOAL_REFERENCE", severity="error"),
            _issue(code="INVALID_METRIC", severity="error"),
        ]
        report = filter_actionable(issues)
        created = create_tasks_for_actionable(report, flaky_creator)
        # First call fails, second succeeds
        assert len(created) == 1


# ── run_actionability_pipeline ───────────────────────────────────────────────

class TestRunActionabilityPipeline:
    def test_end_to_end(self):
        """Full pipeline: filter → create tasks."""
        issues = [
            _issue(code="UNKNOWN_GOAL_REFERENCE", severity="error"),
            _issue(code="STALE_ACTIVITY", severity="info"),
        ]
        report, created = run_actionability_pipeline(issues, task_creator=_mock_task_creator)
        assert report.actionable_count == 1
        assert report.recorded_count == 1
        assert len(created) == 1

    def test_empty_pipeline(self):
        """Empty input produces empty results."""
        report, created = run_actionability_pipeline([], task_creator=_mock_task_creator)
        assert report.actionable_count == 0
        assert len(created) == 0


# ── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_issue_with_empty_details(self):
        """Empty details dict is falsy, no bonus."""
        issue = _issue(goal_id="Test Goal", task_id="Test Task", details={})
        result = score_actionability(issue)
        # error(50) + repairable(20) + context(10) = 80, no details bonus
        assert result.score == 80

    def test_issue_with_none_details(self):
        """None details, no bonus."""
        issue = _issue(goal_id="Test Goal", task_id="Test Task", details=None)
        result = score_actionability(issue)
        # error(50) + repairable(20) + context(10) = 80
        assert result.score == 80

    def test_unknown_severity_defaults_to_zero(self):
        """Unknown severity string gets 0 weight."""
        issue = _issue(severity="critical")
        result = score_actionability(issue)
        # 0 + repairable(20) = 20
        assert result.score == 20

    def test_threshold_boundary_exact(self):
        """Score exactly at threshold is actionable."""
        issue = _issue(
            code="STALE_ACTIVITY",
            severity="warning",
            goal_id="Goal",
            task_id="Task",
        )
        # 30 + 10 = 40, exactly at default threshold
        result = score_actionability(issue, threshold=40)
        assert result.is_actionable is True

    def test_threshold_boundary_below(self):
        """Score just below threshold is not actionable."""
        issue = _issue(
            code="STALE_ACTIVITY",
            severity="warning",
            goal_id="Goal",
            task_id="Task",
        )
        # 30 + 10 = 40, threshold 41
        result = score_actionability(issue, threshold=41)
        assert result.is_actionable is False

    def test_all_repairable_codes(self):
        """All repairable codes get the bonus."""
        repairable_codes = [
            "UNKNOWN_GOAL_REFERENCE",
            "INVALID_RELATED_TASK",
            "CIRCULAR_REFERENCE",
            "ORPHANED_TASK",
            "RELATIONSHIP_COUNT_MISMATCH",
        ]
        for code in repairable_codes:
            issue = _issue(code=code, severity="warning")
            result = score_actionability(issue)
            # 30 + 20 = 50
            assert result.score == 50, f"Code {code} should be repairable"

    def test_all_non_repairable_codes(self):
        """Non-repairable codes do not get the bonus."""
        non_repairable_codes = [
            "GOAL_WITHOUT_TASKS",
            "INVALID_METRIC",
            "STALE_ACTIVITY",
        ]
        for code in non_repairable_codes:
            issue = _issue(code=code, severity="warning")
            result = score_actionability(issue)
            # 30 + 0 = 30
            assert result.score == 30, f"Code {code} should not be repairable"
