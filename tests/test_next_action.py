"""Tests for the next-action derivation engine (R1-R5).

Task-to-milestone membership is derived dynamically (not stored) per
ADR-003 Q3: a shared task "belongs to" whichever non-terminal milestone
is earliest in ``order``. All tasks in goal.related_tasks are shared
across milestones — they belong to the earliest non-terminal milestone
at derivation time.
"""

import pytest

from datetime import date

from janus.models.goal import Goal
from janus.models.task import Task
from janus.services.next_action import derive_next_action, NextAction


FIXED_TODAY = date(2026, 8, 28)


def _make_task(title: str) -> Task:
    return Task(title=title, due_date=None, priority=1)


def _make_goal(title: str, related_tasks: list[str], milestones=None) -> Goal:
    return Goal(title=title, status="active",
                related_tasks=related_tasks,
                milestones=milestones or [])


class TestR1_OpenTaskInCurrentMilestone:
    def test_r1_returns_task_in_current_milestone(self):
        """R1: open task in the earliest non-terminal milestone is picked."""
        goal = _make_goal("G", ["Task A", "Task B"], milestones=[{
            "title": "M1", "goal_title": "G", "description": "",
            "deadline": None, "status": "open", "order": 0,
        }])
        tasks = [_make_task("Task A")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is not None
        assert action.kind == "task"
        assert action.title == "Task A"
        assert "M1" in action.reason

    def test_r1_skips_tasks_in_completed_milestone(self):
        """R1 should NOT select the current active milestone (M1 is completed,
        M2 is open — tasks belong to M2 dynamically)."""
        goal = _make_goal("G", ["Task A"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "",
             "deadline": None, "status": "completed", "order": 0},
            {"title": "M2", "goal_title": "G", "description": "",
             "deadline": None, "status": "open", "order": 1},
        ])
        tasks = [_make_task("Task A")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        # Task A is shared — belongs to M2 (earliest non-terminal milestone)
        assert action is not None
        assert action.title == "Task A"
        assert "M2" in action.reason

    def test_r1_picks_first_open_task_in_related_tasks_order(self):
        """R1 picks the first open task from goal.related_tasks (in order)
        that belongs to the current active milestone."""
        goal = _make_goal("G", ["Task A", "Task B"], milestones=[{
            "title": "M1", "goal_title": "G", "description": "",
            "deadline": None, "status": "open", "order": 0,
        }])
        tasks = [_make_task("Task A"), _make_task("Task B")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is not None
        assert action.title == "Task A"
        assert "milestone" in action.reason.lower()


class TestR2_OpenTaskOutsideMilestone:
    def test_r2_returns_task_not_in_any_milestone(self):
        """R2: an open task not in goal.related_tasks is not considered.
        Only goal.related_tasks tasks are candidates. With no open
        related tasks, R3 surfaces the next milestone."""
        goal = _make_goal("G", ["Task A"], milestones=[{
            "title": "M1", "goal_title": "G", "description": "",
            "deadline": None, "status": "open", "order": 0,
        }])
        # Task B is open but NOT in related_tasks — not a candidate.
        tasks = [_make_task("Task B")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        # No open related task → R3 returns M1 as next milestone
        assert action is not None
        assert action.kind == "milestone"
        assert action.title == "M1"


    def test_r2_no_milestones_first_open_task(self):
        """R2 fallback when goal has no milestones at all."""
        goal = _make_goal("G", ["Task A", "Task B"])
        tasks = [_make_task("Task A"), _make_task("Task B")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is not None
        assert action.kind == "task"
        assert action.title == "Task A"

    def test_r2_no_milestones_all_completed(self):
        """R2 with no milestones, all tasks completed → None (R5)."""
        goal = _make_goal("G", ["Task A"])
        tasks = []
        completed = {"Task A"}
        action = derive_next_action(goal, tasks, completed, FIXED_TODAY)
        assert action is None


class TestR3_NextOpenMilestone:
    def test_r3_returns_next_open_milestone(self):
        """No open tasks, but an open milestone exists."""
        goal = _make_goal("G", [], milestones=[{
            "title": "M1", "goal_title": "G", "description": "",
            "deadline": None, "status": "open", "order": 0,
        }])
        tasks = []
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is not None
        assert action.kind == "milestone"
        assert action.title == "M1"
        assert "not yet reached" in action.reason.lower()

    def test_r3_skips_completed_milestones(self):
        goal = _make_goal("G", [], milestones=[
            {"title": "M1", "goal_title": "G", "description": "",
             "deadline": None, "status": "completed", "order": 0},
            {"title": "M2", "goal_title": "G", "description": "",
             "deadline": None, "status": "open", "order": 1},
        ])
        tasks = []
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is not None
        assert action.title == "M2"


class TestR4_FirstUncompletedMilestone:
    def test_r4_returns_open_milestone_after_completed(self):
        """All milestones completed/skipped, but an 'open' one remains in
        the list beyond the completed ones."""
        goal = _make_goal("G", [], milestones=[
            {"title": "M1", "goal_title": "G", "description": "",
             "deadline": None, "status": "completed", "order": 0},
            {"title": "M2", "goal_title": "G", "description": "",
             "deadline": None, "status": "open", "order": 1},
        ])
        tasks = []
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        # M2 is "open" so _first_active_milestone returns it (R3 path)
        assert action is not None
        assert action.title == "M2"

    def test_r4_all_skipped_returns_none(self):
        """All milestones skipped, no open tasks → None."""
        goal = _make_goal("G", ["Task A"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "",
             "deadline": None, "status": "skipped", "order": 0},
        ])
        tasks = []
        completed = {"Task A"}
        action = derive_next_action(goal, tasks, completed, FIXED_TODAY)
        assert action is None

    def test_r4_in_progress_milestone_is_current(self):
        """An in_progress milestone is also 'active' — R1/R3 use it."""
        goal = _make_goal("G", ["Task A"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "",
             "deadline": None, "status": "in_progress", "order": 0},
        ])
        tasks = [_make_task("Task A")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is not None
        assert action.kind == "task"
        assert action.title == "Task A"

    def test_shared_task_in_current_and_future_milestone(self):
        """A task in the goal's related_tasks is shared across all milestones.
        It belongs to the earliest non-terminal milestone (M1 if open)."""
        goal = _make_goal("G", ["Task A"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "",
             "deadline": None, "status": "open", "order": 0},
            {"title": "M2", "goal_title": "G", "description": "",
             "deadline": None, "status": "open", "order": 1},
        ])
        tasks = [_make_task("Task A")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is not None
        assert action.title == "Task A"
        assert "M1" in action.reason  # current (earliest non-terminal) milestone

    def test_task_in_completed_milestone_falls_to_r2(self):
        """When all milestones are completed/skipped, open related tasks
        have no active milestone to belong to. They fall through to R2 as
        'No milestone' tasks."""
        goal = _make_goal("G", ["Task A"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "",
             "deadline": None, "status": "completed", "order": 0},
        ])
        tasks = [_make_task("Task A")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        # No active milestone → Task A falls to R2 as "No milestone"
        assert action is not None
        assert action.kind == "task"
        assert action.title == "Task A"
        assert "No milestone" in action.reason


class TestR5_NoNextAction:
    def test_r5_all_completed_no_open_tasks(self):
        """All milestones completed, no open tasks → None."""
        goal = _make_goal("G", ["Task A"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "",
             "deadline": None, "status": "completed", "order": 0},
        ])
        tasks = []
        completed = {"Task A"}
        action = derive_next_action(goal, tasks, completed, FIXED_TODAY)
        assert action is None

    def test_r5_all_skipped_no_open_tasks(self):
        """All milestones skipped, no open tasks → None."""
        goal = _make_goal("G", ["Task A"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "",
             "deadline": None, "status": "skipped", "order": 0},
        ])
        tasks = []
        completed = {"Task A"}
        action = derive_next_action(goal, tasks, completed, FIXED_TODAY)
        assert action is None


class TestNoMilestonesFallback:
    def test_goal_without_milestones_falls_back_to_r2(self):
        goal = _make_goal("G", ["Task A"])
        tasks = [_make_task("Task A")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is not None
        assert action.kind == "task"
        assert action.title == "Task A"

    def test_goal_without_milestones_all_done_returns_none(self):
        goal = _make_goal("G", ["Task A"])
        tasks = []
        completed = {"Task A"}
        action = derive_next_action(goal, tasks, completed, FIXED_TODAY)
        assert action is None

    def test_goal_without_milestones_no_tasks_returns_none(self):
        goal = _make_goal("G", [])
        tasks = []
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is None


class TestRelatedTasksOrdering:
    def test_first_open_task_selected_by_related_tasks_order(self):
        """Regression: with multiple open related tasks, derive_next_action()
        selects the first open task according to goal.related_tasks order,
        not the order tasks are supplied."""
        # Deliberately non-alphabetical order in related_tasks
        goal = _make_goal("G", ["Task C", "Task A", "Task B"])
        # Tasks passed in a different order than goal.related_tasks
        tasks = [
            _make_task("Task A"),
            _make_task("Task B"),
            _make_task("Task C"),
        ]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is not None
        assert action.kind == "task"
        # Must follow goal.related_tasks order: Task C is first
        assert action.title == "Task C"


class TestNextActionDataclass:
    def test_score_defaults_to_zero(self):
        a = NextAction(title="X", kind="task", reason="r", goal_title="G")
        assert a.score == 0

    def test_all_fields(self):
        a = NextAction(title="X", kind="milestone", reason="r",
                        goal_title="G", score=5)
        assert a.kind == "milestone"
        assert a.score == 5
