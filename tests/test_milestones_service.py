"""Tests for the milestone CRUD service."""

import pytest

from pathlib import Path
from janus.models.goal import Goal
from janus.services.milestones import (
    add_milestone_for_goal,
    get_milestone,
    get_milestones_for_goal,
    update_milestone,
    complete_milestone,
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


class TestAddMilestone:
    def test_add_milestone_auto_order(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n")
        ms = add_milestone_for_goal("G", "M1")
        assert ms.title == "M1"
        assert ms.order == 0
        assert ms.status == "open"

    def test_add_second_milestone_increments_order(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n")
        add_milestone_for_goal("G", "M1")
        ms2 = add_milestone_for_goal("G", "M2")
        assert ms2.order == 1

    def test_add_milestone_with_all_fields(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n")
        ms = add_milestone_for_goal(
            "G", "M1",
            description="A milestone",
            deadline="2026-10-01",
            status="in_progress",
        )
        assert ms.description == "A milestone"
        assert ms.deadline == "2026-10-01"
        assert ms.status == "in_progress"

    def test_add_milestone_persisted(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n")
        add_milestone_for_goal("G", "M1")
        goals = load_goals()
        assert len(goals[0].milestones) == 1
        assert goals[0].milestones[0]["title"] == "M1"

    def test_add_milestone_nonexistent_goal_raises(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="Goal not found"):
            add_milestone_for_goal("Ghost", "M1")

    def test_add_milestone_duplicate_title_raises(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n")
        add_milestone_for_goal("G", "M1")
        with pytest.raises(ValueError, match="Milestone already exists"):
            add_milestone_for_goal("G", "M1")


class TestGetMilestones:
    def test_get_milestones_ordered(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n"
            "## Milestones\n"
            "### Milestone: Second  (order: 1)\n"
            "Description: B\n"
            "### Milestone: First  (order: 0)\n"
            "Description: A\n"
        )
        mss = get_milestones_for_goal("G")
        assert len(mss) == 2
        assert mss[0].title == "First"  # order 0 first
        assert mss[1].title == "Second"

    def test_get_milestones_empty(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n")
        mss = get_milestones_for_goal("G")
        assert mss == []

    def test_get_milestone_single(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n"
            "## Milestones\n"
            "### Milestone: M1  (order: 0)\n"
            "Description: A\n"
        )
        ms = get_milestone("G", "M1")
        assert ms.title == "M1"
        assert ms.description == "A"

    def test_get_milestone_not_found_raises(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n")
        with pytest.raises(ValueError, match="Milestone not found"):
            get_milestone("G", "Ghost")

    def test_get_milestones_nonexistent_goal_raises(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="Goal not found"):
            get_milestones_for_goal("Ghost")


class TestUpdateMilestone:
    def test_update_status(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n"
            "## Milestones\n"
            "### Milestone: M1  (order: 0)\n"
        )
        ms = update_milestone("G", "M1", status="in_progress")
        assert ms.status == "in_progress"

    def test_update_description(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n"
            "## Milestones\n"
            "### Milestone: M1  (order: 0)\n"
        )
        ms = update_milestone("G", "M1", description="New desc")
        assert ms.description == "New desc"

    def test_update_deadline(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n"
            "## Milestones\n"
            "### Milestone: M1  (order: 0)\n"
        )
        ms = update_milestone("G", "M1", deadline="2026-12-01")
        assert ms.deadline == "2026-12-01"

    def test_update_persists_to_file(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n"
            "## Milestones\n"
            "### Milestone: M1  (order: 0)\n"
        )
        update_milestone("G", "M1", status="completed")
        goals = load_goals()
        assert goals[0].milestones[0]["status"] == "completed"

    def test_update_invalid_status_raises(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n"
            "## Milestones\n"
            "### Milestone: M1  (order: 0)\n"
        )
        with pytest.raises(ValueError, match="Invalid milestone status"):
            update_milestone("G", "M1", status="pending")

    def test_update_nonexistent_milestone_raises(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n")
        with pytest.raises(ValueError, match="Milestone not found"):
            update_milestone("G", "Ghost", status="completed")


class TestCompleteMilestone:
    def test_complete_sets_status(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n"
            "## Milestones\n"
            "### Milestone: M1  (order: 0)\n"
        )
        ms = complete_milestone("G", "M1")
        assert ms.status == "completed"

    def test_complete_persists(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n"
            "## Milestones\n"
            "### Milestone: M1  (order: 0)\n"
        )
        complete_milestone("G", "M1")
        goals = load_goals()
        assert goals[0].milestones[0]["status"] == "completed"

    def test_complete_nonexistent_raises(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n")
        with pytest.raises(ValueError, match="Milestone not found"):
            complete_milestone("G", "Ghost")
