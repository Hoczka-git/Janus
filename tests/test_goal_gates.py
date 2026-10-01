"""Tests for goal completion gates (ADR-011).

Design reference: docs/design/policy_approval_p1_design.md §11.1
"""

from __future__ import annotations

import pytest

from janus.models.goal import Goal
from janus.services.goal_gates import (
    GoalCompletionGateError,
    GoalCompletionGateResult,
    GATE_GOAL_NOT_FOUND,
    GATE_GOAL_ALREADY_COMPLETED,
    GATE_GOAL_METRIC_NOT_AT_TARGET,
    run_goal_completion_gates,
)


class TestRunGoalCompletionGates:
    def test_none_goal_blocks(self):
        result = run_goal_completion_gates(None)
        assert not result.ok
        assert result.blocked_reason == GATE_GOAL_NOT_FOUND

    def test_already_completed_blocks(self):
        goal = Goal(title="Test", status="completed")
        result = run_goal_completion_gates(goal)
        assert not result.ok
        assert result.blocked_reason == GATE_GOAL_ALREADY_COMPLETED

    def test_active_goal_passes(self):
        goal = Goal(title="Test", status="active")
        result = run_goal_completion_gates(goal)
        assert result.ok

    def test_metric_at_target_passes(self):
        goal = Goal(
            title="Test",
            status="active",
            metric_name="Weight",
            current_value=70.0,
            target_value=70.0,
            direction="decrease",
        )
        result = run_goal_completion_gates(goal)
        assert result.ok

    def test_metric_not_at_target_blocks(self):
        goal = Goal(
            title="Test",
            status="active",
            metric_name="Weight",
            current_value=80.0,
            target_value=70.0,
            direction="decrease",
        )
        result = run_goal_completion_gates(goal)
        assert not result.ok
        assert result.blocked_reason == GATE_GOAL_METRIC_NOT_AT_TARGET

    def test_metric_increase_not_at_target_blocks(self):
        goal = Goal(
            title="Test",
            status="active",
            metric_name="Savings",
            current_value=5000.0,
            target_value=10000.0,
            direction="increase",
        )
        result = run_goal_completion_gates(goal)
        assert not result.ok
        assert result.blocked_reason == GATE_GOAL_METRIC_NOT_AT_TARGET

    def test_metric_no_current_value_blocks(self):
        goal = Goal(
            title="Test",
            status="active",
            metric_name="Weight",
            current_value=None,
            target_value=70.0,
            direction="decrease",
        )
        result = run_goal_completion_gates(goal)
        assert not result.ok
        assert result.blocked_reason == GATE_GOAL_METRIC_NOT_AT_TARGET

    def test_no_metric_passes(self):
        goal = Goal(title="Test", status="active")
        result = run_goal_completion_gates(goal)
        assert result.ok


class TestGoalCompletionGateError:
    def test_construction(self):
        error = GoalCompletionGateError(
            reason="test_reason",
            message="Test message",
        )
        assert error.reason == "test_reason"
        assert str(error) == "Test message"

    def test_is_value_error(self):
        error = GoalCompletionGateError(reason="test", message="Test")
        assert isinstance(error, ValueError)
