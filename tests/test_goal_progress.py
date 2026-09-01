"""Tests for Goal progress calculation — metric, task-based, centralized.

All tests use direct function calls (no CLI, no persistence).
"""

import pytest

from janus.models.goal import Goal
from janus.services.goal_progress import (
    compute_goal_progress,
    _compute_metric_progress,
    _compute_task_based_progress,
)


def _compute(start, current, target, direction):
    """Shorthand for _compute_metric_progress."""
    return _compute_metric_progress(start, current, target, direction)


def _compute_task_based(completed_count, related_tasks):
    """Shorthand for _compute_task_based_progress."""
    return _compute_task_based_progress(related_tasks, completed_count)


def test_increase_halfway():
    result = _compute(0, 50, 100, "increase")
    assert result == 50.0


def test_increase_three_quarter():
    result = _compute(0, 5000, 10000, "increase")
    assert result == pytest.approx(50.0)


def test_increase_at_target():
    result = _compute(0, 100, 100, "increase")
    assert result == 100.0


def test_increase_beyond_target():
    result = _compute(0, 120, 100, "increase")
    assert result == 100.0


def test_increase_at_start():
    result = _compute(0, 0, 100, "increase")
    assert result == 0.0


def test_increase_below_start():
    result = _compute(100, 80, 200, "increase")
    assert result == 0.0


def test_decrease_body_fat():
    result = _compute(23, 20, 15, "decrease")
    assert result == pytest.approx(37.5)


def test_decrease_at_target():
    result = _compute(23, 15, 15, "decrease")
    assert result == 100.0


def test_decrease_beyond_target():
    result = _compute(23, 10, 15, "decrease")
    assert result == 100.0


def test_decrease_at_start():
    result = _compute(23, 23, 15, "decrease")
    assert result == 0.0


def test_decrease_above_start():
    result = _compute(23, 25, 15, "decrease")
    assert result == 0.0


def test_degenerate_maintain_at_target():
    # start == target, current == target -> 100%
    assert _compute(80, 80, 80, "increase") == 100.0
    assert _compute(80, 80, 80, "decrease") == 100.0


def test_degenerate_drifted_from_target():
    # start == target, current drifted -> 0%
    assert _compute(80, 82, 80, "increase") == 0.0
    assert _compute(80, 78, 80, "decrease") == 0.0


def test_degenerate_direction_conflict():
    # start == target, but direction says opposite of drift
    # increase with current below start should still be 0%
    assert _compute(80, 78, 80, "increase") == 0.0


def test_negative_values_debt():
    result = _compute(-5000, -2000, 0, "increase")
    # (-2000 - (-5000)) / (0 - (-5000)) = 3000/5000 = 60%
    assert result == pytest.approx(60.0)


def test_percentages():
    result = _compute(23.0, 20.0, 15.0, "decrease")
    assert result == pytest.approx(37.5)


def test_absolute_units_pln():
    result = _compute(0, 4500, 10000, "increase")
    assert result == pytest.approx(45.0)


def test_absolute_units_kg():
    result = _compute(80, 82, 90, "increase")
    assert result == pytest.approx(20.0)


# ===========================================================================
# Invalid configuration
# ===========================================================================


def test_invalid_increase_target_not_greater():
    with pytest.raises(ValueError, match="must be greater than start"):
        _compute(100, 50, 50, "increase")


def test_invalid_decrease_target_not_less():
    with pytest.raises(ValueError, match="must be less than start"):
        _compute(50, 50, 100, "decrease")


# ===========================================================================
# compute_goal_progress with full Goal objects
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
    assert result == pytest.approx(37.5)


def test_metric_goal_missing_current():
    g = Goal(
        title="X",
        metric_name="Savings",
        start_value=0,
        current_value=None,
        target_value=10000,
        direction="increase",
    )
    result = compute_goal_progress(g)
    assert result is None


def test_metric_goal_missing_start():
    g = Goal(
        title="X",
        metric_name="Savings",
        start_value=None,
        current_value=5000,
        target_value=10000,
        direction="increase",
    )
    result = compute_goal_progress(g)
    assert result is None


def test_metric_goal_missing_target():
    g = Goal(
        title="X",
        metric_name="Savings",
        start_value=0,
        current_value=5000,
        target_value=None,
        direction="increase",
    )
    result = compute_goal_progress(g)
    assert result is None


def test_metric_goal_missing_direction():
    g = Goal(
        title="X",
        metric_name="Savings",
        start_value=0,
        current_value=5000,
        target_value=10000,
        direction=None,
    )
    result = compute_goal_progress(g)
    assert result is None


def test_task_based_goal():
    g = Goal(
        title="Japan trip",
        related_tasks=["Buy flights", "Book hotels", "Plan itinerary"],
    )
    result = compute_goal_progress(g)
    assert result is None  # no completed_task_titles provided


def test_no_metric_no_tasks():
    g = Goal(title="Simple goal")
    result = compute_goal_progress(g)
    assert result is None


def test_completed_goal():
    g = Goal(
        title="Done",
        status="completed",
        metric_name="X",
        start_value=0,
        current_value=100,
        target_value=100,
        direction="increase",
    )
    result = compute_goal_progress(g)
    assert result is None


def test_inactive_goal():
    g = Goal(
        title="Paused",
        status="inactive",
        metric_name="X",
        start_value=0,
        current_value=50,
        target_value=100,
        direction="increase",
    )
    result = compute_goal_progress(g)
    assert result is None


def test_metric_plus_tasks_metric_prioritizes():
    g = Goal(
        title="Hybrid",
        metric_name="Savings",
        start_value=0,
        current_value=5000,
        target_value=10000,
        direction="increase",
        related_tasks=["Task A", "Task B"],
    )
    # Both tasks completed -> task-based would be 100%, but metric should win
    result = compute_goal_progress(g, completed_task_titles={"Task A", "Task B"})
    assert result == pytest.approx(50.0)  # metric: 5000/10000 = 50%


def test_goal_with_completed_task_titles():
    g = Goal(
        title="Trip",
        related_tasks=["Buy flights", "Book hotels", "Plan itinerary"],
    )
    result = compute_goal_progress(g, completed_task_titles={"Buy flights"})
    assert result == pytest.approx(100.0 / 3)


def test_goal_without_completed_task_titles():
    g = Goal(
        title="Trip",
        related_tasks=["A", "B", "C"],
    )
    result = compute_goal_progress(g, completed_task_titles=None)
    assert result is None  # task path not taken without titles


# ===========================================================================
# Task-based progress (direct function)
# ===========================================================================


def test_task_based_one_of_three():
    result = _compute_task_based(1, ["A", "B", "C"])
    assert result == pytest.approx(100.0 / 3)


def test_task_based_all_complete():
    result = _compute_task_based(3, ["A", "B", "C"])
    assert result == 100.0


def test_task_based_none_complete():
    result = _compute_task_based(0, ["A", "B", "C"])
    assert result == 0.0


def test_task_based_invalid_count_negative():
    with pytest.raises(ValueError, match="between 0 and"):
        _compute_task_based(-1, ["A", "B", "C"])


def test_task_based_invalid_count_over():
    with pytest.raises(ValueError, match="between 0 and"):
        _compute_task_based(4, ["A", "B", "C"])


def test_task_based_empty_tasks():
    with pytest.raises(ValueError, match="non-empty"):
        _compute_task_based(0, [])
