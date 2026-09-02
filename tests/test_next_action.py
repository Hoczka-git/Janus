"""Tests for the next-action derivation engine (R1-R5)."""

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
        goal = _make_goal("G", ["Task A", "Task B"], milestones=[{
            "title": "M1", "goal_title": "G", "description": "",
            "deadline": None, "status": "open",
            "related_tasks": ["Task A"], "order": 0,
        }])
        tasks = [_make_task("Task A")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is not None
        assert action.kind == "task"
        assert action.title == "Task A"
        assert "M1" in action.reason

    def test_r1_skips_tasks_in_future_milestone(self):
        """R1 should NOT select a task that's only in a future (completed) milestone."""
        goal = _make_goal("G", ["Task A"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "",
             "deadline": None, "status": "completed",
             "related_tasks": [], "order": 0},
            {"title": "M2", "goal_title": "G", "description": "",
             "deadline": None, "status": "open",
             "related_tasks": ["Task A"], "order": 1},
        ])
        tasks = [_make_task("Task A")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        # Task A is in M2 (current open milestone), so R1 should pick it
        assert action is not None
        assert action.title == "Task A"
        assert "M2" in action.reason

    def test_r1_prefers_current_milestone_task_over_goal_task(self):
        """If a task is in both the current milestone and goal.related_tasks,
        R1 picks it as a milestone task, not as a bare goal task."""
        goal = _make_goal("G", ["Task A", "Task B"], milestones=[{
            "title": "M1", "goal_title": "G", "description": "",
            "deadline": None, "status": "open",
            "related_tasks": ["Task A"], "order": 0,
        }])
        tasks = [_make_task("Task A"), _make_task("Task B")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is not None
        assert action.title == "Task A"
        assert "milestone" in action.reason.lower()


class TestR2_OpenTaskOutsideMilestone:
    def test_r2_returns_task_not_in_any_milestone(self):
        goal = _make_goal("G", ["Task A", "Task B"], milestones=[{
            "title": "M1", "goal_title": "G", "description": "",
            "deadline": None, "status": "open",
            "related_tasks": ["Task A"], "order": 0,
        }])
        tasks = [_make_task("Task B")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is not None
        assert action.kind == "task"
        assert action.title == "Task B"
        assert "No milestone" in action.reason

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
            "deadline": None, "status": "open",
            "related_tasks": [], "order": 0,
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
             "deadline": None, "status": "completed",
             "related_tasks": [], "order": 0},
            {"title": "M2", "goal_title": "G", "description": "",
             "deadline": None, "status": "open",
             "related_tasks": [], "order": 1},
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
             "deadline": None, "status": "completed",
             "related_tasks": [], "order": 0},
            {"title": "M2", "goal_title": "G", "description": "",
             "deadline": None, "status": "open",
             "related_tasks": [], "order": 1},
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
             "deadline": None, "status": "skipped",
             "related_tasks": ["Task A"], "order": 0},
        ])
        tasks = []
        completed = {"Task A"}
        action = derive_next_action(goal, tasks, completed, FIXED_TODAY)
        assert action is None

    def test_r4_in_progress_milestone_is_current(self):
        """An in_progress milestone is also 'active' — R1/R3 use it."""
        goal = _make_goal("G", ["Task A"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "",
             "deadline": None, "status": "in_progress",
             "related_tasks": ["Task A"], "order": 0},
        ])
        tasks = [_make_task("Task A")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is not None
        assert action.kind == "task"
        assert action.title == "Task A"

    def test_shared_task_in_current_and_future_milestone(self):
        """A task in both current and future milestone is assigned to current."""
        goal = _make_goal("G", ["Task A"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "",
             "deadline": None, "status": "open",
             "related_tasks": ["Task A"], "order": 0},
            {"title": "M2", "goal_title": "G", "description": "",
             "deadline": None, "status": "open",
             "related_tasks": ["Task A"], "order": 1},
        ])
        tasks = [_make_task("Task A")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is not None
        assert action.title == "Task A"
        assert "M1" in action.reason  # current milestone, not M2

    def test_task_in_completed_milestone_not_picked_by_r2(self):
        """A task in a completed milestone is in a milestone, so R2 skips it."""
        goal = _make_goal("G", ["Task A"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "",
             "deadline": None, "status": "completed",
             "related_tasks": ["Task A"], "order": 0},
        ])
        tasks = [_make_task("Task A")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        # Task A is in M1 (completed), so R1 finds no current active milestone.
        # R2 skips it (it IS in a milestone). R3 has no active milestone.
        # R4 finds no open/in_progress milestone. R5 returns None.
        assert action is None


class TestR5_NoNextAction:
    def test_r5_all_completed_no_open_tasks(self):
        """All milestones completed, no open tasks → None."""
        goal = _make_goal("G", ["Task A"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "",
             "deadline": None, "status": "completed",
             "related_tasks": ["Task A"], "order": 0},
        ])
        tasks = []
        completed = {"Task A"}
        action = derive_next_action(goal, tasks, completed, FIXED_TODAY)
        assert action is None

    def test_r5_all_skipped_no_open_tasks(self):
        """All milestones skipped, no open tasks → None."""
        goal = _make_goal("G", ["Task A"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "",
             "deadline": None, "status": "skipped",
             "related_tasks": ["Task A"], "order": 0},
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


class TestNextActionDataclass:
    def test_score_defaults_to_zero(self):
        a = NextAction(title="X", kind="task", reason="r", goal_title="G")
        assert a.score == 0

    def test_all_fields(self):
        a = NextAction(title="X", kind="milestone", reason="r",
                        goal_title="G", score=5)
        assert a.kind == "milestone"
        assert a.score == 5
