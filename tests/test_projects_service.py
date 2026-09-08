"""Tests for the Project CRUD service.

Covers:
  - Project creation with auto-assigned order (I8, I9)
  - Project retrieval (get_project, get_projects_for_milestone, get_projects_for_goal)
  - Project update (status, description, deadline, add/remove related tasks)
  - Project lifecycle: start, complete, skip, block, reopen (I9)
  - Domain invariants:
      I1: Project must belong to an existing Milestone
      I2: Project title unique within Milestone
      I3: A Task cannot belong to two Projects within one Goal
      I10: Parent references (milestone_title) are immutable in MVP
  - Persistence round-trip (save -> load -> update -> save -> load)
  - Cross-goal task reference warnings (I4)
"""
import logging

import pytest

from janus.models.project import Project
from janus.services.projects import (
    add_project_for_milestone,
    block_project,
    complete_project,
    get_project,
    get_projects_for_goal,
    get_projects_for_milestone,
    reopen_project,
    skip_project,
    start_project,
    update_project,
)
from janus.integrations.markdown_goals import load_goals


def _write_goals_file(tmp_path, content):
    goals_file = tmp_path / "goals.md"
    goals_file.write_text(content)
    return goals_file


def _setup(tmp_path, monkeypatch, goals_content="# Goals\n"):
    goals_file = _write_goals_file(tmp_path, goals_content)
    monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
    return goals_file


_BASE = """# Goals

## Goal: G
Status: active
Related tasks:
- Task A
- Task B
- Task C

## Milestones
### Milestone: M1 (order: 0)
Status: open
Description: First milestone
"""


class TestAddProject:
    def test_create_with_defaults(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        p = add_project_for_milestone("G", "M1", "P1")
        assert p.title == "P1"
        assert p.milestone_title == "M1"
        assert p.status == "open"
        assert p.order == 0
        assert p.related_tasks == []
        assert p.description == ""

    def test_create_with_all_fields(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        p = add_project_for_milestone(
            "G", "M1", "P1",
            description="A project", deadline="2026-10-15",
            status="active", related_tasks=["Task A", "Task B"],
        )
        assert p.description == "A project"
        assert p.deadline == "2026-10-15"
        assert p.status == "active"
        assert p.related_tasks == ["Task A", "Task B"]

    def test_order_auto_assigned_zero(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        p = add_project_for_milestone("G", "M1", "First")
        assert p.order == 0

    def test_order_increments_for_second_project(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "First")
        p = add_project_for_milestone("G", "M1", "Second")
        assert p.order == 1

    def test_order_not_renumbered_on_skip(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "First")
        add_project_for_milestone("G", "M1", "Second")
        skip_project("G", "M1", "First")
        # Second project must retain order 1 (stable, not renumbered)
        projs = get_projects_for_milestone("G", "M1")
        orders = [p.order for p in projs]
        assert orders == [0, 1]

    def test_persisted_after_create(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1", related_tasks=["Task A"])
        goal = load_goals()[0]
        assert len(goal.projects) == 1
        assert goal.projects[0]["title"] == "P1"
        assert goal.projects[0]["milestone_title"] == "M1"

    def test_nonexistent_goal_raises(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        with pytest.raises(ValueError, match="Goal not found"):
            add_project_for_milestone("Ghost", "M1", "P1")

    def test_nonexistent_milestone_raises(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        with pytest.raises(ValueError, match="Milestone not found"):
            add_project_for_milestone("G", "Ghost", "P1")

    def test_duplicate_title_in_same_milestone_raises(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1")
        with pytest.raises(ValueError, match="already exists"):
            add_project_for_milestone("G", "M1", "P1")

    def test_same_title_different_milestones_ok(self, tmp_path, monkeypatch):
        content = _BASE + "### Milestone: M2 (order: 1)\nStatus: open\n"
        _setup(tmp_path, monkeypatch, content)
        add_project_for_milestone("G", "M1", "Research")
        add_project_for_milestone("G", "M2", "Research")
        m1 = get_projects_for_milestone("G", "M1")
        m2 = get_projects_for_milestone("G", "M2")
        assert len(m1) == 1 and m1[0].title == "Research"
        assert len(m2) == 1 and m2[0].title == "Research"

    def test_invalid_status_raises(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        with pytest.raises(ValueError, match="Invalid project status"):
            add_project_for_milestone("G", "M1", "P1", status="pending")

    def test_duplicate_task_assignment_raises(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1", related_tasks=["Task A"])
        with pytest.raises(ValueError, match="already assigned"):
            add_project_for_milestone("G", "M1", "P2", related_tasks=["Task A"])

    def test_cross_goal_task_reference_warns(
        self, tmp_path, monkeypatch, caplog
    ):
        """I4/Q3: a task not in goal.related_tasks produces a warning, not an error."""
        _setup(tmp_path, monkeypatch, _BASE)
        with caplog.at_level(logging.WARNING):
            add_project_for_milestone(
                "G", "M1", "P1", related_tasks=["Task Not In Goal"]
            )
        assert any("not currently in goal.related_tasks" in r.message
                   for r in caplog.records)

    def test_related_tasks_deduped(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        p = add_project_for_milestone(
            "G", "M1", "P1", related_tasks=["Task A", "Task A", "Task B"],
        )
        assert p.related_tasks == ["Task A", "Task B"]


class TestGetProject:
    def test_get_single(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1", related_tasks=["Task A"])
        p = get_project("G", "M1", "P1")
        assert p.title == "P1"
        assert p.related_tasks == ["Task A"]

    def test_get_not_found_raises(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        with pytest.raises(ValueError, match="Project not found"):
            get_project("G", "M1", "Ghost")

    def test_get_projects_for_milestone(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P2")
        add_project_for_milestone("G", "M1", "P1")
        projs = get_projects_for_milestone("G", "M1")
        # ordered by order field
        assert [p.title for p in projs] == ["P2", "P1"]

    def test_get_projects_for_goal(self, tmp_path, monkeypatch):
        content = _BASE + "### Milestone: M2 (order: 1)\nStatus: open\n"
        _setup(tmp_path, monkeypatch, content)
        add_project_for_milestone("G", "M1", "A")
        add_project_for_milestone("G", "M2", "B")
        projs = get_projects_for_goal("G")
        titles = [p.title for p in projs]
        assert "A" in titles and "B" in titles


class TestUpdateProject:
    def test_update_status(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1")
        p = update_project("G", "M1", "P1", status="active")
        assert p.status == "active"
        assert get_project("G", "M1", "P1").status == "active"

    def test_update_description(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1")
        p = update_project("G", "M1", "P1", description="New")
        assert p.description == "New"

    def test_update_deadline(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1")
        p = update_project("G", "M1", "P1", deadline="2026-12-01")
        assert p.deadline == "2026-12-01"

    def test_update_invalid_status_raises(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1")
        with pytest.raises(ValueError, match="Invalid project status"):
            update_project("G", "M1", "P1", status="pending")

    def test_update_add_related_task(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1", related_tasks=["Task A"])
        p = update_project("G", "M1", "P1", add_related_task="Task B")
        assert "Task B" in p.related_tasks
        assert get_project("G", "M1", "P1").related_tasks == ["Task A", "Task B"]

    def test_update_add_duplicate_related_task_noop(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1", related_tasks=["Task A"])
        p = update_project("G", "M1", "P1", add_related_task="Task A")
        assert p.related_tasks == ["Task A"]

    def test_update_add_related_task_rejects_cross_assignment(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1", related_tasks=["Task A"])
        add_project_for_milestone("G", "M1", "P2", related_tasks=["Task B"])
        with pytest.raises(ValueError, match="already assigned"):
            update_project("G", "M1", "P1", add_related_task="Task B")

    def test_update_remove_related_task(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1", related_tasks=["Task A", "Task B"])
        p = update_project("G", "M1", "P1", remove_related_task="Task A")
        assert p.related_tasks == ["Task B"]

    def test_update_remove_nonexistent_task_noop(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1", related_tasks=["Task A"])
        p = update_project("G", "M1", "P1", remove_related_task="Task X")
        assert p.related_tasks == ["Task A"]

    def test_update_parent_reference_rejected(self, tmp_path, monkeypatch):
        """I10: milestone_title is immutable in MVP.

        ``goal_title`` and ``milestone_title`` are positional parameters of
        update_project, so passing them as kwargs is a TypeError — the
        only supported update path for parent references.
        """
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1")
        with pytest.raises(TypeError):
            update_project("G", "M1", "P1", milestone_title="M2")

    def test_update_preserves_other_projects(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1", related_tasks=["Task A"])
        add_project_for_milestone("G", "M1", "P2", related_tasks=["Task B"])
        update_project("G", "M1", "P1", status="completed")
        p2 = get_project("G", "M1", "P2")
        assert p2.related_tasks == ["Task B"]

    def test_round_trip_save_load_update(self, tmp_path, monkeypatch):
        """Spec §21.3 mitigation: save -> load -> update -> save -> load."""
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1", related_tasks=["Task A"])
        # load
        g1 = load_goals()[0]
        assert len(g1.projects) == 1
        # update
        update_project("G", "M1", "P1", status="active", add_related_task="Task B")
        # reload
        g2 = load_goals()[0]
        assert len(g2.projects) == 1
        p = Project(**{k: v for k, v in g2.projects[0].items()
                       if k in ("title", "milestone_title", "description",
                                "deadline", "status", "order", "related_tasks")})
        assert p.status == "active"
        assert p.related_tasks == ["Task A", "Task B"]


class TestProjectLifecycle:
    def test_start_moves_open_to_active(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1")
        p = start_project("G", "M1", "P1")
        assert p.status == "active"

    def test_complete_moves_to_completed(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1")
        p = complete_project("G", "M1", "P1")
        assert p.status == "completed"

    def test_skip_moves_to_skipped(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1")
        p = skip_project("G", "M1", "P1")
        assert p.status == "skipped"

    def test_block_moves_to_blocked(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1")
        p = block_project("G", "M1", "P1")
        assert p.status == "blocked"

    def test_blocked_is_non_terminal(self, tmp_path, monkeypatch):
        """I9: blocked is non-terminal, can transition back to active."""
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1")
        block_project("G", "M1", "P1")
        p = start_project("G", "M1", "P1")
        assert p.status == "active"

    def test_reopen_restores_terminal_to_open(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1")
        complete_project("G", "M1", "P1")
        p = reopen_project("G", "M1", "P1")
        assert p.status == "open"

    def test_reopen_from_skipped(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1")
        skip_project("G", "M1", "P1")
        p = reopen_project("G", "M1", "P1")
        assert p.status == "open"

    def test_complete_persists(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _BASE)
        add_project_for_milestone("G", "M1", "P1")
        complete_project("G", "M1", "P1")
        projs = get_projects_for_milestone("G", "M1")
        assert projs[0].status == "completed"
