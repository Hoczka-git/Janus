"""Tests for CLI goal commands.

Uses capsys to capture stdout/stderr.
All tests use temp fixtures. Does NOT modify data/goals.md.
"""

import sys
from pathlib import Path

import pytest

from janus import main
from janus.integrations.markdown_goals import GOALS_PATH
from janus.integrations.markdown_tasks import TASKS_PATH


def _setup_fixtures(tmp_path, monkeypatch):
    goals_file = tmp_path / "goals.md"
    tasks_file = tmp_path / "tasks.md"
    goals_file.write_text("# Goals\n")
    tasks_file.write_text("")
    monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
    monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
    monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)


def test_list_empty(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    sys.argv = ["janus", "goal", "list"]
    main()

    out = capsys.readouterr().out
    assert "JANUS — GOALS" in out
    assert "ACTIVE (0):" in out
    assert "COMPLETED (0):" in out
    assert "INACTIVE (0):" in out


def test_show_not_found(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    sys.argv = ["janus", "goal", "show", "Nonexistent"]
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1

    err = capsys.readouterr().err
    assert "Goal not found" in err


def test_add_success(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    sys.argv = [
        "janus", "goal", "add",
        "Body fat reduction",
        "--metric", "Body fat %",
        "--start", "23",
        "--current", "20",
        "--target", "15",
        "--direction", "decrease",
    ]
    main()

    out = capsys.readouterr().out
    assert "Added goal: Body fat reduction" in out
    assert "Progress: 37.5%" in out

    # Verify persistence
    from janus.integrations.markdown_goals import load_goals
    goals = load_goals()
    assert len(goals) == 1
    g = goals[0]
    assert g.title == "Body fat reduction"
    assert g.metric_name == "Body fat %"
    assert g.start_value == 23.0
    assert g.current_value == 20.0
    assert g.target_value == 15.0
    assert g.direction == "decrease"


def test_add_missing_title(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    sys.argv = ["janus", "goal", "add"]
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1

    err = capsys.readouterr().err
    assert "goal title is required" in err


def test_add_invalid_status(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    sys.argv = ["janus", "goal", "add", "X", "--status", "pending"]
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1

    err = capsys.readouterr().err
    assert "invalid status" in err


def test_add_invalid_direction(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    sys.argv = ["janus", "goal", "add", "X", "--direction", "sideways"]
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1

    err = capsys.readouterr().err
    assert "invalid direction" in err


def test_add_invalid_float(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    sys.argv = ["janus", "goal", "add", "X", "--start", "abc"]
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1

    err = capsys.readouterr().err
    assert "invalid number" in err


def test_add_invalid_date(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    sys.argv = ["janus", "goal", "add", "X", "--deadline", "bad"]
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1

    err = capsys.readouterr().err
    assert "invalid date" in err


def test_update_success(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    # First add a goal
    sys.argv = ["janus", "goal", "add", "X", "--metric", "Savings", "--start", "0", "--current", "4500", "--target", "10000", "--direction", "increase"]
    main()
    capsys.readouterr()  # clear

    # Then update
    sys.argv = ["janus", "goal", "update", "X", "--current", "19"]
    main()

    out = capsys.readouterr().out
    assert "Updated goal: X" in out

    from janus.integrations.markdown_goals import load_goals
    goals = load_goals()
    assert goals[0].current_value == 19.0


def test_update_not_found(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    sys.argv = ["janus", "goal", "update", "Nonexistent", "--current", "19"]
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1

    err = capsys.readouterr().err
    assert "Goal not found" in err


def test_update_add_task(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    sys.argv = ["janus", "goal", "add", "X"]
    main()
    capsys.readouterr()  # clear

    sys.argv = ["janus", "goal", "update", "X", "--add-related-task", "New task"]
    main()

    out = capsys.readouterr().out
    assert "Updated goal: X" in out

    from janus.integrations.markdown_goals import load_goals
    goals = load_goals()
    assert "New task" in goals[0].related_tasks


def test_update_add_duplicate_task(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    # Add goal with existing task
    sys.argv = ["janus", "goal", "add", "X", "--related-task", "Existing task"]
    main()
    capsys.readouterr()  # clear

    # Try to add duplicate
    sys.argv = ["janus", "goal", "update", "X", "--add-related-task", "Existing task"]
    main()

    out = capsys.readouterr().out
    assert "Updated goal: X" in out

    from janus.integrations.markdown_goals import load_goals
    goals = load_goals()
    assert goals[0].related_tasks == ["Existing task"]


def test_update_remove_task(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    sys.argv = ["janus", "goal", "add", "X", "--related-task", "Task to remove"]
    main()
    capsys.readouterr()  # clear

    sys.argv = ["janus", "goal", "update", "X", "--remove-related-task", "Task to remove"]
    main()

    out = capsys.readouterr().out
    assert "Updated goal: X" in out

    from janus.integrations.markdown_goals import load_goals
    goals = load_goals()
    assert "Task to remove" not in goals[0].related_tasks


def test_complete_success(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    sys.argv = ["janus", "goal", "add", "X"]
    main()
    capsys.readouterr()  # clear

    sys.argv = ["janus", "goal", "complete", "X"]
    main()

    out = capsys.readouterr().out
    assert "Completed goal: X" in out

    from janus.integrations.markdown_goals import load_goals
    g = load_goals()[0]
    assert g.status == "completed"


def test_complete_not_found(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    sys.argv = ["janus", "goal", "complete", "Nonexistent"]
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1

    err = capsys.readouterr().err
    assert "Goal not found" in err


def test_unknown_flag(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    sys.argv = ["janus", "goal", "add", "X", "--bogus"]
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1

    err = capsys.readouterr().err
    assert "unknown argument" in err


def test_list_with_metric_goal(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    sys.argv = [
        "janus", "goal", "add",
        "Body fat",
        "--metric", "Body fat %",
        "--start", "23",
        "--current", "20",
        "--target", "15",
        "--direction", "decrease",
    ]
    main()
    capsys.readouterr()  # clear

    sys.argv = ["janus", "goal", "list"]
    main()

    out = capsys.readouterr().out
    assert "Body fat" in out
    assert "37.5%" in out


def test_list_with_task_goal(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    # Write an open task and monkeypatch tasks path for the tasks service
    tasks_file = tmp_path / "tasks.md"
    tasks_file.write_text("- [ ] Task A\n")
    import janus.services.tasks as tasks_mod
    tasks_mod.TASKS_PATH = tasks_file
    import janus.integrations.markdown_tasks as md_tasks_mod
    md_tasks_mod.TASKS_PATH = tasks_file

    sys.argv = [
        "janus", "goal", "add",
        "Japan trip",
        "--related-task", "Task A",
    ]
    main()
    capsys.readouterr()  # clear

    # Complete the task
    sys.argv = ["janus", "task", "complete", "Task A"]
    main()
    capsys.readouterr()  # clear

    sys.argv = ["janus", "goal", "list"]
    main()

    out = capsys.readouterr().out
    assert "Japan trip" in out
    assert "1/1 tasks completed" in out


def test_show_metric_goal(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    sys.argv = [
        "janus", "goal", "add",
        "Body fat",
        "--metric", "Body fat %",
        "--unit", "%",
        "--start", "23",
        "--current", "20",
        "--target", "15",
        "--direction", "decrease",
        "--deadline", "2027-03-31",
    ]
    main()
    capsys.readouterr()  # clear

    sys.argv = ["janus", "goal", "show", "Body fat"]
    main()

    out = capsys.readouterr().out
    assert "JANUS — GOAL: Body fat" in out
    assert "Metric:      Body fat %" in out
    assert "Unit:        %" in out
    assert "Start:       23.0" in out
    assert "Current:     20.0" in out
    assert "Target:      15.0" in out
    assert "Direction:   decrease" in out
    assert "Deadline:    2027-03-31" in out
    assert "Progress:    37.5%" in out


def test_show_task_goal(capsys, tmp_path, monkeypatch):
    _setup_fixtures(tmp_path, monkeypatch)

    # Add task first — use add_goal to create a task-like goal, then reference it
    from janus.services.goals import add_goal
    add_goal(title="Task A", status="completed")
    add_goal(title="Task B", status="completed")

    sys.argv = [
        "janus", "goal", "add",
        "Trip",
        "--related-task", "Task A",
        "--related-task", "Task B",
    ]
    main()
    capsys.readouterr()  # clear

    sys.argv = ["janus", "goal", "show", "Trip"]
    main()

    out = capsys.readouterr().out
    assert "JANUS — GOAL: Trip" in out
    assert "Related tasks:" in out
    assert "Task A (open)" in out
    assert "Task B (open)" in out
    assert "Progress:    0.0%" in out
