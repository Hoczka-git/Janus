"""Tests for Markdown goals loader.

All tests use temp fixtures ONLY. Does NOT modify data/goals.md.
"""

import pytest

from pathlib import Path

from janus.models.goal import Goal
from janus.integrations.markdown_goals import (
    GOALS_PATH,
    load_goals,
    save_goal,
    update_goal,
)


def _write_goals_file(tmp_path, content):
    goals_file = tmp_path / "goals.md"
    goals_file.write_text(content)
    return goals_file


# ===========================================================================
# 1. Model validation
# ===========================================================================

class TestGoalModelValidation:
    def test_goal_default_fields(self):
        g = Goal("X")
        assert g.title == "X"
        assert g.status == "active"
        assert g.direction is None
        assert g.related_tasks == []

    def test_goal_all_fields(self):
        g = Goal(
            title="Body fat",
            description="Reduce body fat",
            status="active",
            deadline="2027-03-31",
            metric_name="Body fat %",
            metric_unit="%",
            start_value=23.0,
            current_value=20.0,
            target_value=15.0,
            direction="decrease",
            related_tasks=["Task A", "Task B"],
        )
        assert g.metric_name == "Body fat %"
        assert g.start_value == 23.0
        assert g.target_value == 15.0

    def test_invalid_status(self):
        with pytest.raises(ValueError, match="Invalid goal status"):
            Goal("X", status="pending")

    def test_invalid_direction(self):
        with pytest.raises(ValueError, match="Invalid direction"):
            Goal("X", direction="sideways")

    def test_dedup_preserves_order(self):
        g = Goal("X", related_tasks=["A", "B", "A", "C"])
        assert g.related_tasks == ["A", "B", "C"]

    def test_dedup_empty(self):
        g = Goal("X", related_tasks=[])
        assert g.related_tasks == []

    def test_dedup_none(self):
        g = Goal("X")
        assert g.related_tasks == []


# ===========================================================================
# 2. Persistence round-trip
# ===========================================================================

class TestPersistenceRoundTrip:
    def test_roundtrip_minimal(self, tmp_path, monkeypatch):
        goals_file = _write_goals_file(tmp_path, "# Goals\n\n## Goal: X\nStatus: active\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert len(goals) == 1
        g = goals[0]
        assert g.title == "X"
        assert g.status == "active"
        assert g.description == ""
        assert g.metric_name is None

    def test_roundtrip_metric(self, tmp_path, monkeypatch):
        content = (
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
        )
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert len(goals) == 1
        g = goals[0]
        assert g.metric_name == "Body fat %"
        assert g.metric_unit == "%"
        assert g.start_value == 23.0
        assert g.current_value == 20.0
        assert g.target_value == 15.0
        assert g.direction == "decrease"
        assert g.deadline == "2027-03-31"

    def test_roundtrip_task_only(self, tmp_path, monkeypatch):
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

    def test_roundtrip_deadline(self, tmp_path, monkeypatch):
        content = "# Goals\n\n## Goal: X\nStatus: active\nDeadline: 2027-06-30\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        g = goals[0]
        assert g.deadline == "2027-06-30"

    def test_save_appends(self, tmp_path, monkeypatch):
        goals_file = tmp_path / "goals.md"
        goals_file.write_text("# Goals\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        g1 = Goal("First")
        g2 = Goal("Second", status="completed")
        save_goal(g1)
        save_goal(g2)

        goals = load_goals()
        assert len(goals) == 2
        assert goals[0].title == "First"
        assert goals[1].title == "Second"

    def test_update_replaces(self, tmp_path, monkeypatch):
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n"
            "## Goal: X\n"
            "Status: active\n"
            "Description: original\n"
            "\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        g = load_goals()[0]
        g.description = "updated"
        update_goal(g)

        goals = load_goals()
        assert len(goals) == 1
        assert goals[0].description == "updated"

    def test_update_not_found(self, tmp_path, monkeypatch):
        goals_file = _write_goals_file(tmp_path, "# Goals\n\n## Goal: X\nStatus: active\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        g = Goal("Y")
        with pytest.raises(ValueError, match="Goal not found"):
            update_goal(g)

    def test_missing_file_returns_empty(self, monkeypatch):
        nonexistent = Path("/tmp/nonexistent_goals_test_xyz.md")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", nonexistent)

        goals = load_goals()
        assert goals == []


# ===========================================================================
# 3. Backward compatibility
# ===========================================================================

class TestBackwardCompatibility:
    def test_old_format_parses(self, tmp_path, monkeypatch):
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
        assert goals[1].title == "Maintain regular training"
        assert goals[1].metric_name is None

    def test_mixed_format(self, tmp_path, monkeypatch):
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
        assert goals[0].related_tasks == ["Task A"]
        assert goals[1].metric_name == "Savings"
        assert goals[1].target_value == 10000.0

    def test_unknown_field_ignored_on_parse(self, tmp_path, monkeypatch):
        content = (
            "# Goals\n\n"
            "## Goal: X\n"
            "Status: active\n"
            "Foo: bar\n"
            "Baz: 123\n"
        )
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        g = goals[0]
        assert g.title == "X"
        # Goal has no Foo or Baz attributes
        assert not hasattr(g, "foo")
        assert not hasattr(g, "baz")

    def test_unknown_field_not_preserved_on_update(self, tmp_path, monkeypatch):
        content = (
            "# Goals\n\n"
            "## Goal: X\n"
            "Status: active\n"
            "Foo: bar\n"
        )
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        g = goals[0]
        # Change something
        g.description = "updated"
        update_goal(g)

        # Reload
        goals2 = load_goals()
        g2 = goals2[0]
        assert g2.description == "updated"
        # Unknown Foo field should be gone
        content_after = goals_file.read_text()
        assert "Foo:" not in content_after


# ===========================================================================
# 4. New field parsing
# ===========================================================================

class TestNewFieldParsing:
    def test_parse_metric(self, tmp_path, monkeypatch):
        content = "# Goals\n\n## Goal: X\nStatus: active\nMetric: Body fat %\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        goals = load_goals()
        assert goals[0].metric_name == "Body fat %"

    def test_parse_unit(self, tmp_path, monkeypatch):
        content = "# Goals\n\n## Goal: X\nStatus: active\nUnit: %\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        goals = load_goals()
        assert goals[0].metric_unit == "%"

    def test_parse_start(self, tmp_path, monkeypatch):
        content = "# Goals\n\n## Goal: X\nStatus: active\nStart: 23.0\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        goals = load_goals()
        assert goals[0].start_value == 23.0

    def test_parse_current(self, tmp_path, monkeypatch):
        content = "# Goals\n\n## Goal: X\nStatus: active\nCurrent: 20.0\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        goals = load_goals()
        assert goals[0].current_value == 20.0

    def test_parse_target(self, tmp_path, monkeypatch):
        content = "# Goals\n\n## Goal: X\nStatus: active\nTarget: 15.0\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        goals = load_goals()
        assert goals[0].target_value == 15.0

    def test_parse_direction(self, tmp_path, monkeypatch):
        content = "# Goals\n\n## Goal: X\nStatus: active\nDirection: decrease\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        goals = load_goals()
        assert goals[0].direction == "decrease"

    def test_parse_deadline(self, tmp_path, monkeypatch):
        content = "# Goals\n\n## Goal: X\nStatus: active\nDeadline: 2027-01-15\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        goals = load_goals()
        assert goals[0].deadline == "2027-01-15"


class TestMalformedFieldParsing:
    def test_malformed_start_raises(self, tmp_path, monkeypatch):
        content = "# Goals\n\n## Goal: X\nStatus: active\nStart: abc\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        with pytest.raises(ValueError, match="Invalid Start"):
            load_goals()

    def test_malformed_current_raises(self, tmp_path, monkeypatch):
        content = "# Goals\n\n## Goal: X\nStatus: active\nCurrent: xyz\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        with pytest.raises(ValueError, match="Invalid Current"):
            load_goals()

    def test_malformed_target_raises(self, tmp_path, monkeypatch):
        content = "# Goals\n\n## Goal: X\nStatus: active\nTarget: notanumber\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        with pytest.raises(ValueError, match="Invalid Target"):
            load_goals()

    def test_invalid_direction_raises(self, tmp_path, monkeypatch):
        content = "# Goals\n\n## Goal: X\nStatus: active\nDirection: sideways\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        with pytest.raises(ValueError, match="Invalid Direction"):
            load_goals()

    def test_invalid_deadline_raises(self, tmp_path, monkeypatch):
        content = "# Goals\n\n## Goal: X\nStatus: active\nDeadline: not-a-date\n"
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        with pytest.raises(ValueError, match="Invalid Deadline"):
            load_goals()


# ===========================================================================
# 5. Unknown field behavior
# ===========================================================================

class TestUnknownFieldBehavior:
    def test_unknown_field_not_preserved_on_update(self, tmp_path, monkeypatch):
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
# 6. Duplicate related_tasks
# ===========================================================================

class TestDuplicateRelatedTasks:
    def test_duplicate_related_tasks_dedup(self, tmp_path, monkeypatch):
        content = (
            "# Goals\n\n"
            "## Goal: X\n"
            "Status: active\n"
            "Related tasks:\n"
            "- A\n"
            "- B\n"
            "- A\n"
            "- C\n"
        )
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert goals[0].related_tasks == ["A", "B", "C"]
