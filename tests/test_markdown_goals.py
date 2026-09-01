"""Tests for the Goal System MVP implementation.

Tests for markdown_goals persistence, goal progress calculation, CLI handlers,
and weekly review integration.

All tests use temp fixtures ONLY. Does NOT modify data/goals.md.
"""

import pytest

from pathlib import Path


# ===========================================================================
# Helper functions
# ===========================================================================


def _write_goals_file(tmp_path, content):
    """Write a goals.md file in a temp directory."""
    goals_file = tmp_path / "goals.md"
    goals_file.write_text(content)
    return goals_file


def _write_tasks_file(tmp_path, content):
    """Write a tasks.md file in a temp directory."""
    tasks_file = tmp_path / "tasks.md"
    tasks_file.write_text(content)
    return tasks_file


def _setup_fixtures(tmp_path, monkeypatch):
    """Set up goals.md and tasks.md in temp dir, monkeypatch paths."""
    goals_file = _write_goals_file(
        tmp_path,
        "# Goals\n\n## Goal: Task goal\nStatus: active\nRelated tasks:\n- Test task\n",
    )
    tasks_file = _write_tasks_file(
        tmp_path,
        "- [ ] Test task\n",
    )
    monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
    monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
    return goals_file, tasks_file


# ===========================================================================
# 1. Model validation (Goal dataclass)
# ===========================================================================


class TestGoalModel:
    def test_default_fields(self):
        from janus.models.goal import Goal

        g = Goal("Test Goal")
        assert g.title == "Test Goal"
        assert g.status == "active"
        assert g.direction is None
        assert g.related_tasks == []

    def test_all_fields(self):
        from janus.models.goal import Goal

        g = Goal(
            title="Body fat reduction",
            description="Reduce body fat",
            status="active",
            deadline="2027-03-31",
            metric_name="Body fat %",
            metric_unit="%",
            start_value=23.0,
            current_value=20.0,
            target_value=15.0,
            direction="decrease",
            related_tasks=["Strength training", "Cardio"],
        )
        assert g.metric_name == "Body fat %"
        assert g.direction == "decrease"
        assert g.start_value == 23.0
        assert g.target_value == 15.0

    def test_invalid_status(self):
        from janus.models.goal import Goal

        with pytest.raises(ValueError, match="Invalid goal status"):
            Goal("Test", status="pending")

    def test_invalid_direction(self):
        from janus.models.goal import Goal

        with pytest.raises(ValueError, match="Invalid direction"):
            Goal("Test", direction="sideways")

    def test_dedup_preserves_order(self):
        from janus.models.goal import Goal

        g = Goal("Test", related_tasks=["A", "B", "A", "C"])
        assert g.related_tasks == ["A", "B", "C"]

    def test_dedup_empty(self):
        from janus.models.goal import Goal

        g = Goal("Test", related_tasks=[])
        assert g.related_tasks == []

    def test_dedup_none(self):
        from janus.models.goal import Goal

        g = Goal("Test")
        assert g.related_tasks == []


# ===========================================================================
# 2. Persistence round-trip (markdown_goals)
# ===========================================================================


class TestMarkdownGoalsPersistence:
    def test_missing_file_returns_empty(self, monkeypatch):
        """load_goals() returns [] when file is missing (changed from FileNotFoundError)."""
        from janus.integrations.markdown_goals import load_goals

        nonexistent = Path("/tmp/test_missing_goals_" + str(hash(id(monkeypatch))) + ".md")
        if nonexistent.exists():
            nonexistent.unlink()
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", nonexistent)
        result = load_goals()
        assert result == []

    def test_roundtrip_minimal(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals, save_goal, update_goal
        from janus.models.goal import Goal

        goals_file = _write_goals_file(tmp_path, "# Goals\n\n## Goal: Test\nStatus: active\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert len(goals) == 1
        assert goals[0].title == "Test"
        assert goals[0].status == "active"

        # Save another goal
        g = Goal("Second goal")
        save_goal(g)
        goals = load_goals()
        assert len(goals) == 2
        assert goals[1].title == "Second goal"

    def test_roundtrip_metric(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = (
            "# Goals\n\n"
            "## Goal: Body fat reduction\n"
            "Status: active\n"
            "Metric: Body fat %\n"
            "Unit: %\n"
            "Start: 23.0\n"
            "Current: 20.0\n"
            "Target: 15.0\n"
            "Direction: decrease\n"
        )
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert len(goals) == 1
        g = goals[0]
        assert g.metric_name == "Body fat %"
        assert g.start_value == 23.0
        assert g.current_value == 20.0
        assert g.target_value == 15.0
        assert g.direction == "decrease"

    def test_roundtrip_task_only(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = (
            "# Goals\n\n"
            "## Goal: Japan trip\n"
            "Status: active\n"
            "Related tasks:\n"
            "- Buy flights\n"
            "- Book hotels\n"
        )
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert len(goals) == 1
        g = goals[0]
        assert g.title == "Japan trip"
        assert g.metric_name is None
        assert g.target_value is None
        assert g.related_tasks == ["Buy flights", "Book hotels"]

    def test_save_goal_appends(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import save_goal
        from janus.models.goal import Goal

        goals_file = tmp_path / "goals.md"
        goals_file.write_text("# Goals\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        save_goal(Goal("Goal 1", status="active"))
        save_goal(Goal("Goal 2", status="completed"))

        content = goals_file.read_text()
        assert "## Goal: Goal 1" in content
        assert "## Goal: Goal 2" in content

    def test_update_goal_replaces_block(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals, update_goal
        from janus.models.goal import Goal

        content = (
            "# Goals\n\n"
            "## Goal: Test\n"
            "Status: active\n"
            "Description: original\n"
            "\n"
        )
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        g = goals[0]
        g.description = "updated"
        update_goal(g)

        goals2 = load_goals()
        assert len(goals2) == 1
        assert goals2[0].description == "updated"

    def test_update_goal_not_found_raises(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import update_goal
        from janus.models.goal import Goal

        content = "# Goals\n\n## Goal: Existing\nStatus: active\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        g = Goal("NonExistent")
        with pytest.raises(ValueError, match="not found"):
            update_goal(g)

    def test_save_goal_empty_title_raises(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import save_goal
        from janus.models.goal import Goal

        goals_file = tmp_path / "goals.md"
        goals_file.write_text("# Goals\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        with pytest.raises(ValueError, match="empty"):
            save_goal(Goal(""))

    def test_update_goal_empty_title_raises(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals, update_goal

        content = "# Goals\n\n## Goal: Test\nStatus: active\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        g = goals[0]
        g.title = ""
        with pytest.raises(ValueError, match="empty"):
            update_goal(g)


# ===========================================================================
# 3. New field parsing
# ===========================================================================


class TestNewFieldParsing:
    def test_parse_metric(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = "# Goals\n\n## Goal: X\nStatus: active\nMetric: Body fat %\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        goals = load_goals()
        assert goals[0].metric_name == "Body fat %"

    def test_parse_unit(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = "# Goals\n\n## Goal: X\nStatus: active\nUnit: %\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        goals = load_goals()
        assert goals[0].metric_unit == "%"

    def test_parse_start(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = "# Goals\n\n## Goal: X\nStatus: active\nStart: 23.0\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        goals = load_goals()
        assert goals[0].start_value == 23.0

    def test_parse_current(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = "# Goals\n\n## Goal: X\nStatus: active\nCurrent: 20.0\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        goals = load_goals()
        assert goals[0].current_value == 20.0

    def test_parse_target(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = "# Goals\n\n## Goal: X\nStatus: active\nTarget: 15.0\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        goals = load_goals()
        assert goals[0].target_value == 15.0

    def test_parse_direction(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = "# Goals\n\n## Goal: X\nStatus: active\nDirection: decrease\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        goals = load_goals()
        assert goals[0].direction == "decrease"

    def test_parse_deadline(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = "# Goals\n\n## Goal: X\nStatus: active\nDeadline: 2027-01-15\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        goals = load_goals()
        assert goals[0].deadline == "2027-01-15"


# ===========================================================================
# 4. Backward compatibility (old format)
# ===========================================================================


class TestBackwardCompatibility:
    def test_old_format_parses(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        # Matches current data/goals.md format
        content = (
            "# Goals\n\n"
            "## Goal: Complete autumn endurance challenge\n"
            "Description: Complete a meaningful endurance event during autumn.\n"
            "Status: active\n"
            "Related tasks:\n"
            "- Prepare training plan\n"
            "- Buy running shoes\n"
            "\n"
            "## Goal: Maintain regular training\n"
            "Description: Build a consistent training routine.\n"
            "Status: active\n"
            "Related tasks:\n"
            "- Prepare training plan\n"
        )
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        goals = load_goals()
        assert len(goals) == 2
        assert goals[0].title == "Complete autumn endurance challenge"
        assert goals[0].metric_name is None
        assert goals[0].target_value is None
        assert goals[0].related_tasks == ["Prepare training plan", "Buy running shoes"]

    def test_mixed_format(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = (
            "# Goals\n\n"
            "## Goal: Old style\n"
            "Status: active\n"
            "Related tasks:\n"
            "- Task A\n"
            "\n"
            "## Goal: New metric\n"
            "Status: active\n"
            "Metric: Savings\n"
            "Unit: PLN\n"
            "Start: 0\n"
            "Current: 4500\n"
            "Target: 10000\n"
            "Direction: increase\n"
        )
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        goals = load_goals()
        assert len(goals) == 2
        assert goals[0].metric_name is None
        assert goals[1].metric_name == "Savings"
        assert goals[1].target_value == 10000.0


# ===========================================================================
# 5. Unknown field behavior
# ===========================================================================


class TestUnknownFieldBehavior:
    def test_unknown_field_ignored_on_parse(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = "# Goals\n\n## Goal: X\nStatus: active\nSecret: hidden\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        goals = load_goals()
        g = goals[0]
        # Unknown field should not be in the Goal object
        assert not hasattr(g, "secret")

    def test_unknown_field_not_preserved_on_update(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals, update_goal

        content = "# Goals\n\n## Goal: X\nStatus: active\nSecret: hidden\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        goals = load_goals()
        g = goals[0]
        g.description = "now has description"
        update_goal(g)

        content_after = goals_file.read_text()
        assert "Secret:" not in content_after
        assert "Description:" in content_after


# ===========================================================================
# 6. Malformed field parsing (raises ValueError)
# ===========================================================================


class TestMalformedFieldParsing:
    def test_malformed_start_raises(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = "# Goals\n\n## Goal: X\nStatus: active\nStart: abc\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        with pytest.raises(ValueError, match="Invalid Start"):
            load_goals()

    def test_malformed_current_raises(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = "# Goals\n\n## Goal: X\nStatus: active\nCurrent: xyz\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        with pytest.raises(ValueError, match="Invalid Current"):
            load_goals()

    def test_malformed_target_raises(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = "# Goals\n\n## Goal: X\nStatus: active\nTarget: notanumber\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        with pytest.raises(ValueError, match="Invalid Target"):
            load_goals()

    def test_invalid_direction_raises(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = "# Goals\n\n## Goal: X\nStatus: active\nDirection: sideways\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        with pytest.raises(ValueError, match="Invalid Direction"):
            load_goals()

    def test_invalid_deadline_raises(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = "# Goals\n\n## Goal: X\nStatus: active\nDeadline: not-a-date\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        with pytest.raises(ValueError, match="Invalid Deadline"):
            load_goals()
