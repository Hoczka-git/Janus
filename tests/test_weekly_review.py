"""Tests for Weekly Review milestone."""

from pathlib import Path
from datetime import date
from io import StringIO
from unittest.mock import patch

import pytest

from janus.models.goal import Goal
from janus.models.weekly_review import GoalReview, WeeklyReview
from janus.integrations.markdown_goals import load_goals, GOALS_PATH
from janus.services.weekly_review import create_weekly_review, TASKS_PATH
from janus.integrations.markdown_tasks import load_tasks, TASKS_PATH as TASKS_FILE_PATH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_goals_file(tmp_path, content):
    goals_file = tmp_path / "goals.md"
    goals_file.write_text(content)
    return goals_file


def _write_tasks_file(tmp_path, content):
    tasks_file = tmp_path / "tasks.md"
    tasks_file.write_text(content)
    return tasks_file


# ===========================================================================
# 1. Markdown goals parsing
# ===========================================================================

class TestMarkdownGoalsParsing:
    def test_valid_goal_parsing(self, tmp_path, monkeypatch):
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n"
            "\n"
            "## Goal: Test goal\n"
            "Description: A test goal.\n"
            "Status: active\n"
            "\n"
            "Related tasks:\n"
            "- Task A\n"
            "- Task B\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert len(goals) == 1
        goal = goals[0]
        assert goal.title == "Test goal"
        assert goal.description == "A test goal."
        assert goal.status == "active"
        assert goal.related_tasks == ["Task A", "Task B"]

    def test_active_goal_status(self, tmp_path, monkeypatch):
        goals_file = _write_goals_file(tmp_path, "# Goals\n\n## Goal: Active\nStatus: active\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert goals[0].status == "active"

    def test_completed_goal_status(self, tmp_path, monkeypatch):
        goals_file = _write_goals_file(tmp_path, "# Goals\n\n## Goal: Done\nStatus: completed\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert goals[0].status == "completed"

    def test_inactive_goal_status(self, tmp_path, monkeypatch):
        goals_file = _write_goals_file(tmp_path, "# Goals\n\n## Goal: Paused\nStatus: inactive\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert goals[0].status == "inactive"

    def test_related_tasks_parsing(self, tmp_path, monkeypatch):
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n- A\n- B\n- C\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert goals[0].related_tasks == ["A", "B", "C"]

    def test_empty_related_tasks(self, tmp_path, monkeypatch):
        goals_file = _write_goals_file(tmp_path, "# Goals\n\n## Goal: G\nStatus: active\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert goals[0].related_tasks == []

    def test_multiple_goals(self, tmp_path, monkeypatch):
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n"
            "## Goal: First\nStatus: active\n\n"
            "## Goal: Second\nStatus: active\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert len(goals) == 2
        assert goals[0].title == "First"
        assert goals[1].title == "Second"

    def test_malformed_goal_status_raises(self, tmp_path, monkeypatch):
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n## Goal: Bad\nStatus: unknown\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        with pytest.raises(ValueError, match="Invalid goal status"):
            load_goals()

    def test_missing_goals_file_returns_empty(self, monkeypatch):
        nonexistent = Path("/tmp/nonexistent_goals_test_xyz.md")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", nonexistent)

        goals = load_goals()
        assert goals == []

    def test_goal_without_description(self, tmp_path, monkeypatch):
        goals_file = _write_goals_file(tmp_path, "# Goals\n\n## Goal: Minimal\nStatus: active\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert goals[0].description == ""

    def test_goal_with_empty_title_raises(self, tmp_path, monkeypatch):
        goals_file = _write_goals_file(tmp_path, "# Goals\n\n## Goal:   \nStatus: active\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        with pytest.raises(ValueError, match="missing title"):
            load_goals()


# ===========================================================================
# 2. Weekly review service logic
# ===========================================================================

class TestWeeklyReviewService:
    def test_completed_related_task_produces_progress(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [x] Prepare training plan | priority: 3\n"
            "- [ ] Buy groceries\n"
        )
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n## Goal: Training\nStatus: active\nRelated tasks:\n- Prepare training plan\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        review = create_weekly_review()
        assert len(review.goals) == 1
        assert review.goals[0].progress == 100.0
        assert "Prepare training plan" in review.goals[0].completed_related_tasks

    def test_open_related_task_reported_as_remaining(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [ ] Prepare training plan | priority: 3\n"
        )
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n## Goal: Training\nStatus: active\nRelated tasks:\n- Prepare training plan\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        review = create_weekly_review()
        assert review.goals[0].progress == 0.0
        assert review.goals[0].completed_related_tasks == []
        assert review.goals[0].suggested_next_step == "Prepare training plan"

    def test_missing_related_task_handled_clearly(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Buy groceries\n")
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n## Goal: Training\nStatus: active\nRelated tasks:\n- Prepare training plan\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        review = create_weekly_review()
        assert review.goals[0].missing_related_tasks == ["Prepare training plan"]

    def test_inactive_goals_excluded(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [x] Prepare training plan\n")
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n"
            "## Goal: Active\nStatus: active\nRelated tasks:\n- Prepare training plan\n"
            "## Goal: Inactive\nStatus: inactive\nRelated tasks:\n- Prepare training plan\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        review = create_weekly_review()
        assert len(review.goals) == 1
        assert review.goals[0].goal.title == "Active"

    def test_completed_goals_excluded(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [x] Task\n")
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n"
            "## Goal: Active\nStatus: active\nRelated tasks:\n- Task\n"
            "## Goal: Completed\nStatus: completed\nRelated tasks:\n- Task\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        review = create_weekly_review()
        assert len(review.goals) == 1
        assert review.goals[0].goal.title == "Active"

    def test_all_linked_tasks_completed(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [x] Task A\n"
            "- [x] Task B\n"
        )
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n- Task A\n- Task B\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        review = create_weekly_review()
        assert review.goals[0].all_related_tasks_completed is True
        assert review.goals[0].suggested_next_step is None

    def test_suggested_next_step_first_open(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [ ] Task B\n"
            "- [ ] Task A\n"
        )
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n- Task A\n- Task B\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        review = create_weekly_review()
        assert review.goals[0].suggested_next_step == "Task A"

    def test_exact_title_matching(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [x] Prepare training plan\n"
            "- [ ] prepare training plan\n"
        )
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n- Prepare training plan\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        review = create_weekly_review()
        assert review.goals[0].progress == 100.0
        assert "Prepare training plan" in review.goals[0].completed_related_tasks
        assert "prepare training plan" not in review.goals[0].completed_related_tasks

    def test_no_goals_defined(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Buy groceries\n")
        goals_file = _write_goals_file(tmp_path, "# Goals\n")
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        review = create_weekly_review()
        assert review.goals == []

    def test_multiple_goals_all_active(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [x] Prepare training plan\n"
            "- [ ] Buy groceries\n"
        )
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n"
            "## Goal: Training\nStatus: active\nRelated tasks:\n- Prepare training plan\n"
            "## Goal: Groceries\nStatus: active\nRelated tasks:\n- Buy groceries\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        review = create_weekly_review()
        assert len(review.goals) == 2
        training = next(g for g in review.goals if g.goal.title == "Training")
        groceries = next(g for g in review.goals if g.goal.title == "Groceries")
        assert training.progress == 100.0
        assert groceries.progress == 0.0
        assert groceries.suggested_next_step == "Buy groceries"

    def test_completed_tasks_list(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [x] Completed A\n"
            "- [x] Completed B\n"
            "- [ ] Open task\n"
            "- [ ] Valid due | due: 2026-12-31\n"
        )
        goals_file = _write_goals_file(tmp_path, "# Goals\n")
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        review = create_weekly_review()
        assert "Completed A" in review.completed_tasks
        assert "Completed B" in review.completed_tasks
        assert "Open task" not in review.completed_tasks
        assert "Valid due" not in review.completed_tasks

    def test_open_tasks_list(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [ ] Buy groceries\n"
            "- [ ] Book dentist appointment | due: 2026-08-30 | priority: 2\n"
            "- [ ] Valid due | due: 2026-12-31\n"
        )
        goals_file = _write_goals_file(tmp_path, "# Goals\n")
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        review = create_weekly_review()
        assert "Buy groceries" in review.open_tasks
        assert "Book dentist appointment" in review.open_tasks
        assert "Valid due" in review.open_tasks


# ===========================================================================
# 3. CLI / rendering
# ===========================================================================

class TestWeeklyCLIRendering:
    def test_weekly_command_exists(self):
        from janus.weekly import show_weekly
        assert callable(show_weekly)

    def test_weekly_output_contains_header(self, capsys, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Buy groceries\n")
        goals_file = _write_goals_file(tmp_path, "# Goals\n")
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        from janus.weekly import show_weekly
        show_weekly()

        out = capsys.readouterr().out
        assert "JANUS — WEEKLY REVIEW" in out

    def test_weekly_output_includes_completed_section(self, capsys, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [x] Done task\n")
        goals_file = _write_goals_file(tmp_path, "# Goals\n")
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        from janus.weekly import show_weekly
        show_weekly()

        out = capsys.readouterr().out
        assert "COMPLETED TASKS" in out
        assert "Done task" in out

    def test_weekly_output_includes_goal_with_progress(self, capsys, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [x] Completed task\n")
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n## Goal: My Goal\nStatus: active\nRelated tasks:\n- Completed task\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        from janus.weekly import show_weekly
        show_weekly()

        out = capsys.readouterr().out
        assert "Goal: My Goal" in out
        assert "Progress: 100.0%" in out
        assert "1/1 tasks completed" in out
        assert "Completed task" in out

    def test_weekly_output_includes_goal_without_progress(self, capsys, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Open task\n")
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n## Goal: My Goal\nStatus: active\nRelated tasks:\n- Open task\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        from janus.weekly import show_weekly
        show_weekly()

        out = capsys.readouterr().out
        assert "Goal: My Goal" in out
        assert "Progress: 0.0%" in out
        assert "Suggested next step:" in out
        assert "Open task" in out

    def test_weekly_output_empty_completed_section(self, capsys, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Only open\n")
        goals_file = _write_goals_file(tmp_path, "# Goals\n")
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        from janus.weekly import show_weekly
        show_weekly()

        out = capsys.readouterr().out
        assert "COMPLETED TASKS" in out
        assert "No completed tasks." in out

    def test_weekly_output_contains_missing_related_task(self, capsys, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Buy groceries\n")
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n- Missing task\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        from janus.weekly import show_weekly
        show_weekly()

        out = capsys.readouterr().out
        assert "⚠ Related task not found:" in out
        assert "Missing task" in out

    def test_weekly_output_all_linked_completed(self, capsys, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [x] Task A\n- [x] Task B\n")
        goals_file = _write_goals_file(
            tmp_path,
            "# Goals\n\n## Goal: G\nStatus: active\nRelated tasks:\n- Task A\n- Task B\n"
        )
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        monkeypatch.setattr("janus.services.weekly_review.TASKS_PATH", tasks_file)

        from janus.weekly import show_weekly
        show_weekly()

        out = capsys.readouterr().out
        assert "✓ All currently linked tasks completed" in out
