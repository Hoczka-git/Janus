"""Tests for 'janus workout --help' and leaf-level 'janus workout <sub> --help'.

Covers the dispatcher-level help (janus workout --help) and per-handler
help for add, show, and summary subcommands.
"""

import sys

import janus
from janus.workout_cli import print_workout_help


class TestWorkoutHelpRouter:
    """janus workout --help / -h at the dispatcher (main()) level."""

    def test_workout_help_long(self, capsys):
        """janus workout --help prints usage, description, subcommands, options."""
        sys.argv = ["janus", "workout", "--help"]
        janus.main()
        out = capsys.readouterr().out
        assert "Usage: janus workout <subcommand> [options]" in out
        assert "Track and display workouts." in out
        assert "add" in out
        assert "show" in out
        assert "summary" in out
        assert "-h, --help" in out

    def test_workout_help_short(self, capsys):
        """janus workout -h prints the same help."""
        sys.argv = ["janus", "workout", "-h"]
        janus.main()
        out = capsys.readouterr().out
        assert "Usage: janus workout <subcommand> [options]" in out
        assert "Track and display workouts." in out

    def test_workout_no_subcommand_prints_help(self, capsys):
        """janus workout (no subcommand) still prints help."""
        sys.argv = ["janus", "workout"]
        janus.main()
        out = capsys.readouterr().out
        assert "Usage: janus workout <subcommand> [options]" in out
        assert "Track and display workouts." in out


class TestLeafHelp:
    """Per-handler --help for each workout subcommand."""

    def test_workout_add_help(self, capsys):
        """janus workout add --help prints help, does not attempt to save."""
        from janus.workout_cli import handle_workout_add
        from unittest.mock import patch
        with patch("janus.services.workout_analytics.add_workout_via_ingest") as mock_ingest:
            handle_workout_add(["--help"])
        out = capsys.readouterr().out
        assert "Usage: janus workout add" in out
        assert "--type" in out
        assert "--sets" in out
        assert "--distance" in out
        assert "--duration" in out
        assert mock_ingest.call_count == 0

    def test_workout_show_help(self, capsys):
        """janus workout show --help prints help, does not attempt to load."""
        from janus.workout_cli import handle_workout_show
        from unittest.mock import patch
        with patch("janus.workout_cli.find_last_n") as mock_find, \
             patch("janus.workout_cli.find_history_by_exercise") as mock_hist, \
             patch("janus.workout_cli.find_running_workouts") as mock_run, \
             patch("janus.workout_cli.find_workouts_by_date_range") as mock_range:
            handle_workout_show(["--help"])
        out = capsys.readouterr().out
        assert "Usage: janus workout show" in out
        assert "--last" in out
        assert "--from" in out
        assert "--to" in out
        assert "--running" in out
        assert "--exercise" in out
        assert mock_find.call_count == 0
        assert mock_hist.call_count == 0
        assert mock_run.call_count == 0
        assert mock_range.call_count == 0

    def test_workout_summary_help(self, capsys):
        """janus workout summary --help prints help, does not attempt to load."""
        from janus.workout_cli import handle_workout_summary
        from unittest.mock import patch
        with patch("janus.workout_cli.load_workouts") as mock_load, \
             patch("janus.workout_cli.compute_overall_summary") as mock_overall, \
             patch("janus.workout_cli.compute_running_summary") as mock_running, \
             patch("janus.workout_cli.compute_exercise_summary") as mock_ex:
            handle_workout_summary(["--help"])
        out = capsys.readouterr().out
        assert "Usage: janus workout summary" in out
        assert "--running" in out
        assert "--exercise" in out
        assert mock_load.call_count == 0
        assert mock_overall.call_count == 0
        assert mock_running.call_count == 0
        assert mock_ex.call_count == 0


class TestPrintWorkoutHelp:
    """Direct unit tests for print_workout_help()."""

    def test_print_workout_help_contains_subcommands(self, capsys):
        print_workout_help()
        out = capsys.readouterr().out
        assert "Usage: janus workout <subcommand> [options]" in out
        for sub in ("add", "show", "summary"):
            assert sub in out
        assert "-h, --help" in out
