"""Tests for Goal persistence service (goals.py).

All tests use temp fixtures ONLY.
"""
from __future__ import annotations

import pytest

from pathlib import Path
from janus.models.goal import Goal
from janus.services.goals import (
    add_goal,
    complete_goal,
    get_goal,
    update_goal_fields,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_goals_file(tmp_path, content):
    goals_file = tmp_path / "goals.md"
    goals_file.write_text(content)
    return goals_file


def _setup_goals_fixtures(tmp_path, monkeypatch, goals_content="# Goals\n"):
    goals_file = _write_goals_file(tmp_path, goals_content)
    monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
    return goals_file


# ---------------------------------------------------------------------------
# 1. add_goal
# ---------------------------------------------------------------------------

class TestAddGoal:
    def test_add_minimal_goal(self, tmp_path, monkeypatch):
        _setup_goals_fixtures(tmp_path, monkeypatch)
        g = add_goal("Test goal")
        assert g.title == "Test goal"
        assert g.status == "active"
        assert g.description == ""
        assert g.metric_name is None
        assert g.related_tasks == []

    def test_add_goal_persisted_to_file(self, tmp_path, monkeypatch):
        goals_file = _setup_goals_fixtures(tmp_path, monkeypatch)
        add_goal("X")
        assert "## Goal: X" in goals_file.read_text()

    def test_add_goal_duplicate_title_raises(self, tmp_path, monkeypatch):
        _setup_goals_fixtures(tmp_path, monkeypatch)
        add_goal("X")
        with pytest.raises(ValueError, match="already exists"):
            add_goal("X")

    def test_add_goal_with_description(self, tmp_path, monkeypatch):
        _setup_goals_fixtures(tmp_path, monkeypatch)
        g = add_goal("X", description="A description")
        assert g.description == "A description"

    def test_add_goal_with_status(self, tmp_path, monkeypatch):
        _setup_goals_fixtures(tmp_path, monkeypatch)
        g = add_goal("X", status="inactive")
        assert g.status == "inactive"

    def test_add_goal_with_deadline(self, tmp_path, monkeypatch):
        _setup_goals_fixtures(tmp_path, monkeypatch)
        g = add_goal("X", deadline="2027-12-31")
        assert g.deadline == "2027-12-31"

    def test_add_goal_metric(self, tmp_path, monkeypatch):
        _setup_goals_fixtures(tmp_path, monkeypatch)
        g = add_goal(
            "Body fat",
            metric_name="Body fat %",
            metric_unit="%",
            start_value=23.0,
            current_value=20.0,
            target_value=15.0,
            direction="decrease",
        )
        assert g.metric_name == "Body fat %"
        assert g.metric_unit == "%"
        assert g.start_value == 23.0
        assert g.current_value == 20.0
        assert g.target_value == 15.0
        assert g.direction == "decrease"

    def test_add_goal_related_tasks(self, tmp_path, monkeypatch):
        _setup_goals_fixtures(tmp_path, monkeypatch)
        g = add_goal("X", related_tasks=["Task A", "Task B"])
        assert g.related_tasks == ["Task A", "Task B"]

    def test_add_goal_invalid_status_raises(self, tmp_path, monkeypatch):
        _setup_goals_fixtures(tmp_path, monkeypatch)
        with pytest.raises(ValueError):
            add_goal("X", status="pending")

    def test_add_goal_invalid_direction_raises(self, tmp_path, monkeypatch):
        _setup_goals_fixtures(tmp_path, monkeypatch)
        with pytest.raises(ValueError):
            add_goal("X", direction="sideways")

    def test_add_goal_empty_title_raises(self, tmp_path, monkeypatch):
        _setup_goals_fixtures(tmp_path, monkeypatch)
        with pytest.raises(ValueError):
            add_goal("")


# ---------------------------------------------------------------------------
# 2. get_goal
# ---------------------------------------------------------------------------

class TestGetGoal:
    def _seed(self, tmp_path, monkeypatch):
        goals_file = _setup_goals_fixtures(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: Existing\nStatus: active\n",
        )
        return goals_file

    def test_get_existing_goal(self, tmp_path, monkeypatch):
        self._seed(tmp_path, monkeypatch)
        g = get_goal("Existing")
        assert g.title == "Existing"
        assert g.status == "active"

    def test_get_nonexistent_goal_raises(self, tmp_path, monkeypatch):
        _setup_goals_fixtures(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="Goal not found"):
            get_goal("Ghost")


# ---------------------------------------------------------------------------
# 3. update_goal_fields
# ---------------------------------------------------------------------------

class TestUpdateGoalFields:
    def _seed_with_metric(self, tmp_path, monkeypatch):
        goals_file = _setup_goals_fixtures(
            tmp_path, monkeypatch,
            "# Goals\n\n"
            "## Goal: Body fat\n"
            "Status: active\n"
            "Metric: Body fat %\n"
            "Unit: %\n"
            "Start: 23.0\n"
            "Current: 20.0\n"
            "Target: 15.0\n"
            "Direction: decrease\n"
            "Deadline: 2027-03-31\n"
            "Related tasks:\n"
            "- Strength training\n"
            "- Cardio plan\n"
            "\n",
        )
        return goals_file

    def test_update_status(self, tmp_path, monkeypatch):
        self._seed_with_metric(tmp_path, monkeypatch)
        g = update_goal_fields("Body fat", status="completed")
        assert g.status == "completed"

    def test_update_description(self, tmp_path, monkeypatch):
        self._seed_with_metric(tmp_path, monkeypatch)
        g = update_goal_fields("Body fat", description="New desc")
        assert g.description == "New desc"

    def test_update_deadline(self, tmp_path, monkeypatch):
        self._seed_with_metric(tmp_path, monkeypatch)
        g = update_goal_fields("Body fat", deadline="2028-01-01")
        assert g.deadline == "2028-01-01"

    def test_update_metric(self, tmp_path, monkeypatch):
        self._seed_with_metric(tmp_path, monkeypatch)
        g = update_goal_fields("Body fat", metric_name="Weight")
        assert g.metric_name == "Weight"

    def test_update_direction(self, tmp_path, monkeypatch):
        self._seed_with_metric(tmp_path, monkeypatch)
        g = update_goal_fields("Body fat", direction="increase")
        assert g.direction == "increase"

    def test_update_target_value(self, tmp_path, monkeypatch):
        self._seed_with_metric(tmp_path, monkeypatch)
        g = update_goal_fields("Body fat", target_value=10.0)
        assert g.target_value == 10.0

    def test_update_start_value(self, tmp_path, monkeypatch):
        self._seed_with_metric(tmp_path, monkeypatch)
        g = update_goal_fields("Body fat", start_value=30.0)
        assert g.start_value == 30.0

    def test_update_current_value(self, tmp_path, monkeypatch):
        self._seed_with_metric(tmp_path, monkeypatch)
        g = update_goal_fields("Body fat", current_value=18.0)
        assert g.current_value == 18.0

    def test_update_add_related_task_new(self, tmp_path, monkeypatch):
        self._seed_with_metric(tmp_path, monkeypatch)
        g = update_goal_fields("Body fat", add_related_task="New task")
        assert "New task" in g.related_tasks
        assert len(g.related_tasks) == 3

    def test_update_add_related_task_duplicate_no_change(self, tmp_path, monkeypatch):
        self._seed_with_metric(tmp_path, monkeypatch)
        g = update_goal_fields("Body fat", add_related_task="Strength training")
        assert g.related_tasks == ["Strength training", "Cardio plan"]

    def test_update_remove_related_task(self, tmp_path, monkeypatch):
        self._seed_with_metric(tmp_path, monkeypatch)
        g = update_goal_fields("Body fat", remove_related_task="Cardio plan")
        assert "Cardio plan" not in g.related_tasks
        assert "Strength training" in g.related_tasks

    def test_update_remove_nonexistent_task_no_change(self, tmp_path, monkeypatch):
        self._seed_with_metric(tmp_path, monkeypatch)
        g = update_goal_fields("Body fat", remove_related_task="Ghost")
        assert g.related_tasks == ["Strength training", "Cardio plan"]

    def test_update_nonexistent_goal_raises(self, tmp_path, monkeypatch):
        _setup_goals_fixtures(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="Goal not found"):
            update_goal_fields("Ghost", status="completed")

    def test_update_empty_title_raises(self, tmp_path, monkeypatch):
        _setup_goals_fixtures(tmp_path, monkeypatch)
        add_goal("X")
        with pytest.raises(ValueError):
            update_goal_fields("", status="completed")

    def test_update_title_immutable_via_kwargs(self, tmp_path, monkeypatch):
        self._seed_with_metric(tmp_path, monkeypatch)
        with pytest.raises(TypeError):
            update_goal_fields("Body fat", title="Renamed")

    def test_update_persists_to_file(self, tmp_path, monkeypatch):
        goals_file = self._seed_with_metric(tmp_path, monkeypatch)
        update_goal_fields("Body fat", description="Updated desc")
        content = goals_file.read_text()
        assert "Description: Updated desc" in content
        assert "Description: Reduce body fat" not in content


# ---------------------------------------------------------------------------
# 4. complete_goal
# ---------------------------------------------------------------------------

class TestCompleteGoal:
    def _seed(self, tmp_path, monkeypatch):
        _setup_goals_fixtures(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: X\nStatus: active\n",
        )

    def test_complete_active_goal(self, tmp_path, monkeypatch):
        self._seed(tmp_path, monkeypatch)
        g = complete_goal("X")
        assert g.status == "completed"

    def test_complete_nonexistent_goal_raises(self, tmp_path, monkeypatch):
        self._seed(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="Goal not found"):
            complete_goal("Ghost")

    def test_complete_empty_title_raises(self, tmp_path, monkeypatch):
        _setup_goals_fixtures(tmp_path, monkeypatch)
        with pytest.raises(ValueError):
            complete_goal("")


# ---------------------------------------------------------------------------
# 5. No delete_goal
# ---------------------------------------------------------------------------

class TestNoDeleteGoal:
    def test_delete_goal_does_not_exist_in_service(self):
        import janus.services.goals as s
        assert not hasattr(s, "delete_goal")

    def test_delete_goal_does_not_exist_in_models(self):
        import janus.models.goal as m
        assert not hasattr(m, "delete_goal")

    def test_delete_goal_does_not_exist_in_integrations(self):
        import janus.integrations.markdown_goals as i
        assert not hasattr(i, "delete_goal"), (
            "delete_goal must not be implemented in markdown_goals either"
        )
