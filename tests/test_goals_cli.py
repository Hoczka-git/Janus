"""Tests for Goal CLI handlers.

All tests use temp fixtures ONLY.
"""
import pytest
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch


# ===========================================================================
# Helper functions
# ===========================================================================

def _write_goals_file(tmp_path, content):
    goals_file = tmp_path / "goals.md"
    goals_file.write_text(content)
    return goals_file


def _write_tasks_file(tmp_path, content):
    tasks_file = tmp_path / "tasks.md"
    tasks_file.write_text(content)
    return tasks_file


def _setup_cli_fixtures(tmp_path, monkeypatch, goals_content="# Goals\n", tasks_content="- [ ] Test task\n"):
    goals_file = _write_goals_file(tmp_path, goals_content)
    tasks_file = _write_tasks_file(tmp_path, tasks_content)
    monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
    monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
    monkeypatch.setattr("janus.services.goals.GOALS_PATH", goals_file)
    return goals_file, tasks_file


# ===========================================================================
# Validation tests
# ===========================================================================

class TestGoalListValidation:
    def test_list_accepts_no_args(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_list
        _setup_cli_fixtures(tmp_path, monkeypatch)
        # Should not raise
        handle_goal_list([])

    def test_list_rejects_args(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_list
        _setup_cli_fixtures(tmp_path, monkeypatch)
        with pytest.raises(SystemExit):
            handle_goal_list(["extra"])


class TestGoalShowValidation:
    def test_show_requires_title(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_show
        _setup_cli_fixtures(tmp_path, monkeypatch)
        with pytest.raises(SystemExit):
            handle_goal_show([])

    def test_show_with_title(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_show
        goals_file = _setup_cli_fixtures(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: Test goal\nStatus: active\n",
        )
        # Should not raise for existing goal
        handle_goal_show(["Test goal"])


class TestGoalAddValidation:
    def test_add_requires_title(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_add
        _setup_cli_fixtures(tmp_path, monkeypatch)
        with pytest.raises(SystemExit):
            handle_goal_add([])

    def test_add_with_title(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_add
        _setup_cli_fixtures(tmp_path, monkeypatch)
        # Should not raise
        handle_goal_add(["Test goal"])

    def test_add_duplicate_title(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_add
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        with pytest.raises(SystemExit):
            handle_goal_add(["Test goal"])

    def test_add_invalid_status(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_add
        _setup_cli_fixtures(tmp_path, monkeypatch)
        with pytest.raises(SystemExit):
            handle_goal_add(["Test goal", "--status", "pending"])

    def test_add_invalid_direction(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_add
        _setup_cli_fixtures(tmp_path, monkeypatch)
        with pytest.raises(SystemExit):
            handle_goal_add(["Test goal", "--direction", "sideways"])

    def test_add_invalid_date(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_add
        _setup_cli_fixtures(tmp_path, monkeypatch)
        with pytest.raises(SystemExit):
            handle_goal_add(["Test goal", "--deadline", "not-a-date"])


class TestGoalUpdateValidation:
    def test_update_requires_title(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_update
        _setup_cli_fixtures(tmp_path, monkeypatch)
        with pytest.raises(SystemExit):
            handle_goal_update([])

    def test_update_nonexistent_goal(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_update
        _setup_cli_fixtures(tmp_path, monkeypatch)
        with pytest.raises(SystemExit):
            handle_goal_update(["NonExistent"])

    def test_update_invalid_status(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_add, handle_goal_update
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        with pytest.raises(SystemExit):
            handle_goal_update(["Test goal", "--status", "pending"])

    def test_update_invalid_direction(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_add, handle_goal_update
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        with pytest.raises(SystemExit):
            handle_goal_update(["Test goal", "--direction", "sideways"])

    def test_update_invalid_date(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_add, handle_goal_update
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        with pytest.raises(SystemExit):
            handle_goal_update(["Test goal", "--deadline", "not-a-date"])


class TestGoalCompleteValidation:
    def test_complete_requires_title(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_complete
        _setup_cli_fixtures(tmp_path, monkeypatch)
        with pytest.raises(SystemExit):
            handle_goal_complete([])

    def test_complete_nonexistent_goal(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_complete
        _setup_cli_fixtures(tmp_path, monkeypatch)
        with pytest.raises(SystemExit):
            handle_goal_complete(["NonExistent"])


# ===========================================================================
# Metric goal tests
# ===========================================================================

class TestGoalAddMetric:
    def test_add_metric_goal(self, tmp_path, monkeypatch, capsys):
        from janus.goals_cli import handle_goal_add
        goals_file = _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add([
            "Body fat reduction",
            "--metric", "Body fat %",
            "--unit", "%",
            "--start", "23.0",
            "--current", "20.0",
            "--target", "15.0",
            "--direction", "decrease",
        ])
        out = capsys.readouterr().out
        assert "Added goal: Body fat reduction" in out
        assert "Metric: Body fat %" in out
        assert "Progress: 37.5%" in out

    def test_add_metric_goal_with_related_tasks(self, tmp_path, monkeypatch, capsys):
        from janus.goals_cli import handle_goal_add
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add([
            "Hybrid goal",
            "--metric", "Savings",
            "--start", "0",
            "--current", "5000",
            "--target", "10000",
            "--direction", "increase",
            "--related-task", "Task A",
            "--related-task", "Task B",
        ])
        out = capsys.readouterr().out
        assert "Progress: 50.0%" in out


class TestGoalListMetric:
    def test_list_with_metric_goal(self, tmp_path, monkeypatch, capsys):
        from janus.goals_cli import handle_goal_add, handle_goal_list
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add([
            "Body fat",
            "--metric", "Body fat %",
            "--start", "23.0",
            "--current", "20.0",
            "--target", "15.0",
            "--direction", "decrease",
        ])
        handle_goal_list([])
        out = capsys.readouterr().out
        assert "Body fat" in out
        assert "37.5%" in out


class TestGoalShowMetric:
    def test_show_metric_goal(self, tmp_path, monkeypatch, capsys):
        from janus.goals_cli import handle_goal_add, handle_goal_show
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add([
            "Body fat",
            "--metric", "Body fat %",
            "--start", "23.0",
            "--current", "20.0",
            "--target", "15.0",
            "--direction", "decrease",
        ])
        handle_goal_show(["Body fat"])
        out = capsys.readouterr().out
        assert "Metric:      Body fat %" in out
        assert "Current:     20.0" in out
        assert "Target:      15.0" in out
        assert "Progress:    37.5%" in out
        assert "Detail:      20.0 → 15.0, decrease" in out


class TestGoalUpdateMetric:
    def test_update_metric_current_value(self, tmp_path, monkeypatch, capsys):
        from janus.goals_cli import handle_goal_add, handle_goal_update
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add([
            "Savings",
            "--metric", "Savings",
            "--start", "0",
            "--current", "3000",
            "--target", "10000",
            "--direction", "increase",
        ])
        handle_goal_update(["Savings", "--current", "5000"])
        out = capsys.readouterr().out
        assert "Progress: 50.0%" in out


# ===========================================================================
# Task goal tests
# ===========================================================================

class TestGoalAddTask:
    def test_add_task_goal(self, tmp_path, monkeypatch, capsys):
        from janus.goals_cli import handle_goal_add
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n## Goal: Japan trip\nStatus: active\nRelated tasks:\n- Buy flights\n- Book hotels\n",
        )
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Buy flights\n- [ ] Book hotels\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.services.goals.GOALS_PATH", goals_file)
        # List goals
        from janus.goals_cli import handle_goal_list
        handle_goal_list([])
        out = capsys.readouterr().out
        # List format: "  Japan trip                                 0.0%   0/2 tasks completed"
        assert "Japan trip" in out
        assert "0.0%" in out
        assert "0/2 tasks completed" in out


class TestGoalListWithCompletedTasks:
    def test_list_with_completed_tasks(self, tmp_path, monkeypatch, capsys):
        from janus.goals_cli import handle_goal_list
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n## Goal: Japan trip\nStatus: active\nRelated tasks:\n- Buy flights\n- Book hotels\n- Plan itinerary\n",
        )
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [x] Buy flights\n"
            "- [x] Book hotels\n"
            "- [ ] Plan itinerary\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.services.goals.GOALS_PATH", goals_file)
        handle_goal_list([])
        out = capsys.readouterr().out
        # List format: "  Japan trip                                66.7%   2/3 tasks completed"
        assert "Japan trip" in out
        assert "66.7%" in out
        assert "2/3 tasks completed" in out


class TestGoalListRelatedTaskDedup:
    def test_duplicate_related_tasks_dedup_in_goal(self, tmp_path, monkeypatch, capsys):
        from janus.models.goal import Goal
        from janus.services.goals import add_goal
        goals_file = _write_goals_file(tmp_path, "# Goals\n")
        tasks_file = _write_tasks_file(tmp_path, "")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.services.goals.GOALS_PATH", goals_file)
        g = add_goal("Japan trip", related_tasks=["Buy flights", "Buy flights", "Book hotels"])
        assert g.related_tasks == ["Buy flights", "Book hotels"]


# ===========================================================================
# Title immutability tests
# ===========================================================================

class TestTitleImmutability:
    def test_update_does_not_change_title(self, tmp_path, monkeypatch, capsys):
        from janus.goals_cli import handle_goal_add, handle_goal_update
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Original title"])
        handle_goal_update(["Original title", "--description", "New desc"])
        out = capsys.readouterr().out
        assert "Updated goal: Original title" in out


class TestNoDeleteGoal:
    def test_no_delete_goal_command(self):
        import janus.goals_cli as cli
        assert not hasattr(cli, "handle_goal_delete")

    def test_no_delete_goal_in_service(self):
        import janus.services.goals as svc
        assert not hasattr(svc, "delete_goal")


# ===========================================================================
# Goal health CLI tests (§12.6)
# ===========================================================================

class TestGoalHealthCLI:
    def test_health_list_no_goals(self, tmp_path, monkeypatch, capsys):
        """`janus goal health` with no active goals prints 'No active goals.'"""
        goals_file = _write_goals_file(tmp_path, "# Goals\n")
        tasks_file = _write_tasks_file(tmp_path, "")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        from janus.goals_cli import handle_goal_health
        handle_goal_health([])
        out = capsys.readouterr().out
        assert "No active goals." in out

    def test_health_list_shows_healthy_goal(self, tmp_path, monkeypatch, capsys):
        """Health list shows a healthy goal with its state."""
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n## Goal: My Goal\nStatus: active\nRelated tasks:\n- Open task\n"
        )
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Open task\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        from janus.goals_cli import handle_goal_health
        handle_goal_health([])
        out = capsys.readouterr().out
        assert "My Goal" in out
        assert "healthy" in out

    def test_health_list_sorts_by_severity(self, tmp_path, monkeypatch, capsys):
        """Health list sorts stalled first, then watch, then healthy."""
        from datetime import timedelta
        today = date.today()
        soon = (today + timedelta(days=3)).isoformat()
        far = (today + timedelta(days=365)).isoformat()
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n"
            f"## Goal: Stalled Goal\nStatus: active\nDeadline: {far}\n"
            f"## Goal: Watch Goal\nStatus: active\nDeadline: {soon}\n"
            "## Goal: Healthy Goal\nStatus: active\nRelated tasks:\n- Open task\n"
        )
        tasks_file = _write_tasks_file(tmp_path, "- [x] Done task\n- [ ] Open task\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        from janus.goals_cli import handle_goal_health
        handle_goal_health([])

        out = capsys.readouterr().out
        stalled_idx = next(i for i, l in enumerate(out.split("\n")) if "Stalled Goal" in l)
        watch_idx = next(i for i, l in enumerate(out.split("\n")) if "Watch Goal" in l)
        healthy_idx = next(i for i, l in enumerate(out.split("\n")) if "Healthy Goal" in l)
        assert stalled_idx < watch_idx < healthy_idx

    def test_health_single_goal_healthy(self, tmp_path, monkeypatch, capsys):
        """`janus goal health <title>` shows full assessment for a single goal."""
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n## Goal: My Goal\nStatus: active\nRelated tasks:\n- Open task\n"
        )
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Open task\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        from janus.goals_cli import handle_goal_health
        handle_goal_health(["My Goal"])
        out = capsys.readouterr().out
        assert "JANUS — GOAL HEALTH: My Goal" in out
        assert "State:" in out
        assert "healthy" in out
        assert "Progress:" in out

    def test_health_single_goal_stalled(self, tmp_path, monkeypatch, capsys):
        """Single goal health shows stalled with dominant signal."""
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n## Goal: Stalled Goal\nStatus: active\nDeadline: 2027-01-01\n"
        )
        tasks_file = _write_tasks_file(tmp_path, "- [x] Done task\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        from janus.goals_cli import handle_goal_health
        handle_goal_health(["Stalled Goal"])
        out = capsys.readouterr().out
        assert "stalled" in out
        assert "Dominant:" in out

    def test_health_single_goal_not_found(self, tmp_path, monkeypatch, capsys):
        """Goal not found prints error and exits with code 1."""
        goals_file = _write_goals_file(tmp_path, "# Goals\n")
        tasks_file = _write_tasks_file(tmp_path, "")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        from janus.goals_cli import handle_goal_health
        with pytest.raises(SystemExit) as exc_info:
            handle_goal_health(["Nonexistent Goal"])
        assert exc_info.value.code == 1