"""Tests for goal milestone CLI commands.

Tests: goal milestone add, list, show, complete, update, and goal next.
All tests use temp fixtures ONLY.
"""

import pytest

from pathlib import Path


def _write_goals_file(tmp_path, content):
    goals_file = tmp_path / "goals.md"
    goals_file.write_text(content)
    return goals_file


def _write_tasks_file(tmp_path, content):
    tasks_file = tmp_path / "tasks.md"
    tasks_file.write_text(content)
    return tasks_file


def _setup_cli_fixtures(tmp_path, monkeypatch, goals_content="# Goals\n",
                        tasks_content=""):
    goals_file = _write_goals_file(tmp_path, goals_content)
    tasks_file = _write_tasks_file(tmp_path, tasks_content)
    monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
    monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
    monkeypatch.setattr("janus.services.goals.GOALS_PATH", goals_file)
    monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)
    return goals_file, tasks_file


# ===========================================================================
# Milestone add
# ===========================================================================

class TestMilestoneAddCLI:
    def test_milestone_add_creates_persisted_milestone(self, tmp_path, monkeypatch, capsys):
        from janus.goals_cli import handle_goal_add, handle_goal_milestone
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal", "--related-task", "Task A"])
        handle_goal_milestone(["add", "Test goal", "M1"])
        out = capsys.readouterr().out
        assert "Added milestone: M1" in out
        assert "order: 0" in out

    def test_milestone_add_with_options(self, tmp_path, monkeypatch, capsys):
        from janus.goals_cli import handle_goal_add, handle_goal_milestone
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        handle_goal_milestone([
            "add", "Test goal", "Register",
            "--description", "Sign up",
            "--deadline", "2026-09-30",
            "--status", "open",
            "--related-task", "Buy shoes",
        ])
        out = capsys.readouterr().out
        assert "Added milestone: Register" in out
        assert "Deadline: 2026-09-30" in out

    def test_milestone_add_requires_goal_title(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_milestone
        _setup_cli_fixtures(tmp_path, monkeypatch)
        with pytest.raises(SystemExit):
            handle_goal_milestone(["add"])

    def test_milestone_add_nonexistent_goal(self, tmp_path, monkeypatch, capsys):
        from janus.goals_cli import handle_goal_milestone
        _setup_cli_fixtures(tmp_path, monkeypatch)
        with pytest.raises(SystemExit):
            handle_goal_milestone(["add", "Ghost goal", "M1"])

    def test_milestone_add_invalid_status(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_add, handle_goal_milestone
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        with pytest.raises(SystemExit):
            handle_goal_milestone([
                "add", "Test goal", "M1",
                "--status", "pending",
            ])

    def test_milestone_add_duplicate_title(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_add, handle_goal_milestone
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        handle_goal_milestone(["add", "Test goal", "M1"])
        with pytest.raises(SystemExit):
            handle_goal_milestone(["add", "Test goal", "M1"])


# ===========================================================================
# Milestone list
# ===========================================================================

class TestMilestoneListCLI:
    def test_list_shows_milestone(self, tmp_path, monkeypatch, capsys):
        from janus.goals_cli import handle_goal_add, handle_goal_milestone
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        handle_goal_milestone(["add", "Test goal", "M1"])
        handle_goal_milestone(["add", "Test goal", "M2"])
        handle_goal_milestone(["list", "Test goal"])
        out = capsys.readouterr().out
        assert "M1" in out
        assert "M2" in out
        # M1 should have order 0, M2 order 1
        assert "order: 0" in out
        assert "order: 1" in out

    def test_list_empty_milestones(self, tmp_path, monkeypatch, capsys):
        from janus.goals_cli import handle_goal_add, handle_goal_milestone
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        handle_goal_milestone(["list", "Test goal"])
        out = capsys.readouterr().out
        assert "No milestones defined" in out

    def test_list_nonexistent_goal(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_milestone
        _setup_cli_fixtures(tmp_path, monkeypatch)
        with pytest.raises(SystemExit):
            handle_goal_milestone(["list", "Ghost"])


# ===========================================================================
# Milestone show
# ===========================================================================

class TestMilestoneShowCLI:
    def test_show_milestone_details(self, tmp_path, monkeypatch, capsys):
        from janus.goals_cli import handle_goal_add, handle_goal_milestone
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        handle_goal_milestone([
            "add", "Test goal", "Register",
            "--description", "Sign up for event",
            "--deadline", "2026-09-30",
            "--related-task", "Buy shoes",
        ])
        handle_goal_milestone(["show", "Test goal", "Register"])
        out = capsys.readouterr().out
        assert "MILESTONE: Register" in out
        assert "Sign up for event" in out
        assert "2026-09-30" in out
        assert "Buy shoes" in out

    def test_show_nonexistent_milestone(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_add, handle_goal_milestone
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        with pytest.raises(SystemExit):
            handle_goal_milestone(["show", "Test goal", "Ghost"])

    def test_show_requires_two_args(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_milestone
        _setup_cli_fixtures(tmp_path, monkeypatch)
        with pytest.raises(SystemExit):
            handle_goal_milestone(["show", "Test goal"])


# ===========================================================================
# Milestone complete
# ===========================================================================

class TestMilestoneCompleteCLI:
    def test_complete_milestone(self, tmp_path, monkeypatch, capsys):
        from janus.goals_cli import handle_goal_add, handle_goal_milestone
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        handle_goal_milestone(["add", "Test goal", "M1"])
        handle_goal_milestone(["complete", "Test goal", "M1"])
        out = capsys.readouterr().out
        assert "Completed milestone: M1" in out

    def test_complete_persists(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_add, handle_goal_milestone
        from janus.integrations.markdown_goals import load_goals
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        handle_goal_milestone(["add", "Test goal", "M1"])
        handle_goal_milestone(["complete", "Test goal", "M1"])
        goals = load_goals()
        assert goals[0].milestones[0]["status"] == "completed"

    def test_complete_nonexistent_raises(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_add, handle_goal_milestone
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        with pytest.raises(SystemExit):
            handle_goal_milestone(["complete", "Test goal", "Ghost"])


# ===========================================================================
# Milestone update
# ===========================================================================

class TestMilestoneUpdateCLI:
    def test_update_status(self, tmp_path, monkeypatch, capsys):
        from janus.goals_cli import handle_goal_add, handle_goal_milestone
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        handle_goal_milestone(["add", "Test goal", "M1"])
        handle_goal_milestone([
            "update", "Test goal", "M1",
            "--status", "in_progress",
        ])
        out = capsys.readouterr().out
        assert "Updated milestone: M1" in out
        assert "in_progress" in out

    def test_update_description(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_add, handle_goal_milestone
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        handle_goal_milestone(["add", "Test goal", "M1"])
        handle_goal_milestone([
            "update", "Test goal", "M1",
            "--description", "New desc",
        ])

    def test_update_add_related_task(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_add, handle_goal_milestone
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        handle_goal_milestone(["add", "Test goal", "M1"])
        handle_goal_milestone([
            "update", "Test goal", "M1",
            "--add-related-task", "Task B",
        ])

    def test_update_invalid_status(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_add, handle_goal_milestone
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        handle_goal_milestone(["add", "Test goal", "M1"])
        with pytest.raises(SystemExit):
            handle_goal_milestone([
                "update", "Test goal", "M1",
                "--status", "invalid",
            ])

    def test_update_invalid_date(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_add, handle_goal_milestone
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        handle_goal_milestone(["add", "Test goal", "M1"])
        with pytest.raises(SystemExit):
            handle_goal_milestone([
                "update", "Test goal", "M1",
                "--deadline", "not-a-date",
            ])


# ===========================================================================
# No regression: existing goal commands still work with milestones
# ===========================================================================

class TestGoalCommandsWithMilestones:
    def test_goal_show_displays_milestones(self, tmp_path, monkeypatch, capsys):
        from janus.goals_cli import handle_goal_add, handle_goal_milestone_add, handle_goal_show
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        handle_goal_milestone_add([
            "Test goal", "M1",
            "--description", "Sign up",
            "--deadline", "2026-10-01",
            "--related-task", "Task A",
        ])
        handle_goal_show(["Test goal"])
        out = capsys.readouterr().out
        assert "Test goal" in out
        assert "Milestones:" in out
        assert "M1" in out
        assert "2026-10-01" in out
        assert "Sign up" in out
        assert "Task A" in out

    def test_goal_show_no_milestones(self, tmp_path, monkeypatch, capsys):
        from janus.goals_cli import handle_goal_add, handle_goal_show
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        handle_goal_show(["Test goal"])
        out = capsys.readouterr().out
        assert "No milestones." in out

    def test_goal_list_works_with_milestones(self, tmp_path, monkeypatch, capsys):
        from janus.goals_cli import handle_goal_add, handle_goal_milestone_add, handle_goal_list
        _setup_cli_fixtures(tmp_path, monkeypatch)
        handle_goal_add(["Test goal"])
        handle_goal_milestone_add(["Test goal", "M1"])
        handle_goal_list([])
        out = capsys.readouterr().out
        assert "Test goal" in out


# ===========================================================================
# CLI dispatcher integration
# ===========================================================================

class TestCLIDispatcher:
    def test_main_goal_milestone_add(self, tmp_path, monkeypatch, capsys):
        """Verify main() dispatches goal milestone correctly."""
        _setup_cli_fixtures(tmp_path, monkeypatch)
        import janus
        monkeypatch.setattr("sys.argv", ["janus", "goal", "add", "Test goal"])
        janus.main()
        monkeypatch.setattr("sys.argv", ["janus", "goal", "milestone", "add", "Test goal", "M1"])
        janus.main()
        out = capsys.readouterr().out
        assert "Added milestone: M1" in out

    def test_main_goal_next(self, tmp_path, monkeypatch, capsys):
        """Verify main() dispatches goal next correctly."""
        _setup_cli_fixtures(tmp_path, monkeypatch)
        from janus.services.goals import add_goal
        add_goal("Test goal")
        import janus
        monkeypatch.setattr("sys.argv", ["janus", "goal", "next", "Test goal"])
        janus.main()
        out = capsys.readouterr().out
        assert "No next action" in out

    def test_main_goal_no_subcommand(self, tmp_path, monkeypatch, capsys):
        """Verify usage is printed when no subcommand."""
        import janus
        monkeypatch.setattr("sys.argv", ["janus", "goal"])
        janus.main()
        out = capsys.readouterr().out
        assert "Usage" in out
        assert "milestone" in out
        assert "next" in out
