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

    def test_update_current_value_appends_snapshot(self, tmp_path, monkeypatch):
        """Setting current_value on a metric goal appends a snapshot (§12.4)."""
        goals_file = self._seed_with_metric(tmp_path, monkeypatch)
        # Redirect metric history to a temp file so we don't touch real data.
        metric_file = tmp_path / "metric_history.md"
        monkeypatch.setattr(
            "janus.integrations.metric_history.METRIC_HISTORY_PATH", metric_file
        )
        g = update_goal_fields("Body fat", current_value=18.0)
        assert g.current_value == 18.0
        assert metric_file.exists()
        content = metric_file.read_text()
        assert "Body fat" in content  # goal title appears in snapshot
        assert "Body fat %" in content  # metric name also appears
        assert "18.0" in content
        assert "manual" in content

    def test_update_current_value_no_snapshot_without_metric(self, tmp_path, monkeypatch):
        """No snapshot appended when goal has no metric_name."""
        goals_file = tmp_path / "goals.md"
        goals_file.write_text(
            "# Goals\n\n## Goal: Simple\nStatus: active\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        metric_file = tmp_path / "metric_history.md"
        monkeypatch.setattr(
            "janus.integrations.metric_history.METRIC_HISTORY_PATH", metric_file
        )
        # current_value on a goal without metric — metric_name is None
        # so update_goal_fields won't see current_value as a metric change
        # Actually, current_value is just a float field; the service checks
        # goal.metric_name. Since Simple has no metric, no snapshot.
        update_goal_fields("Simple", current_value=5.0)
        assert not metric_file.exists()

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


# ---------------------------------------------------------------------------
# 6. Measurement requirements in add_goal / update_goal_fields
# ---------------------------------------------------------------------------


class TestMeasurementRequirementsService:
    def _seed(self, tmp_path, monkeypatch, goals_content="# Goals\n"):
        goals_file = _write_goals_file(tmp_path, goals_content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        return goals_file

    def test_add_goal_with_measurement_requirements(self, tmp_path, monkeypatch):
        self._seed(tmp_path, monkeypatch)
        g = add_goal(
            "Body fat",
            measurement_requirements=[
                {"metric": "weight", "unit": "kg", "frequency": "daily"},
                {"metric": "waist", "unit": "cm", "frequency": "twice_weekly"},
            ],
        )
        assert len(g.measurement_requirements) == 2
        assert g.measurement_requirements[0]["metric"] == "weight"
        assert g.measurement_requirements[1]["metric"] == "waist"

    def test_add_goal_without_measurement_requirements_defaults_empty(self, tmp_path, monkeypatch):
        self._seed(tmp_path, monkeypatch)
        g = add_goal("Simple goal")
        assert g.measurement_requirements == []

    def test_add_goal_invalid_frequency_raises(self, tmp_path, monkeypatch):
        self._seed(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="Invalid frequency"):
            add_goal(
                "Bad",
                measurement_requirements=[{"metric": "x", "frequency": "monthly"}],
            )

    def test_add_goal_empty_metric_raises(self, tmp_path, monkeypatch):
        self._seed(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="non-empty"):
            add_goal("Bad", measurement_requirements=[{"metric": ""}])

    def test_add_goal_custom_without_interval_raises(self, tmp_path, monkeypatch):
        self._seed(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="interval_days"):
            add_goal("Bad", measurement_requirements=[{"metric": "x", "frequency": "custom"}])

    def test_add_goal_invalid_preferred_time_raises(self, tmp_path, monkeypatch):
        self._seed(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="preferred_time"):
            add_goal(
                "Bad",
                measurement_requirements=[{"metric": "x", "preferred_time": "noon"}],
            )

    def test_update_add_measurement_requirement(self, tmp_path, monkeypatch):
        self._seed(
            tmp_path, monkeypatch,
            "## Goal: Body fat\nStatus: active\n",
        )
        g = update_goal_fields(
            "Body fat",
            add_measurement_requirement={"metric": "weight", "unit": "kg", "frequency": "daily"},
        )
        assert len(g.measurement_requirements) == 1
        assert g.measurement_requirements[0]["metric"] == "weight"

    def test_update_add_duplicate_metric_appends(self, tmp_path, monkeypatch):
        self._seed(
            tmp_path, monkeypatch,
            "## Goal: Body fat\nStatus: active\n",
        )
        update_goal_fields("Body fat", add_measurement_requirement={"metric": "weight", "unit": "kg"})
        g = update_goal_fields("Body fat", add_measurement_requirement={"metric": "weight", "unit": "lb"})
        assert len(g.measurement_requirements) == 2

    def test_update_remove_measurement_requirement(self, tmp_path, monkeypatch):
        self._seed(
            tmp_path, monkeypatch,
            "## Goal: Body fat\nStatus: active\n",
        )
        update_goal_fields("Body fat", add_measurement_requirement={"metric": "weight", "unit": "kg"})
        g = update_goal_fields("Body fat", remove_measurement_requirement="weight")
        assert g.measurement_requirements == []

    def test_update_remove_nonexistent_metric_no_change(self, tmp_path, monkeypatch):
        self._seed(
            tmp_path, monkeypatch,
            "## Goal: Body fat\nStatus: active\n",
        )
        update_goal_fields("Body fat", add_measurement_requirement={"metric": "weight", "unit": "kg"})
        g = update_goal_fields("Body fat", remove_measurement_requirement="waist")
        assert len(g.measurement_requirements) == 1
        assert g.measurement_requirements[0]["metric"] == "weight"

    def test_update_set_measurement_requirements(self, tmp_path, monkeypatch):
        self._seed(
            tmp_path, monkeypatch,
            "## Goal: Body fat\nStatus: active\n",
        )
        update_goal_fields(
            "Body fat",
            add_measurement_requirement={"metric": "weight", "unit": "kg"},
        )
        g = update_goal_fields(
            "Body fat",
            set_measurement_requirements=[{"metric": "steps", "unit": "steps", "frequency": "daily"}],
        )
        assert len(g.measurement_requirements) == 1
        assert g.measurement_requirements[0]["metric"] == "steps"

    def test_update_add_invalid_measurement_requirement_raises(self, tmp_path, monkeypatch):
        self._seed(
            tmp_path, monkeypatch,
            "## Goal: Body fat\nStatus: active\n",
        )
        with pytest.raises(ValueError, match="Invalid frequency"):
            update_goal_fields(
                "Body fat",
                add_measurement_requirement={"metric": "x", "frequency": "monthly"},
            )

    def test_add_goal_requires_persists_to_file(self, tmp_path, monkeypatch):
        goals_file = self._seed(tmp_path, monkeypatch)
        add_goal("X", measurement_requirements=[{"metric": "weight", "unit": "kg"}])
        content = goals_file.read_text()
        assert "Measurement requirements:" in content
        assert "- metric: weight" in content


# ---------------------------------------------------------------------------
# 7. research_artifact_titles field
# ---------------------------------------------------------------------------

class TestResearchArtifactTitles:
    def _seed_empty(self, tmp_path, monkeypatch):
        goals_file = tmp_path / "goals.md"
        goals_file.write_text("# Goals\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        return goals_file

    def test_add_goal_with_research_artifacts(self, tmp_path, monkeypatch):
        self._seed_empty(tmp_path, monkeypatch)
        g = add_goal("My Goal", research_artifact_titles=["Artifact 1", "Artifact 2"])
        assert g.research_artifact_titles == ["Artifact 1", "Artifact 2"]

    def test_add_goal_research_artifacts_default_empty(self, tmp_path, monkeypatch):
        self._seed_empty(tmp_path, monkeypatch)
        g = add_goal("Simple goal")
        assert g.research_artifact_titles == []

    def test_update_add_research_artifact(self, tmp_path, monkeypatch):
        self._seed_empty(tmp_path, monkeypatch)
        add_goal("G")
        g = update_goal_fields("G", add_research_artifact="Artifact 1")
        assert g.research_artifact_titles == ["Artifact 1"]

    def test_update_add_research_artifact_duplicate_no_change(self, tmp_path, monkeypatch):
        self._seed_empty(tmp_path, monkeypatch)
        add_goal("G", research_artifact_titles=["Artifact 1"])
        g = update_goal_fields("G", add_research_artifact="Artifact 1")
        assert g.research_artifact_titles == ["Artifact 1"]

    def test_update_remove_research_artifact(self, tmp_path, monkeypatch):
        self._seed_empty(tmp_path, monkeypatch)
        add_goal("G", research_artifact_titles=["A1", "A2"])
        g = update_goal_fields("G", remove_research_artifact="A1")
        assert g.research_artifact_titles == ["A2"]

    def test_update_remove_nonexistent_artifact_no_change(self, tmp_path, monkeypatch):
        self._seed_empty(tmp_path, monkeypatch)
        add_goal("G", research_artifact_titles=["A1"])
        g = update_goal_fields("G", remove_research_artifact="Ghost")
        assert g.research_artifact_titles == ["A1"]

    def test_update_set_research_artifacts(self, tmp_path, monkeypatch):
        self._seed_empty(tmp_path, monkeypatch)
        add_goal("G", research_artifact_titles=["A1", "A2"])
        g = update_goal_fields("G", set_research_artifacts=["A3", "A4"])
        assert g.research_artifact_titles == ["A3", "A4"]

    def test_update_research_artifacts_persists_to_file(self, tmp_path, monkeypatch):
        goals_file = self._seed_empty(tmp_path, monkeypatch)
        add_goal("G")
        update_goal_fields("G", add_research_artifact="My Artifact")
        content = goals_file.read_text()
        assert "Research artifacts:" in content
        assert "- My Artifact" in content
