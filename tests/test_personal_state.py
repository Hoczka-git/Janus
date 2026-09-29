"""Tests for the PersonalState data model.

Spec: docs/design/personal_state_model_spec.md

Covers:
- PersonalState construction and validation
- PersonalStateStatus enum
- Transition rules (goal, task, followup)
- Derived properties (is_empty, has_integrity_errors, counts)
- Serialization (to_dict)
"""

from datetime import datetime, timezone

import pytest

from janus.models.personal_state import (
    PersonalState,
    PersonalStateStatus,
    GOAL_STATUS_TRANSITIONS,
    TASK_STATE_TRANSITIONS,
    FOLLOWUP_STATE_TRANSITIONS,
    is_valid_goal_transition,
    is_valid_task_transition,
    is_valid_followup_transition,
)
from janus.models.goal import Goal
from janus.models.task import Task
from janus.models.follow_up import FollowUp
from janus.models.inbox import InboxItem
from janus.models.goal_integrity_report import GoalIntegrityIssue


NOW = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)
FINGERPRINT = "abc123def456"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_state(**kwargs) -> PersonalState:
    """Build a minimal valid PersonalState with overrides."""
    from typing import Any
    defaults: dict[str, Any] = dict(
        generated_at=NOW,
        data_fingerprint=FINGERPRINT,
    )
    defaults.update(kwargs)
    return PersonalState(**defaults)


def _make_goal(title="Test Goal", status="active", **kwargs) -> Goal:
    return Goal(title=title, status=status, **kwargs)


def _make_task(title="Test Task", state="todo", **kwargs) -> Task:
    return Task(title=title, state=state, **kwargs)


def _make_followup(id="fu-1", title="Test FollowUp", state="pending", **kwargs) -> FollowUp:
    return FollowUp(id=id, title=title, state=state, **kwargs)


def _make_inbox_item(id="ib-1", captured_text="Test item", **kwargs) -> InboxItem:
    return InboxItem(id=id, captured_text=captured_text, **kwargs)


def _make_integrity_issue(severity="error", code="TEST") -> GoalIntegrityIssue:
    return GoalIntegrityIssue(code=code, severity=severity, message="test")


# ── Construction and validation ──────────────────────────────────────────────


class TestPersonalStateConstruction:
    def test_minimal_construction(self):
        state = _make_state()
        assert state.generated_at == NOW
        assert state.data_fingerprint == FINGERPRINT
        assert state.goals == []
        assert state.tasks == []
        assert state.status == PersonalStateStatus.HEALTHY

    def test_full_construction(self):
        goal = _make_goal()
        task = _make_task()
        followup = _make_followup()
        inbox = _make_inbox_item()
        issue = _make_integrity_issue()

        state = _make_state(
            goals=[goal],
            active_goals=[goal],
            tasks=[task],
            open_tasks=[task],
            followups=[followup],
            inbox_items=[inbox],
            integrity_issues=[issue],
            status=PersonalStateStatus.CRITICAL,
        )
        assert state.goals == [goal]
        assert state.active_goals == [goal]
        assert state.tasks == [task]
        assert state.open_tasks == [task]
        assert state.followups == [followup]
        assert state.inbox_items == [inbox]
        assert state.integrity_issues == [issue]
        assert state.status == PersonalStateStatus.CRITICAL

    def test_empty_fingerprint_raises(self):
        with pytest.raises(ValueError, match="data_fingerprint"):
            _make_state(data_fingerprint="")

    def test_whitespace_fingerprint_raises(self):
        with pytest.raises(ValueError, match="data_fingerprint"):
            _make_state(data_fingerprint="   ")

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="Invalid status"):
            _make_state(status="invalid_status")

    def test_default_status_is_healthy(self):
        state = _make_state()
        assert state.status == PersonalStateStatus.HEALTHY


# ── PersonalStateStatus enum ─────────────────────────────────────────────────


class TestPersonalStateStatus:
    def test_enum_values(self):
        assert PersonalStateStatus.HEALTHY == "healthy"
        assert PersonalStateStatus.ATTENTION_NEEDED == "attention_needed"
        assert PersonalStateStatus.CRITICAL == "critical"
        assert PersonalStateStatus.EMPTY == "empty"

    def test_enum_membership(self):
        assert PersonalStateStatus.HEALTHY in PersonalStateStatus
        assert PersonalStateStatus("healthy") == PersonalStateStatus.HEALTHY
        with pytest.raises(ValueError):
            PersonalStateStatus("nonexistent")

    def test_enum_from_value(self):
        assert PersonalStateStatus("healthy") == PersonalStateStatus.HEALTHY
        assert PersonalStateStatus("critical") == PersonalStateStatus.CRITICAL


# ── Derived properties ───────────────────────────────────────────────────────


class TestPersonalStateProperties:
    def test_is_empty_true(self):
        state = _make_state()
        assert state.is_empty is True

    def test_is_empty_false_with_goals(self):
        state = _make_state(goals=[_make_goal()])
        assert state.is_empty is False

    def test_is_empty_false_with_tasks(self):
        state = _make_state(tasks=[_make_task()])
        assert state.is_empty is False

    def test_is_empty_false_with_followups(self):
        state = _make_state(followups=[_make_followup()])
        assert state.is_empty is False

    def test_has_integrity_errors_true(self):
        issue = _make_integrity_issue(severity="error")
        state = _make_state(integrity_issues=[issue])
        assert state.has_integrity_errors is True

    def test_has_integrity_errors_false_with_warnings_only(self):
        issue = _make_integrity_issue(severity="warning")
        state = _make_state(integrity_issues=[issue])
        assert state.has_integrity_errors is False

    def test_has_integrity_errors_false_when_empty(self):
        state = _make_state()
        assert state.has_integrity_errors is False

    def test_goal_count(self):
        state = _make_state(goals=[_make_goal("A"), _make_goal("B")])
        assert state.goal_count == 2

    def test_active_goal_count(self):
        state = _make_state(active_goals=[_make_goal("A")])
        assert state.active_goal_count == 1

    def test_open_task_count(self):
        state = _make_state(open_tasks=[_make_task("A"), _make_task("B")])
        assert state.open_task_count == 2

    def test_blocked_task_count(self):
        state = _make_state(blocked_tasks=[_make_task("A", state="blocked")])
        assert state.blocked_task_count == 1

    def test_followup_count(self):
        state = _make_state(followups=[_make_followup("fu-1"), _make_followup("fu-2")])
        assert state.followup_count == 2

    def test_inbox_count(self):
        state = _make_state(inbox_items=[_make_inbox_item("ib-1"), _make_inbox_item("ib-2")])
        assert state.inbox_count == 2

    def test_integrity_error_count(self):
        issues = [
            _make_integrity_issue(severity="error"),
            _make_integrity_issue(severity="error"),
            _make_integrity_issue(severity="warning"),
        ]
        state = _make_state(integrity_issues=issues)
        assert state.integrity_error_count == 2

    def test_integrity_warning_count(self):
        issues = [
            _make_integrity_issue(severity="error"),
            _make_integrity_issue(severity="warning"),
            _make_integrity_issue(severity="warning"),
        ]
        state = _make_state(integrity_issues=issues)
        assert state.integrity_warning_count == 2


# ── Goal status transitions ─────────────────────────────────────────────────


class TestGoalStatusTransitions:
    def test_valid_transitions_defined(self):
        assert "active" in GOAL_STATUS_TRANSITIONS
        assert "completed" in GOAL_STATUS_TRANSITIONS["active"]
        assert "inactive" in GOAL_STATUS_TRANSITIONS["active"]
        assert "active" in GOAL_STATUS_TRANSITIONS["inactive"]
        assert "active" in GOAL_STATUS_TRANSITIONS["completed"]

    def test_active_to_completed_valid(self):
        assert is_valid_goal_transition("active", "completed") is True

    def test_active_to_inactive_valid(self):
        assert is_valid_goal_transition("active", "inactive") is True

    def test_inactive_to_active_valid(self):
        assert is_valid_goal_transition("inactive", "active") is True

    def test_completed_to_active_valid(self):
        assert is_valid_goal_transition("completed", "active") is True

    def test_active_to_active_invalid(self):
        assert is_valid_goal_transition("active", "active") is False

    def test_completed_to_inactive_invalid(self):
        assert is_valid_goal_transition("completed", "inactive") is False

    def test_inactive_to_completed_invalid(self):
        assert is_valid_goal_transition("inactive", "completed") is False

    def test_unknown_from_status_invalid(self):
        assert is_valid_goal_transition("unknown", "active") is False

    def test_unknown_to_status_invalid(self):
        assert is_valid_goal_transition("active", "unknown") is False


# ── Task state transitions ───────────────────────────────────────────────────


class TestTaskStateTransitions:
    def test_valid_transitions_defined(self):
        assert "todo" in TASK_STATE_TRANSITIONS
        assert "in_progress" in TASK_STATE_TRANSITIONS["todo"]
        assert "blocked" in TASK_STATE_TRANSITIONS["todo"]
        assert "blocked" in TASK_STATE_TRANSITIONS["in_progress"]
        assert "todo" in TASK_STATE_TRANSITIONS["blocked"]

    def test_todo_to_in_progress_valid(self):
        assert is_valid_task_transition("todo", "in_progress") is True

    def test_todo_to_blocked_valid(self):
        assert is_valid_task_transition("todo", "blocked") is True

    def test_in_progress_to_blocked_valid(self):
        assert is_valid_task_transition("in_progress", "blocked") is True

    def test_blocked_to_in_progress_valid(self):
        assert is_valid_task_transition("blocked", "in_progress") is True

    def test_blocked_to_todo_valid(self):
        assert is_valid_task_transition("blocked", "todo") is True

    def test_todo_to_todo_invalid(self):
        assert is_valid_task_transition("todo", "todo") is False

    def test_in_progress_to_todo_valid(self):
        assert is_valid_task_transition("in_progress", "todo") is True

    def test_unknown_state_invalid(self):
        assert is_valid_task_transition("unknown", "todo") is False


# ── Follow-up state transitions ──────────────────────────────────────────────


class TestFollowUpStateTransitions:
    def test_valid_transitions_defined(self):
        assert "pending" in FOLLOWUP_STATE_TRANSITIONS
        assert "scheduled" in FOLLOWUP_STATE_TRANSITIONS["pending"]
        assert "in_progress" in FOLLOWUP_STATE_TRANSITIONS["pending"]
        assert "completed" in FOLLOWUP_STATE_TRANSITIONS["in_progress"]
        assert "deferred" in FOLLOWUP_STATE_TRANSITIONS["pending"]

    def test_pending_to_scheduled_valid(self):
        assert is_valid_followup_transition("pending", "scheduled") is True

    def test_pending_to_in_progress_valid(self):
        assert is_valid_followup_transition("pending", "in_progress") is True

    def test_pending_to_deferred_valid(self):
        assert is_valid_followup_transition("pending", "deferred") is True

    def test_scheduled_to_in_progress_valid(self):
        assert is_valid_followup_transition("scheduled", "in_progress") is True

    def test_in_progress_to_blocked_valid(self):
        assert is_valid_followup_transition("in_progress", "blocked") is True

    def test_in_progress_to_completed_valid(self):
        assert is_valid_followup_transition("in_progress", "completed") is True

    def test_blocked_to_completed_valid(self):
        assert is_valid_followup_transition("blocked", "completed") is True

    def test_deferred_to_pending_valid(self):
        assert is_valid_followup_transition("deferred", "pending") is True

    def test_completed_is_terminal(self):
        assert is_valid_followup_transition("completed", "pending") is False
        assert is_valid_followup_transition("completed", "in_progress") is False

    def test_pending_to_completed_invalid(self):
        assert is_valid_followup_transition("pending", "completed") is False

    def test_unknown_state_invalid(self):
        assert is_valid_followup_transition("unknown", "pending") is False


# ── Serialization ────────────────────────────────────────────────────────────


class TestPersonalStateSerialization:
    def test_to_dict_returns_dict(self):
        state = _make_state()
        result = state.to_dict()
        assert isinstance(result, dict)

    def test_to_dict_contains_core_fields(self):
        state = _make_state()
        result = state.to_dict()
        assert "generated_at" in result
        assert "data_fingerprint" in result
        assert "goals" in result
        assert "tasks" in result
        assert "status" in result

    def test_to_dict_serializes_datetime(self):
        state = _make_state()
        result = state.to_dict()
        assert isinstance(result["generated_at"], str)
        assert "2026" in result["generated_at"]

    def test_to_dict_serializes_status_enum(self):
        state = _make_state(status=PersonalStateStatus.CRITICAL)
        result = state.to_dict()
        assert result["status"] == "critical"

    def test_to_dict_with_goals(self):
        goal = _make_goal(title="My Goal")
        state = _make_state(goals=[goal])
        result = state.to_dict()
        assert len(result["goals"]) == 1
        assert result["goals"][0]["title"] == "My Goal"

    def test_to_dict_with_integrity_issues(self):
        issue = _make_integrity_issue(severity="error", code="ORPHANED_TASK")
        state = _make_state(integrity_issues=[issue])
        result = state.to_dict()
        assert len(result["integrity_issues"]) == 1
        assert result["integrity_issues"][0]["code"] == "ORPHANED_TASK"
