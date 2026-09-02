"""Targeted tests for the dynamic shared-task derivation logic.

These tests cover ``derive_milestone_tasks`` and ``derive_milestone_task_set``
in ``src/janus/services/next_action.py``, which implement ADR-003 Q3:
shared tasks are NOT permanently assigned to milestones. Instead, a shared
task "belongs to" whichever non-terminal milestone is earliest in ``order``.
As earlier milestones complete or are skipped, the task becomes eligible
for the next non-terminal milestone.

Task membership is derived purely from:
  - ``goal.related_tasks`` (the canonical list of supporting tasks)
  - the current milestone statuses (open | in_progress = non-terminal)
  - ``open_task_titles`` (which of those tasks are currently open)
"""

from datetime import date

import pytest

from janus.models.goal import Goal
from janus.models.milestone import Milestone
from janus.models.task import Task
from janus.services.next_action import (
    derive_milestone_tasks,
    derive_milestone_task_set,
    _milestone_objs,
    _first_non_terminal_milestone,
    _first_active_milestone,
)


FIXED_TODAY = date(2026, 8, 28)


def _mk_milestone(title, status="open", order=0, goal_title="G"):
    return Milestone(
        title=title, goal_title=goal_title, status=status, order=order,
    )


def _make_goal(title="G", related_tasks=None, milestone_dicts=None):
    return Goal(
        title=title,
        status="active",
        related_tasks=related_tasks or [],
        milestones=milestone_dicts or [],
    )


# ── _first_non_terminal_milestone ───────────────────────────────────────────

class TestFirstNonTerminalMilestone:
    def test_returns_first_open_milestone(self):
        mss = [
            _mk_milestone("M1", status="open", order=0),
            _mk_milestone("M2", status="open", order=1),
        ]
        result = _first_non_terminal_milestone(mss)
        assert result is not None
        assert result.title == "M1"

    def test_returns_first_in_progress_milestone(self):
        mss = [
            _mk_milestone("M1", status="in_progress", order=0),
            _mk_milestone("M2", status="open", order=1),
        ]
        result = _first_non_terminal_milestone(mss)
        assert result is not None
        assert result.title == "M1"

    def test_skips_completed_milestones(self):
        mss = [
            _mk_milestone("M1", status="completed", order=0),
            _mk_milestone("M2", status="open", order=1),
        ]
        result = _first_non_terminal_milestone(mss)
        assert result is not None
        assert result.title == "M2"

    def test_skips_skipped_milestones(self):
        mss = [
            _mk_milestone("M1", status="skipped", order=0),
            _mk_milestone("M2", status="open", order=1),
        ]
        result = _first_non_terminal_milestone(mss)
        assert result is not None
        assert result.title == "M2"

    def test_returns_none_when_all_completed(self):
        mss = [
            _mk_milestone("M1", status="completed", order=0),
            _mk_milestone("M2", status="completed", order=1),
        ]
        result = _first_non_terminal_milestone(mss)
        assert result is None

    def test_returns_none_when_all_skipped(self):
        mss = [
            _mk_milestone("M1", status="skipped", order=0),
            _mk_milestone("M2", status="skipped", order=1),
        ]
        result = _first_non_terminal_milestone(mss)
        assert result is None

    def test_returns_none_for_empty_list(self):
        assert _first_non_terminal_milestone([]) is None


# ── _first_active_milestone (alias) ─────────────────────────────────────────

class TestFirstActiveMilestone:
    def test_same_behavior_as_non_terminal(self):
        """_first_active_milestone is the same as _first_non_terminal_milestone."""
        mss = [
            _mk_milestone("M1", status="completed", order=0),
            _mk_milestone("M2", status="open", order=1),
        ]
        assert _first_active_milestone(mss) is _first_non_terminal_milestone(mss)


# ── derive_milestone_tasks ──────────────────────────────────────────────────

class TestDeriveMilestoneTasks:
    """Test the dynamic derivation of which tasks belong to a specific milestone."""

    def test_tasks_assigned_to_active_milestone(self):
        """When the milestone IS the earliest non-terminal, all open related
        tasks are assigned to it."""
        m1 = _mk_milestone("M1", status="open", order=0)
        mss = [m1]
        goal = _make_goal(related_tasks=["Task A", "Task B"])
        open_titles = {"Task A", "Task B"}

        result = derive_milestone_tasks(m1, mss, goal, open_titles)
        assert result == ["Task A", "Task B"]

    def test_tasks_not_assigned_to_completed_milestone(self):
        """When the milestone is NOT the earliest non-terminal (it's completed),
        no tasks are assigned to it."""
        m1 = _mk_milestone("M1", status="completed", order=0)
        m2 = _mk_milestone("M2", status="open", order=1)
        mss = [m1, m2]
        goal = _make_goal(related_tasks=["Task A", "Task B"])
        open_titles = {"Task A", "Task B"}

        result = derive_milestone_tasks(m1, mss, goal, open_titles)
        assert result == []

    def test_tasks_assigned_to_second_milestone_when_first_completed(self):
        """After M1 completes, tasks dynamically move to M2 (earliest non-terminal)."""
        m1 = _mk_milestone("M1", status="completed", order=0)
        m2 = _mk_milestone("M2", status="open", order=1)
        mss = [m1, m2]
        goal = _make_goal(related_tasks=["Task A"])
        open_titles = {"Task A"}

        result = derive_milestone_tasks(m2, mss, goal, open_titles)
        assert result == ["Task A"]

    def test_completed_milestone_gets_no_tasks_after_completion(self):
        """M1 is completed → tasks move to M2. M1 gets no tasks."""
        m1 = _mk_milestone("M1", status="completed", order=0)
        m2 = _mk_milestone("M2", status="open", order=1)
        mss = [m1, m2]
        goal = _make_goal(related_tasks=["Task A"])
        open_titles = {"Task A"}

        assert derive_milestone_tasks(m1, mss, goal, open_titles) == []
        assert derive_milestone_tasks(m2, mss, goal, open_titles) == ["Task A"]

    def test_only_open_related_tasks_returned(self):
        """Closed (completed) related tasks are not returned even when they
        would belong to the active milestone."""
        m1 = _mk_milestone("M1", status="open", order=0)
        mss = [m1]
        goal = _make_goal(related_tasks=["Task A", "Task B", "Task C"])
        open_titles = {"Task A", "Task C"}  # Task B is not open

        result = derive_milestone_tasks(m1, mss, goal, open_titles)
        assert set(result) == {"Task A", "Task C"}

    def test_no_non_terminal_milestone_returns_empty(self):
        """If all milestones are terminal, no milestone gets tasks."""
        m1 = _mk_milestone("M1", status="completed", order=0)
        mss = [m1]
        goal = _make_goal(related_tasks=["Task A"])
        open_titles = {"Task A"}

        result = derive_milestone_tasks(m1, mss, goal, open_titles)
        assert result == []

    def test_no_milestones_returns_empty(self):
        """With no milestones at all, no milestone gets tasks."""
        goal = _make_goal(related_tasks=["Task A"])
        open_titles = {"Task A"}

        result = derive_milestone_tasks(_mk_milestone("X"), [], goal, open_titles)
        assert result == []

    def test_preserves_related_tasks_order(self):
        """Returned tasks preserve goal.related_tasks order."""
        m1 = _mk_milestone("M1", status="open", order=0)
        mss = [m1]
        goal = _make_goal(related_tasks=["Zeta", "Alpha", "Beta"])
        open_titles = {"Zeta", "Alpha", "Beta"}

        result = derive_milestone_tasks(m1, mss, goal, open_titles)
        assert result == ["Zeta", "Alpha", "Beta"]

    def test_skipped_milestone_does_not_get_tasks(self):
        """A skipped (terminal) milestone gets no tasks."""
        m1 = _mk_milestone("M1", status="skipped", order=0)
        m2 = _mk_milestone("M2", status="open", order=1)
        mss = [m1, m2]
        goal = _make_goal(related_tasks=["Task A"])
        open_titles = {"Task A"}

        assert derive_milestone_tasks(m1, mss, goal, open_titles) == []
        assert derive_milestone_tasks(m2, mss, goal, open_titles) == ["Task A"]

    def test_shared_task_between_open_and_future_milestone(self):
        """A task shared between two open milestones belongs to the earliest."""
        m1 = _mk_milestone("M1", status="open", order=0)
        m2 = _mk_milestone("M2", status="open", order=1)
        mss = [m1, m2]
        goal = _make_goal(related_tasks=["Task A"])
        open_titles = {"Task A"}

        assert derive_milestone_tasks(m1, mss, goal, open_titles) == ["Task A"]
        assert derive_milestone_tasks(m2, mss, goal, open_titles) == []


# ── derive_milestone_task_set ───────────────────────────────────────────────

class TestDeriveMilestoneTaskSet:
    """Test the set-level derivation (returns all tasks for the active milestone)."""

    def test_returns_all_open_related_tasks_for_active_milestone(self):
        m1 = _mk_milestone("M1", status="open", order=0)
        mss = [m1]
        goal = _make_goal(related_tasks=["Task A", "Task B"])
        open_titles = {"Task A", "Task B"}

        result = derive_milestone_task_set(mss, goal, open_titles)
        assert result == {"Task A", "Task B"}

    def test_returns_empty_when_all_milestones_terminal(self):
        m1 = _mk_milestone("M1", status="completed", order=0)
        mss = [m1]
        goal = _make_goal(related_tasks=["Task A"])
        open_titles = {"Task A"}

        result = derive_milestone_task_set(mss, goal, open_titles)
        assert result == set()

    def test_returns_empty_when_no_milestones(self):
        goal = _make_goal(related_tasks=["Task A"])
        open_titles = {"Task A"}

        result = derive_milestone_task_set([], goal, open_titles)
        assert result == set()

    def test_returns_empty_when_no_open_tasks(self):
        m1 = _mk_milestone("M1", status="open", order=0)
        mss = [m1]
        goal = _make_goal(related_tasks=["Task A", "Task B"])
        open_titles = set()

        result = derive_milestone_task_set(mss, goal, open_titles)
        assert result == set()

    def test_moves_to_next_milestone_after_completion(self):
        """After M1 completes, M2 becomes the active milestone."""
        m1 = _mk_milestone("M1", status="completed", order=0)
        m2 = _mk_milestone("M2", status="open", order=1)
        mss = [m1, m2]
        goal = _make_goal(related_tasks=["Task A"])
        open_titles = {"Task A"}

        result = derive_milestone_task_set(mss, goal, open_titles)
        assert result == {"Task A"}

    def test_filters_out_closed_related_tasks(self):
        """Tasks in related_tasks that aren't open are excluded."""
        m1 = _mk_milestone("M1", status="open", order=0)
        mss = [m1]
        goal = _make_goal(related_tasks=["Task A", "Task B"])
        open_titles = {"Task A"}

        result = derive_milestone_task_set(mss, goal, open_titles)
        assert result == {"Task A"}


# ── _milestone_objs (backward compat) ───────────────────────────────────────

class TestMilestoneObjsBackwardCompat:
    """Verify that legacy 'related_tasks' key in milestone dicts is filtered
    out, ensuring backward compatibility with old data files."""

    def test_filters_legacy_related_tasks_key(self):
        goal = _make_goal(
            related_tasks=["Task A"],
            milestone_dicts=[{
                "title": "M1",
                "goal_title": "G",
                "description": "",
                "deadline": None,
                "status": "open",
                "related_tasks": ["Task A", "Task B"],
                "order": 0,
            }],
        )
        from janus.models.milestone import Milestone
        mss = _milestone_objs(goal)
        assert len(mss) == 1
        assert not hasattr(mss[0], "related_tasks")

    def test_handles_milestone_dicts_without_related_tasks(self):
        goal = _make_goal(
            related_tasks=["Task A"],
            milestone_dicts=[{
                "title": "M1",
                "goal_title": "G",
                "description": "",
                "deadline": None,
                "status": "open",
                "order": 0,
            }],
        )
        mss = _milestone_objs(goal)
        assert len(mss) == 1
        assert mss[0].title == "M1"
        assert mss[0].status == "open"

    def test_empty_milestones(self):
        goal = _make_goal(related_tasks=["Task A"], milestone_dicts=[])
        mss = _milestone_objs(goal)
        assert mss == []


# ── Integration: dynamic derivation through derive_next_action ──────────────

class TestDynamicDerivationThroughNextAction:
    """Verify the dynamic derivation works end-to-end via derive_next_action."""

    def test_task_moves_to_next_milestone_after_completion(self):
        """When M1 is completed, the shared task dynamically belongs to M2."""
        from janus.services.next_action import derive_next_action

        goal = _make_goal(
            related_tasks=["Task A"],
            milestone_dicts=[
                {"title": "M1", "goal_title": "G", "description": "",
                 "deadline": None, "status": "completed", "order": 0},
                {"title": "M2", "goal_title": "G", "description": "",
                 "deadline": None, "status": "open", "order": 1},
            ],
        )
        tasks = [Task(title="Task A", due_date=None, priority=1)]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is not None
        assert action.title == "Task A"
        assert "M2" in action.reason

    def test_task_falls_to_r2_when_all_milestones_terminal(self):
        """When all milestones are completed, open tasks fall to R2."""
        from janus.services.next_action import derive_next_action

        goal = _make_goal(
            related_tasks=["Task A"],
            milestone_dicts=[
                {"title": "M1", "goal_title": "G", "description": "",
                 "deadline": None, "status": "completed", "order": 0},
            ],
        )
        tasks = [Task(title="Task A", due_date=None, priority=1)]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is not None
        assert action.title == "Task A"
        assert "No milestone" in action.reason

    def test_skipped_milestone_passes_tasks_to_next(self):
        """A skipped milestone is terminal — tasks move to the next."""
        from janus.services.next_action import derive_next_action

        goal = _make_goal(
            related_tasks=["Task A"],
            milestone_dicts=[
                {"title": "M1", "goal_title": "G", "description": "",
                 "deadline": None, "status": "skipped", "order": 0},
                {"title": "M2", "goal_title": "G", "description": "",
                 "deadline": None, "status": "open", "order": 1},
            ],
        )
        tasks = [Task(title="Task A", due_date=None, priority=1)]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is not None
        assert action.title == "Task A"
        assert "M2" in action.reason

    def test_no_active_milestone_surfaces_next_milestone(self):
        """When no open tasks exist, the next open milestone is surfaced (R3)."""
        from janus.services.next_action import derive_next_action

        goal = _make_goal(
            related_tasks=[],
            milestone_dicts=[
                {"title": "M1", "goal_title": "G", "description": "",
                 "deadline": None, "status": "completed", "order": 0},
                {"title": "M2", "goal_title": "G", "description": "",
                 "deadline": None, "status": "open", "order": 1},
            ],
        )
        tasks = []
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is not None
        assert action.kind == "milestone"
        assert action.title == "M2"


    def test_all_milestones_completed_no_tasks_returns_none(self):
        """All milestones completed, all tasks done → no next action (R5)."""
        from janus.services.next_action import derive_next_action

        goal = _make_goal(
            related_tasks=["Task A"],
            milestone_dicts=[
                {"title": "M1", "goal_title": "G", "description": "",
                 "deadline": None, "status": "completed", "order": 0},
                {"title": "M2", "goal_title": "G", "description": "",
                 "deadline": None, "status": "completed", "order": 1},
            ],
        )
        tasks = []
        action = derive_next_action(goal, tasks, {"Task A"}, FIXED_TODAY)
        assert action is None

    def test_dynamic_equality_with_stored_model(self):
        """The dynamic derivation produces the same result as if tasks were
        stored on the active milestone (backward-compatible behavior)."""
        from janus.services.next_action import derive_next_action

        # Old model: tasks stored on milestone
        goal_old = _make_goal(
            related_tasks=["Task A", "Task B"],
            milestone_dicts=[
                {"title": "M1", "goal_title": "G", "description": "",
                 "deadline": None, "status": "open", "order": 0,
                 "related_tasks": ["Task A", "Task B"]},
            ],
        )
        # New model: tasks derived dynamically (no related_tasks on milestone)
        goal_new = _make_goal(
            related_tasks=["Task A", "Task B"],
            milestone_dicts=[
                {"title": "M1", "goal_title": "G", "description": "",
                 "deadline": None, "status": "open", "order": 0},
            ],
        )
        tasks = [Task(title="Task A"), Task(title="Task B")]
        action_old = derive_next_action(goal_old, tasks, set(), FIXED_TODAY)
        action_new = derive_next_action(goal_new, tasks, set(), FIXED_TODAY)
        assert action_old.title == action_new.title
        assert action_old.kind == action_new.kind
