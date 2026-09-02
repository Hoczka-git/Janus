"""Tests for the 'janus goal next <title>' CLI command.

Tests derive_next_action integration through the CLI: R1 (task in milestone),
R2 (task outside milestone), R3 (next milestone as action), R5 (no next action).
"""

import pytest


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


class TestGoalNextCLI:
    def test_goal_next_milestone_task(self, tmp_path, monkeypatch, capsys):
        """R1: open task in current milestone."""
        from janus.goals_cli import handle_goal_milestone_add, handle_goal_next
        from janus.services.goals import add_goal
        _setup_cli_fixtures(
            tmp_path, monkeypatch,
            goals_content="# Goals\n",
            tasks_content="- [ ] Task A\n",
        )
        add_goal("Test goal", related_tasks=["Task A"])
        handle_goal_milestone_add(["Test goal", "M1", "--related-task", "Task A"])
        handle_goal_next(["Test goal"])
        out = capsys.readouterr().out
        assert "Next action: Task A" in out
        assert "(task)" in out

    def test_goal_next_no_milestone_open_task(self, tmp_path, monkeypatch, capsys):
        """R2: open task outside any milestone."""
        from janus.services.goals import add_goal
        from janus.goals_cli import handle_goal_next
        _setup_cli_fixtures(
            tmp_path, monkeypatch,
            goals_content="# Goals\n",
            tasks_content="- [ ] Task A\n",
        )
        add_goal("Test goal", related_tasks=["Task A"])
        handle_goal_next(["Test goal"])
        out = capsys.readouterr().out
        assert "Next action: Task A" in out
        assert "No milestone" in out

    def test_goal_next_milestone_as_action(self, tmp_path, monkeypatch, capsys):
        """R3: no open tasks, next milestone is the action."""
        from janus.services.goals import add_goal
        from janus.goals_cli import handle_goal_milestone_add, handle_goal_next
        _setup_cli_fixtures(
            tmp_path, monkeypatch,
            goals_content="# Goals\n",
            tasks_content="",
        )
        add_goal("Test goal")
        handle_goal_milestone_add(["Test goal", "M1"])
        handle_goal_next(["Test goal"])
        out = capsys.readouterr().out
        assert "Next action: M1" in out
        assert "(milestone)" in out

    def test_goal_next_no_action(self, tmp_path, monkeypatch, capsys):
        """R5: all tasks done, all milestones completed → No next action."""
        from janus.services.goals import add_goal
        from janus.goals_cli import handle_goal_milestone_add, handle_goal_next
        _setup_cli_fixtures(
            tmp_path, monkeypatch,
            goals_content="# Goals\n",
            tasks_content="- [x] Task A\n",
        )
        add_goal("Test goal", related_tasks=["Task A"])
        handle_goal_milestone_add([
            "Test goal", "M1", "--related-task", "Task A",
            "--status", "completed",
        ])
        handle_goal_milestone_add(["Test goal", "M2", "--status", "completed"])
        handle_goal_next(["Test goal"])
        out = capsys.readouterr().out
        assert "No next action." in out

    def test_goal_next_nonexistent_goal(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_next
        _setup_cli_fixtures(tmp_path, monkeypatch)
        with pytest.raises(SystemExit):
            handle_goal_next(["Ghost"])

    def test_goal_next_requires_title(self, tmp_path, monkeypatch):
        from janus.goals_cli import handle_goal_next
        _setup_cli_fixtures(tmp_path, monkeypatch)
        with pytest.raises(SystemExit):
            handle_goal_next([])
