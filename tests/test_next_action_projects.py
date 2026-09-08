"""Tests for project-aware next-action derivation (spec §9, §10).

Covers the P1-P7 priority ordering for goals that have Projects:
  P1 — Current Project has an open Task  -> Task
  P2 — Current Milestone has unassigned open Task -> Task (legacy derivation)
  P3 — Current Project has no open Tasks -> Project
  P4 — Next Milestone has an eligible Project -> Project
  P5 — Next Milestone has unassigned open Task -> Task
  P6 — Next Milestone exists, no actionable Project/Task -> Milestone
  P7 — Nothing actionable -> None

Also verifies D9: goals without Projects use R1-R5 unchanged.
"""
from datetime import date

import pytest

from janus.models.goal import Goal
from janus.models.task import Task
from janus.models.project import Project
from janus.services.next_action import (
    NextAction,
    _project_objs,
    derive_next_action,
)
from janus.services.projects import add_project_for_milestone
from janus.integrations.markdown_goals import load_goals

FIXED_TODAY = date(2026, 8, 28)


def _task(title):
    return Task(title=title, due_date=None, priority=1)


def _setup(tmp_path, monkeypatch, goals_content):
    goals_file = tmp_path / "goals.md"
    goals_file.write_text(goals_content)
    monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
    tasks_file = tmp_path / "tasks.md"
    tasks_file.write_text("")
    monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)


# ── P1: Current Project has an open Task ──────────────────────────────────

class TestP1_ProjectOpenTask:
    def test_p1_returns_first_open_task_in_project(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n"
            "- Task A\n- Task B\n"
            "## Milestones\n### Milestone: M1 (order: 0)\nStatus: in_progress\n")
        add_project_for_milestone("G", "M1", "P1",
                                  related_tasks=["Task A", "Task B"],
                                  status="active")
        goal = load_goals()[0]
        tasks = [_task("Task A"), _task("Task B")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY,
                                    projects=_project_objs(goal))
        assert action.kind == "task"
        assert action.title == "Task A"
        assert "P1" in action.reason

    def test_p1_project_task_ordering_respected(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n"
            "- Task A\n- Task B\n"
            "## Milestones\n### Milestone: M1 (order: 0)\nStatus: in_progress\n")
        add_project_for_milestone("G", "M1", "P1",
                                  related_tasks=["Task B", "Task A"],
                                  status="active")
        goal = load_goals()[0]
        tasks = [_task("Task A"), _task("Task B")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY,
                                    projects=_project_objs(goal))
        assert action.title == "Task B"  # first in project's order

    def test_p1_skips_completed_task(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n"
            "- Task A\n- Task B\n"
            "## Milestones\n### Milestone: M1 (order: 0)\nStatus: in_progress\n")
        add_project_for_milestone("G", "M1", "P1",
                                  related_tasks=["Task A", "Task B"],
                                  status="active")
        goal = load_goals()[0]
        tasks = [_task("Task B")]
        action = derive_next_action(goal, tasks, {"Task A"}, FIXED_TODAY,
                                    projects=_project_objs(goal))
        assert action.kind == "task"
        assert action.title == "Task B"

    def test_p1_project_assignment_overrides_dynamic(self, tmp_path, monkeypatch):
        """I6/D4: an explicitly assigned task is returned from its Project,
        not via legacy dynamic derivation."""
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n"
            "- Task A\n"
            "## Milestones\n### Milestone: M1 (order: 0)\nStatus: in_progress\n"
            "### Milestone: M2 (order: 1)\nStatus: open\n")
        add_project_for_milestone("G", "M1", "P1",
                                  related_tasks=["Task A"],
                                  status="active")
        goal = load_goals()[0]
        tasks = [_task("Task A")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY,
                                    projects=_project_objs(goal))
        assert action.kind == "task"
        assert action.title == "Task A"
        assert "P1" in action.reason


# ── P3: Current Project has no open Tasks ──────────────────────────────────

class TestP3_ProjectNoOpenTasks:
    def test_p3_returns_project_when_all_tasks_completed(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n"
            "- Task A\n"
            "## Milestones\n### Milestone: M1 (order: 0)\nStatus: in_progress\n")
        add_project_for_milestone("G", "M1", "P1",
                                  related_tasks=["Task A"],
                                  status="active")
        goal = load_goals()[0]
        action = derive_next_action(goal, [], {"Task A"}, FIXED_TODAY,
                                    projects=_project_objs(goal))
        assert action.kind == "project"
        assert action.title == "P1"

    def test_p3_returns_project_when_no_tasks_assigned(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n"
            "- Task A\n"
            "## Milestones\n### Milestone: M1 (order: 0)\nStatus: in_progress\n")
        add_project_for_milestone("G", "M1", "P1", status="active")
        goal = load_goals()[0]
        tasks = [_task("Task A")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY,
                                    projects=_project_objs(goal))
        # P1 exists, is non-terminal, but has no tasks.
        # The engine returns P3 (project) because a project exists in the
        # current milestone but has no open tasks — the project itself
        # becomes the actionable unit.
        assert action.kind == "project"
        assert action.title == "P1"


# ── P2: Current Milestone has unassigned open Task ──────────────────────────

class TestP2_UnassignedTaskInMilestone:
    def test_p2_returns_unassigned_task(self, tmp_path, monkeypatch):
        """P2: current milestone with no project returns unassigned open task."""
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n"
            "- Task A\n- Task B\n"
            "## Milestones\n### Milestone: M1 (order: 0)\nStatus: in_progress\n"
            "### Milestone: M2 (order: 1)\nStatus: open\n")
        # Project only in M2, not M1
        add_project_for_milestone("G", "M2", "P2", status="active")
        goal = load_goals()[0]
        tasks = [_task("Task A"), _task("Task B")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY,
                                    projects=_project_objs(goal))
        # M1 is current but has no project — P2 returns unassigned open task
        assert action.kind == "task"
        assert action.title == "Task A"
        assert "M1" in action.reason

    def test_p2_task_assigned_to_project_not_treated_as_dynamic(self, tmp_path, monkeypatch):
        """A task assigned to a terminal project is NOT available via P2."""
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n"
            "- Task A\n- Task B\n"
            "## Milestones\n### Milestone: M1 (order: 0)\nStatus: in_progress\n")
        add_project_for_milestone("G", "M1", "P1",
                                  related_tasks=["Task A"],
                                  status="completed")
        goal = load_goals()[0]
        tasks = [_task("Task A"), _task("Task B")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY,
                                    projects=_project_objs(goal))
        # Task A is assigned to a terminal project -> excluded from P2.
        # Task B is unassigned and in the current milestone -> returned.
        assert action is not None
        assert action.title == "Task B"


# ── P4: Next Milestone has an eligible Project ──────────────────────────────

class TestP4_NextMilestoneProject:
    def test_p4_returns_next_milestone_project(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n"
            "## Milestones\n"
            "### Milestone: M1 (order: 0)\nStatus: open\n"
            "### Milestone: M2 (order: 1)\nStatus: open\n")
        add_project_for_milestone("G", "M2", "P2", status="active")
        goal = load_goals()[0]
        action = derive_next_action(goal, [], set(), FIXED_TODAY,
                                    projects=_project_objs(goal))
        assert action.kind == "project"
        assert action.title == "P2"
        assert "M2" in action.reason

    def test_p4_skips_terminal_projects_in_next_milestone(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n"
            "## Milestones\n"
            "### Milestone: M1 (order: 0)\nStatus: open\n"
            "### Milestone: M2 (order: 1)\nStatus: open\n")
        add_project_for_milestone("G", "M2", "P2a", status="completed")
        add_project_for_milestone("G", "M2", "P2b", status="active")
        goal = load_goals()[0]
        action = derive_next_action(goal, [], set(), FIXED_TODAY,
                                    projects=_project_objs(goal))
        assert action.title == "P2b"


# ── P6/P7: No next action ───────────────────────────────────────────────────

class TestP6_P7_NoAction:
    def test_p7_returns_none_when_all_milestones_terminal(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n"
            "## Milestones\n"
            "### Milestone: M1 (order: 0)\nStatus: completed\n")
        add_project_for_milestone("G", "M1", "P1", status="completed")
        goal = load_goals()[0]
        action = derive_next_action(goal, [], set(), FIXED_TODAY,
                                    projects=_project_objs(goal))
        assert action is None

    def test_p6_returns_milestone_when_no_projects(self, tmp_path, monkeypatch):
        """Next milestone with no projects -> milestone as action."""
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n"
            "## Milestones\n"
            "### Milestone: M1 (order: 0)\nStatus: completed\n"
            "### Milestone: M2 (order: 1)\nStatus: open\n")
        # No projects — falls through to R3/R4
        goal = load_goals()[0]
        action = derive_next_action(goal, [], set(), FIXED_TODAY,
                                    projects=_project_objs(goal))
        # No projects, so legacy behavior: M2 is next milestone
        assert action is not None
        assert action.kind == "milestone"
        assert action.title == "M2"


# ── D9: Legacy compatibility ────────────────────────────────────────────────

class TestLegacyCompatibility:
    def test_no_projects_uses_legacy_r1(self, tmp_path, monkeypatch):
        """Goals without Projects use R1-R5 unchanged (D9)."""
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n"
            "- Task A\n"
            "## Milestones\n### Milestone: M1 (order: 0)\nStatus: in_progress\n")
        goal = load_goals()[0]
        tasks = [_task("Task A")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        # No projects passed → legacy path
        assert action is not None
        assert action.kind == "task"
        assert action.title == "Task A"
        assert "M1" in action.reason

    def test_empty_projects_uses_legacy(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n"
            "- Task A\n"
            "## Milestones\n### Milestone: M1 (order: 0)\nStatus: in_progress\n")
        goal = load_goals()[0]
        tasks = [_task("Task A")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY, projects=[])
        assert action is not None
        assert action.title == "Task A"

    def test_goal_with_empty_projects_list_uses_legacy(self, tmp_path, monkeypatch):
        """Even if projects param is passed, an empty list triggers legacy."""
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n"
            "- Task A\n"
            "## Milestones\n### Milestone: M1 (order: 0)\nStatus: in_progress\n")
        goal = load_goals()[0]
        tasks = [_task("Task A")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY,
                                    projects=_project_objs(goal))
        # Goal has no projects -> _project_objs returns [] -> legacy
        assert action is not None
        assert action.title == "Task A"
