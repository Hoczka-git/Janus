"""Tests for 'janus task --help' and leaf-level 'janus task <sub> --help'.

Covers the dispatcher-level help (janus task --help) and per-handler
help for add, complete, list, state, and progress subcommands.
"""

import janus
from janus.tasks_cli import print_task_help


class TestTaskHelpRouter:
    """janus task --help / -h at the dispatcher (main()) level."""

    def test_task_help_long(self, capsys):
        """janus task --help prints usage, description, subcommands, options."""
        import sys
        sys.argv = ["janus", "task", "--help"]
        janus.main()
        out = capsys.readouterr().out
        assert "Usage: janus task" in out
        assert "Manage tasks." in out
        assert "add" in out
        assert "complete" in out
        assert "list" in out
        assert "state" in out
        assert "progress" in out
        assert "-h, --help" in out

    def test_task_help_short(self, capsys):
        """janus task -h prints the same help."""
        import sys
        sys.argv = ["janus", "task", "-h"]
        janus.main()
        out = capsys.readouterr().out
        assert "Usage: janus task" in out
        assert "Manage tasks." in out

    def test_task_no_subcommand_prints_help(self, capsys):
        """janus task (no subcommand) still prints help."""
        import sys
        sys.argv = ["janus", "task"]
        janus.main()
        out = capsys.readouterr().out
        assert "Usage: janus task" in out
        assert "Manage tasks." in out


class TestLeafHelp:
    """Per-handler --help for each task subcommand."""

    def test_task_add_help(self, capsys):
        """janus task add --help prints help, does not attempt to create."""
        from janus.tasks_cli import handle_task_add
        from unittest.mock import patch
        with patch("janus.tasks_cli.add_task") as mock_add, \
             patch("janus.tasks_cli.list_tasks", return_value=[]):
            handle_task_add(["--help"])
        out = capsys.readouterr().out
        assert "Usage: janus task add" in out
        assert "--due" in out
        assert "--priority" in out
        assert mock_add.call_count == 0

    def test_task_complete_help(self, capsys):
        """janus task complete --help prints help, does not attempt to complete."""
        from janus.tasks_cli import handle_task_complete
        from unittest.mock import patch
        with patch("janus.tasks_cli.complete_task") as mock_complete:
            handle_task_complete(["--help"])
        out = capsys.readouterr().out
        assert "Usage: janus task complete" in out
        assert mock_complete.call_count == 0

    def test_task_list_help(self, capsys):
        """janus task list --help prints help, does not attempt to list."""
        from janus.tasks_cli import handle_task_list
        from unittest.mock import patch
        with patch("janus.tasks_cli.list_tasks") as mock_list:
            handle_task_list(["--help"])
        out = capsys.readouterr().out
        assert "Usage: janus task list" in out
        assert mock_list.call_count == 0

    def test_task_state_help(self, capsys):
        """janus task state --help prints help, does not attempt to update."""
        from janus.tasks_cli import handle_task_state
        from unittest.mock import patch
        with patch("janus.tasks_cli.set_task_state") as mock_state:
            handle_task_state(["--help"])
        out = capsys.readouterr().out
        assert "Usage: janus task state" in out
        assert "--state" in out
        assert mock_state.call_count == 0

    def test_task_progress_help(self, capsys):
        """janus task progress --help prints help, does not attempt to update."""
        from janus.tasks_cli import handle_task_progress
        from unittest.mock import patch
        with patch("janus.tasks_cli.set_task_progress") as mock_progress:
            handle_task_progress(["--help"])
        out = capsys.readouterr().out
        assert "Usage: janus task progress" in out
        assert "--pct" in out
        assert mock_progress.call_count == 0

    def test_task_add_help_does_not_create_title(self, capsys):
        """janus task add --help is treated as help, not a task titled '--help'."""
        from janus.tasks_cli import handle_task_add
        from unittest.mock import patch
        with patch("janus.tasks_cli.add_task") as mock_add, \
             patch("janus.tasks_cli.list_tasks", return_value=[]):
            handle_task_add(["--help"])
        out = capsys.readouterr().out
        assert "Usage: janus task add" in out
        assert mock_add.call_count == 0
        assert "Added task:" not in out


class TestPrintTaskHelp:
    """Direct unit tests for print_task_help()."""

    def test_print_task_help_contains_subcommands(self, capsys):
        print_task_help()
        out = capsys.readouterr().out
        assert "Usage: janus task <subcommand> [options]" in out
        for sub in ("add", "complete", "list", "state", "progress"):
            assert sub in out
        assert "-h, --help" in out
