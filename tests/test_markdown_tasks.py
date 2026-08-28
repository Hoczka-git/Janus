"""Tests for Markdown task loader."""

from pathlib import Path
from datetime import date

import pytest


def _write_tasks_file(tmp_path, content):
    tasks_file = tmp_path / "tasks.md"
    tasks_file.write_text(content)
    return tasks_file


class TestLoadTasks:
    def test_basic_task(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Buy groceries\n")
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)

        from janus.integrations.markdown_tasks import load_tasks
        tasks = load_tasks()
        assert len(tasks) == 1
        assert tasks[0].title == "Buy groceries"
        assert tasks[0].due_date is None
        assert tasks[0].priority == 1

    def test_due_date(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Dentist | due: 2026-08-30\n")
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)

        from janus.integrations.markdown_tasks import load_tasks
        tasks = load_tasks()
        assert len(tasks) == 1
        assert tasks[0].title == "Dentist"
        assert tasks[0].due_date == date(2026, 8, 30)

    def test_priority(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Training | priority: 3\n")
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)

        from janus.integrations.markdown_tasks import load_tasks
        tasks = load_tasks()
        assert len(tasks) == 1
        assert tasks[0].title == "Training"
        assert tasks[0].priority == 3

    def test_multiple_metadata(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Task | due: 2026-08-30 | priority: 2\n")
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)

        from janus.integrations.markdown_tasks import load_tasks
        tasks = load_tasks()
        assert len(tasks) == 1
        assert tasks[0].title == "Task"
        assert tasks[0].due_date == date(2026, 8, 30)
        assert tasks[0].priority == 2

    def test_completed_task_not_returned(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [x] Completed task\n")
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)

        from janus.integrations.markdown_tasks import load_tasks
        tasks = load_tasks()
        assert len(tasks) == 0

    def test_unknown_metadata_ignored(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Task | context: home\n")
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)

        from janus.integrations.markdown_tasks import load_tasks
        tasks = load_tasks()
        assert len(tasks) == 1
        assert tasks[0].title == "Task"
        assert tasks[0].priority == 1

    def test_invalid_due_date_raises(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Task | due: invalid-date\n")
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)

        from janus.integrations.markdown_tasks import load_tasks
        with pytest.raises(ValueError, match="Invalid due date"):
            load_tasks()

    def test_invalid_priority_raises(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Task | priority: high\n")
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)

        from janus.integrations.markdown_tasks import load_tasks
        with pytest.raises(ValueError, match="Invalid priority"):
            load_tasks()

    def test_missing_file_raises(self, monkeypatch):
        import janus.integrations.markdown_tasks as mt
        nonexistent = Path("/tmp/nonexistent_tasks_test.md")
        monkeypatch.setattr(mt, "TASKS_PATH", nonexistent)

        with pytest.raises(FileNotFoundError):
            mt.load_tasks()
