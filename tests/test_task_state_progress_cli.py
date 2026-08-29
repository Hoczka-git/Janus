"""Tests for 'janus task state' and 'janus task progress' CLI handlers.

Style zgodny z test_tasks_cli.py — mockowanie service callów + capys output.
"""

from io import StringIO
from unittest.mock import patch

import pytest

from janus.models.task import Task
from janus.tasks_cli import handle_task_state, handle_task_progress


# =============================================================================
# Task State CLI
# =============================================================================


class TestTaskStateCLI:
    def _make_task(self, title="Test task", state="todo"):
        return type("Task", (), {
            "title": title,
            "due_date": None,
            "priority": 1,
            "state": state,
            "progress": None,
        })()

    def test_set_state_in_progress(self, capsys):
        with patch("janus.tasks_cli.set_task_state") as mock_set:
            mock_set.return_value = self._make_task(state="in_progress")
            handle_task_state(["Test task", "--state", "in_progress"])

        out = capsys.readouterr().out
        assert "Updated task state:" in out
        assert "in_progress" in out
        mock_set.assert_called_once_with("Test task", "in_progress")

    def test_set_state_blocked(self, capsys):
        with patch("janus.tasks_cli.set_task_state") as mock_set:
            mock_set.return_value = self._make_task(state="blocked")
            handle_task_state(["Test task", "--state", "blocked"])

        out = capsys.readouterr().out
        assert "blocked" in out
        mock_set.assert_called_once_with("Test task", "blocked")

    def test_set_state_todo(self, capsys):
        with patch("janus.tasks_cli.set_task_state") as mock_set:
            mock_set.return_value = self._make_task(state="todo")
            handle_task_state(["Test task", "--state", "todo"])

        out = capsys.readouterr().out
        assert "todo" in out
        mock_set.assert_called_once_with("Test task", "todo")

    def test_set_state_multword_title(self, capsys):
        with patch("janus.tasks_cli.set_task_state") as mock_set:
            mock_set.return_value = self._make_task(title="Buy running shoes", state="in_progress")
            handle_task_state(["Buy", "running", "shoes", "--state", "in_progress"])

        mock_set.assert_called_once_with("Buy running shoes", "in_progress")

    def test_missing_title_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_task_state(["--state", "in_progress"])
        err = capsys.readouterr().err
        assert "title is required" in err

    def test_missing_state_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_task_state(["Test task"])
        err = capsys.readouterr().err
        assert "--state is required" in err

    def test_invalid_state_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_task_state(["Test task", "--state", "done"])
        err = capsys.readouterr().err
        assert "invalid state" in err
        assert "todo" in err
        assert "in_progress" in err
        assert "blocked" in err

    def test_service_error_exits(self, capsys):
        with patch("janus.tasks_cli.set_task_state") as mock_set:
            mock_set.side_effect = ValueError("Task not found: Missing")
            with pytest.raises(SystemExit):
                handle_task_state(["Missing", "--state", "in_progress"])
        err = capsys.readouterr().err
        assert "Task not found" in err


# =============================================================================
# Task Progress CLI
# =============================================================================


class TestTaskProgressCLI:
    def _make_task(self, title="Test task", progress=0):
        return type("Task", (), {
            "title": title,
            "due_date": None,
            "priority": 1,
            "state": None,
            "progress": progress,
        })()

    def test_set_progress_70(self, capsys):
        with patch("janus.tasks_cli.set_task_progress") as mock_set:
            mock_set.return_value = self._make_task(progress=70)
            handle_task_progress(["Test task", "--pct", "70"])

        out = capsys.readouterr().out
        assert "Updated task progress:" in out
        assert "70%" in out
        mock_set.assert_called_once_with("Test task", 70)

    def test_set_progress_100(self, capsys):
        with patch("janus.tasks_cli.set_task_progress") as mock_set:
            mock_set.return_value = self._make_task(progress=100)
            handle_task_progress(["Test task", "--pct", "100"])

        out = capsys.readouterr().out
        assert "100%" in out
        mock_set.assert_called_once_with("Test task", 100)

    def test_set_progress_multword_title(self, capsys):
        with patch("janus.tasks_cli.set_task_progress") as mock_set:
            mock_set.return_value = self._make_task(title="Prepare training plan", progress=50)
            handle_task_progress(["Prepare", "training", "plan", "--pct", "50"])

        mock_set.assert_called_once_with("Prepare training plan", 50)

    def test_missing_title_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_task_progress(["--pct", "50"])
        err = capsys.readouterr().err
        assert "title is required" in err

    def test_missing_pct_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_task_progress(["Test task"])
        err = capsys.readouterr().err
        assert "--pct is required" in err

    def test_invalid_pct_non_integer_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_task_progress(["Test task", "--pct", "abc"])
        err = capsys.readouterr().err
        assert "--pct requires an integer" in err

    def test_invalid_pct_below_zero_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_task_progress(["Test task", "--pct", "-1"])
        err = capsys.readouterr().err
        assert "--pct requires an integer" in err

    def test_invalid_pct_above_100_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_task_progress(["Test task", "--pct", "101"])
        err = capsys.readouterr().err
        assert "--pct requires an integer" in err

    def test_service_error_exits(self, capsys):
        with patch("janus.tasks_cli.set_task_progress") as mock_set:
            mock_set.side_effect = ValueError("Task not found: Missing")
            with pytest.raises(SystemExit):
                handle_task_progress(["Missing", "--pct", "50"])
        err = capsys.readouterr().err
        assert "Task not found" in err
