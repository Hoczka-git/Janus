"""Tests for goal progress calculation.

Tests compute_goal_progress, compute_metric_progress, and
compute_task_based_progress from services/goal_progress.py.
"""

import pytest

from janus.models.goal import Goal
from janus.services.goal_progress import (
    compute_goal_progress,
    _compute_metric_progress,
    _compute_task_based_progress,
)


# ===========================================================================
# 1. Metric increase
# ===========================================================================

def test_increase_halfway():
    result = _compute_metric_progress(0, 50, 100, "increase")
    assert result == 50.0


def test_increase_three_quarter():
    result = _compute_metric_progress(140, 170, 200, "increase")
    # (170-140)/(200-140) = 30/60 = 50%
    assert result == pytest.approx(50.0)


def test_increase_at_target():
    result = _compute_metric_progress(0, 100, 100, "increase")
    assert result == 100.0


def test_increase_beyond_target():
    result = _compute_metric_progress(0, 120, 100, "increase")
    assert result == pytest.approx(100.0)


def test_increase_at_start():
    result = _compute_metric_progress(0, 0, 100, "increase")
    assert result == 0.0


def test_increase_below_start():
    result = _compute_metric_progress(100, 80, 200, "increase")
    assert result == pytest.approx(0.0)


# ===========================================================================
# 2. Metric decrease
# ===========================================================================

def test_decrease_body_fat():
    result = _compute_metric_progress(23, 20, 15, "decrease")
    # (23 - 20) / (23 - 15) = 3/8 = 37.5%
    assert result == pytest.approx(37.5)


def test_decrease_at_target():
    result = _compute_metric_progress(23, 15, 15, "decrease")
    assert result == 100.0


def test_decrease_beyond_target():
    result = _compute_metric_progress(23, 10, 15, "decrease")
    assert result == pytest.approx(100.0)


def test_decrease_at_start():
    result = _compute_metric_progress(23, 23, 15, "decrease")
    assert result == 0.0


def test_decrease_above_start():
    result = _compute_metric_progress(23, 25, 15, "decrease")
    assert result == pytest.approx(0.0)


# ===========================================================================
# 3. Edge cases
# ===========================================================================

def test_start_equals_target_at_target():
    result = _compute_metric_progress(80, 80, 80, "increase")
    assert result == 100.0


def test_start_equals_target_drifted():
    result = _compute_metric_progress(80, 82, 80, "increase")
    assert result == 0.0


def test_negative_values_debt():
    result = _compute_metric_progress(-5000, -2000, 0, "increase")
    assert result == pytest.approx(60.0)


def test_percentages():
    result = _compute_metric_progress(23.0, 20.0, 15.0, "decrease")
    # (23 - 20) / (23 - 15) = 3/8 = 37.5%
    assert result == pytest.approx(37.5)


def test_absolute_units_pln():
    result = _compute_metric_progress(0, 4500, 10000, "increase")
    assert result == pytest.approx(45.0)


def test_absolute_units_kg():
    result = _compute_metric_progress(80, 82, 90, "increase")
    assert result == pytest.approx(20.0)


# ===========================================================================
# 4. Invalid configuration
# ===========================================================================

def test_invalid_increase_target_not_greater():
    with pytest.raises(ValueError, match="Invalid increase goal"):
        _compute_metric_progress(100, 50, 50, "increase")


def test_invalid_decrease_target_not_less():
    with pytest.raises(ValueError, match="Invalid decrease goal"):
        _compute_metric_progress(50, 50, 100, "decrease")


def test_invalid_direction():
    with pytest.raises(ValueError, match="Invalid direction"):
        _compute_metric_progress(0, 50, 100, "sideways")


# ===========================================================================
# 5. compute_goal_progress with full Goal objects
# ===========================================================================

def test_metric_goal_full():
    g = Goal(
        title="Body fat",
        metric_name="Body fat %",
        start_value=23.0,
        current_value=20.0,
        target_value=15.0,
        direction="decrease",
    )
    result = compute_goal_progress(g)
    # (23-20)/(23-15) = 3/8 = 37.5%
    assert result == pytest.approx(37.5)


def test_metric_goal_missing_current():
    g = Goal(
        title="X",
        metric_name="Body fat %",
        start_value=23.0,
        target_value=15.0,
        direction="decrease",
    )
    result = compute_goal_progress(g)
    assert result is None


def test_metric_goal_missing_start():
    g = Goal(
        title="X",
        metric_name="Body fat %",
        current_value=20.0,
        target_value=15.0,
        direction="decrease",
    )
    result = compute_goal_progress(g)
    assert result is None


def test_metric_goal_missing_target():
    g = Goal(
        title="X",
        metric_name="Body fat %",
        start_value=23.0,
        current_value=20.0,
        direction="decrease",
    )
    result = compute_goal_progress(g)
    assert result is None


def test_metric_goal_missing_direction():
    g = Goal(
        title="X",
        metric_name="Body fat %",
        start_value=23.0,
        current_value=20.0,
        target_value=15.0,
    )
    result = compute_goal_progress(g)
    assert result is None


def test_task_based_goal_no_completed_titles():
    g = Goal(
        title="Japan trip",
        related_tasks=["Buy flights", "Book hotels", "Create itinerary"],
    )
    result = compute_goal_progress(g, completed_task_titles=None)
    assert result is None


def test_no_metric_no_tasks():
    g = Goal(title="Simple goal")
    result = compute_goal_progress(g)
    assert result is None


def test_completed_goal():
    g = Goal(
        title="Done",
        status="completed",
        metric_name="Body fat %",
        start_value=23.0,
        current_value=15.0,
        target_value=15.0,
        direction="decrease",
    )
    result = compute_goal_progress(g)
    assert result is None


def test_inactive_goal():
    g = Goal(
        title="Paused",
        status="inactive",
        metric_name="Body fat %",
        start_value=23.0,
        current_value=20.0,
        target_value=15.0,
        direction="decrease",
    )
    result = compute_goal_progress(g)
    assert result is None


def test_metric_plus_tasks_metric_prioritizes():
    g = Goal(
        title="Body fat",
        metric_name="Body fat %",
        start_value=23.0,
        current_value=20.0,
        target_value=15.0,
        direction="decrease",
        related_tasks=["Task A", "Task B"],
    )
    result = compute_goal_progress(g, completed_task_titles={"Task A"})
    # Metric progress should be prioritized over task-based
    # (23 - 20) / (23 - 15) = 3/8 = 37.5%
    assert result == pytest.approx(37.5)


def test_goal_with_completed_task_titles():
    g = Goal(
        title="Japan trip",
        related_tasks=["Buy flights", "Book hotels", "Create itinerary"],
    )
    result = compute_goal_progress(g, completed_task_titles={"Buy flights"})
    assert result == pytest.approx(33.333333333333336)


def test_goal_without_completed_task_titles():
    g = Goal(
        title="Japan trip",
        related_tasks=["Buy flights", "Book hotels", "Create itinerary"],
    )
    result = compute_goal_progress(g, completed_task_titles=None)
    assert result is None


# ===========================================================================
# 6. Task-based progress
# ===========================================================================

def test_task_based_one_of_three():
    result = _compute_task_based_progress(["A", "B", "C"], 1)
    assert result == pytest.approx(33.333333333333336)


def test_task_based_all_complete():
    result = _compute_task_based_progress(["A", "B", "C"], 3)
    assert result == 100.0


def test_task_based_none_complete():
    result = _compute_task_based_progress(["A", "B", "C"], 0)
    assert result == 0.0


def test_task_based_invalid_count_negative():
    with pytest.raises(ValueError, match="completed_count"):
        _compute_task_based_progress(["A", "B", "C"], -1)


def test_task_based_invalid_count_over():
    with pytest.raises(ValueError, match="completed_count"):
        _compute_task_based_progress(["A", "B", "C"], 4)


def test_task_based_empty_tasks():
    with pytest.raises(ValueError, match="related_tasks must be non-empty"):
        _compute_task_based_progress([], 0)
