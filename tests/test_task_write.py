"""Tests for the task write service (add_task, formatting, validation)."""

from pathlib import Path
from datetime import date

import pytest

from janus.models.task import Task
from janus.services.tasks import add_task, _format_task_line, TASKS_PATH


class TestAddTaskService:
    def test_title_only(self, tmp_path, monkeypatch):
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH",
                            tmp_path / "tasks.md")
        task = add_task("Buy running shoes")

        assert task.title == "Buy running shoes"
        assert task.due_date is None
        assert task.priority == 1

        content = (tmp_path / "tasks.md").read_text()
        assert "- [ ] Buy running shoes" in content
        assert "due:" not in content
        assert "priority:" not in content

    def test_with_due_date(self, tmp_path, monkeypatch):
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH",
                            tmp_path / "tasks.md")
        task = add_task("Book dentist appointment", due_date=date(2026, 9, 4))

        assert task.due_date == date(2026, 9, 4)
        assert task.priority == 1

        content = (tmp_path / "tasks.md").read_text()
        assert "due: 2026-09-04" in content
        assert "priority:" not in content

    def test_with_priority(self, tmp_path, monkeypatch):
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH",
                            tmp_path / "tasks.md")
        task = add_task("Prepare training plan", priority=2)

        assert task.priority == 2
        assert task.due_date is None

        content = (tmp_path / "tasks.md").read_text()
        assert "priority: 2" in content
        assert "due:" not in content

    def test_default_priority_not_written(self, tmp_path, monkeypatch):
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH",
                            tmp_path / "tasks.md")
        add_task("Some task", priority=1)

        content = (tmp_path / "tasks.md").read_text()
        assert "priority" not in content

    def test_full_metadata(self, tmp_path, monkeypatch):
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH",
                            tmp_path / "tasks.md")
        task = add_task("Full task", due_date=date(2026, 9, 4), priority=2)

        content = (tmp_path / "tasks.md").read_text()
        assert "- [ ] Full task | due: 2026-09-04 | priority: 2" in content

    def test_existing_tasks_preserved(self, tmp_path, monkeypatch):
        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text("- [ ] Existing task\n")

        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
        add_task("New task")

        content = tasks_file.read_text()
        assert "- [ ] Existing task" in content
        assert "- [ ] New task" in content

    def test_invalid_empty_title(self):
        with pytest.raises(ValueError, match="title cannot be empty"):
            add_task("")

    def test_invalid_whitespace_title(self):
        with pytest.raises(ValueError, match="title cannot be empty"):
            add_task("   ")

    def test_invalid_priority_zero(self):
        with pytest.raises(ValueError, match="Priority must be >= 1"):
            add_task("Bad task", priority=0)

    def test_invalid_priority_negative(self):
        with pytest.raises(ValueError, match="Priority must be >= 1"):
            add_task("Bad task", priority=-1)

    def test_valid_due_date_accepted(self, tmp_path, monkeypatch):
        tasks_path = tmp_path / "tasks.md"

        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_path)

        task = add_task("Valid due", due_date=date(2026, 12, 31))

        assert task.due_date == date(2026, 12, 31)

    def test_empty_tasks_file_before_append(self, tmp_path, monkeypatch):
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH",
                            tmp_path / "tasks.md")
        add_task("First task")

        assert (tmp_path / "tasks.md").read_text().strip() \
               == "- [ ] First task"


class TestFormatTaskLine:
    def test_title_only(self):
        task = Task(title="Simple task", due_date=None, priority=1)
        assert _format_task_line(task) == "- [ ] Simple task"

    def test_with_due_date(self):
        task = Task(title="Due task", due_date=date(2026, 8, 30), priority=1)
        assert _format_task_line(task) \
               == "- [ ] Due task | due: 2026-08-30"

    def test_with_priority(self):
        task = Task(title="Priority task", due_date=None, priority=3)
        assert _format_task_line(task) \
               == "- [ ] Priority task | priority: 3"

    def test_full(self):
        task = Task(title="Full task", due_date=date(2026, 9, 4), priority=2)
        assert _format_task_line(task) \
               == "- [ ] Full task | due: 2026-09-04 | priority: 2"

    def test_no_priority_for_default(self):
        task = Task(title="Default priority", priority=1)
        line = _format_task_line(task)
        assert line == "- [ ] Default priority"
        assert "| priority:" not in line
