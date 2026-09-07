"""Tests for the 'janus goal health' CLI command."""
from datetime import date
from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

from janus.goals_cli import handle_goal_health


class TestGoalHealthCLI:
    """Tests for handle_goal_health — design §12.6."""

    @pytest.fixture
    def _isolated_data(self, tmp_path, monkeypatch):
        """Redirect all data file paths to a temp dir."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # Empty goals file
        (data_dir / "goals.md").write_text("# Goals\n\n")
        # No tasks file → handle_goal_health should handle gracefully
        tasks_path = data_dir / "tasks.md"

        import janus.integrations.markdown_goals as mg
        import janus.integrations.markdown_tasks as mt
        import janus.integrations.metric_history as mhist

        monkeypatch.setattr(mg, "GOALS_PATH", data_dir / "goals.md")
        monkeypatch.setattr(mt, "TASKS_PATH", tasks_path)
        monkeypatch.setattr(mhist, "METRIC_HISTORY_PATH", data_dir / "metric_history.md")

    def test_no_goals_prints_message(self, _isolated_data, capsys):
        """CLI with no goals prints a message, no crash."""
        handle_goal_health([])
        captured = capsys.readouterr()
        assert "GOAL HEALTH" in captured.out
        assert "No active goals to assess." in captured.out

    def test_no_tasks_file_does_not_crash(self, tmp_path, monkeypatch, capsys):
        """CLI works even when tasks.md doesn't exist (only goals defined)."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        goals_md = data_dir / "goals.md"
        goals_md.write_text(
            "# Goals\n\n"
            "## Goal: Test Goal\n"
            "Status: active\n"
        )
        tasks_path = data_dir / "tasks.md"  # does not exist

        import janus.integrations.markdown_goals as mg
        import janus.integrations.markdown_tasks as mt
        import janus.integrations.metric_history as mhist

        monkeypatch.setattr(mg, "GOALS_PATH", goals_md)
        monkeypatch.setattr(mt, "TASKS_PATH", tasks_path)
        monkeypatch.setattr(mhist, "METRIC_HISTORY_PATH", data_dir / "metric_history.md")

        handle_goal_health([])
        captured = capsys.readouterr()
        assert "GOAL HEALTH" in captured.out
        assert "Test Goal" in captured.out

    def test_single_goal_detail(self, tmp_path, monkeypatch, capsys):
        """With a title argument, shows full detail for that goal."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        goals_md = data_dir / "goals.md"
        goals_md.write_text(
            "# Goals\n\n"
            "## Goal: My Goal\n"
            "Status: active\n"
            "Metric: Weight\n"
            "Unit: kg\n"
            "Start: 100.0\n"
            "Current: 95.0\n"
            "Target: 90.0\n"
            "Direction: decrease\n"
            "Related tasks:\n"
            "- Task A\n"
        )
        tasks_path = data_dir / "tasks.md"
        tasks_path.write_text("- [ ] Task A\n")

        import janus.integrations.markdown_goals as mg
        import janus.integrations.markdown_tasks as mt
        import janus.integrations.metric_history as mhist

        monkeypatch.setattr(mg, "GOALS_PATH", goals_md)
        monkeypatch.setattr(mt, "TASKS_PATH", tasks_path)
        monkeypatch.setattr(mhist, "METRIC_HISTORY_PATH", data_dir / "metric_history.md")

        handle_goal_health(["My Goal"])
        captured = capsys.readouterr()
        assert "GOAL HEALTH: My Goal" in captured.out
        assert "Health state:" in captured.out
        assert "Progress:" in captured.out
        assert "Progress delta:" in captured.out
        assert "Last activity:" in captured.out
        assert "Measurements overdue:" in captured.out

    def test_unknown_goal_exits_1(self, _isolated_data, capsys):
        """CLI exits with code 1 for unknown goal title."""
        with pytest.raises(SystemExit) as exc_info:
            handle_goal_health(["Nonexistent Goal"])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "goal not found" in captured.err.lower()

    def test_all_goals_sorted_by_severity(self, tmp_path, monkeypatch, capsys):
        """All-goals view sorts stalled first, then watch, then healthy."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        goals_md = data_dir / "goals.md"
        goals_md.write_text(
            "# Goals\n\n"
            "## Goal: Stalled Goal\n"
            "Status: active\n"
            "Related tasks:\n"
            "- Done Task\n"
            "\n"
            "## Goal: Watch Goal\n"
            "Status: active\n"
            "Metric: M\n"
            "Unit: u\n"
            "Start: 10.0\n"
            "Current: 9.0\n"
            "Target: 5.0\n"
            "Direction: decrease\n"
            "Measurement requirements:\n"
            "  - metric: M\n"
            "    frequency: daily\n"
        )
        tasks_path = data_dir / "tasks.md"
        tasks_path.write_text("- [x] Done Task\n")

        import janus.integrations.markdown_goals as mg
        import janus.integrations.markdown_tasks as mt
        import janus.integrations.metric_history as mhist

        monkeypatch.setattr(mg, "GOALS_PATH", goals_md)
        monkeypatch.setattr(mt, "TASKS_PATH", tasks_path)
        monkeypatch.setattr(mhist, "METRIC_HISTORY_PATH", data_dir / "metric_history.md")

        handle_goal_health([])
        captured = capsys.readouterr()
        # Stalled Goal should appear before Watch Goal
        stalled_pos = captured.out.find("Stalled Goal")
        watch_pos = captured.out.find("Watch Goal")
        assert stalled_pos < watch_pos

    def test_stalled_goal_shows_stalled_label(self, tmp_path, monkeypatch, capsys):
        """Stalled goals display 'stalled' health state in list view."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        goals_md = data_dir / "goals.md"
        goals_md.write_text(
            "# Goals\n\n"
            "## Goal: Inactive Goal\n"
            "Status: active\n"
            "Related tasks:\n"
            "- Old Task\n"
        )
        tasks_path = data_dir / "tasks.md"
        tasks_path.write_text("- [x] Old Task\n")

        import janus.integrations.markdown_goals as mg
        import janus.integrations.markdown_tasks as mt
        import janus.integrations.metric_history as mhist

        monkeypatch.setattr(mg, "GOALS_PATH", goals_md)
        monkeypatch.setattr(mt, "TASKS_PATH", tasks_path)
        monkeypatch.setattr(mhist, "METRIC_HISTORY_PATH", data_dir / "metric_history.md")

        handle_goal_health([])
        captured = capsys.readouterr()
        assert "stalled" in captured.out
