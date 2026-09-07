"""Tests for the 'janus task add' CLI handler."""

from datetime import date
from io import StringIO
from unittest.mock import patch

import pytest

from janus.tasks_cli import handle_task_add


class TestTaskAddCLI:
    def test_basic_add(self, capsys):
        with patch("janus.tasks_cli.add_task") as mock_add, \
             patch("janus.tasks_cli.list_tasks", return_value=[]):
            mock_add.return_value = type("Task", (),
                                          {"title": "Buy shoes",
                                           "due_date": None,
                                           "priority": 1})()
            handle_task_add(["Buy shoes"])

        out = capsys.readouterr().out
        assert "Added task:" in out
        assert "Buy shoes" in out
        assert mock_add.call_count == 1

    def test_with_due_date(self, capsys):
        with patch("janus.tasks_cli.add_task") as mock_add, \
             patch("janus.tasks_cli.list_tasks", return_value=[]):
            mock_add.return_value = type("Task", (),
                                          {"title": "Dentist",
                                           "due_date": date(2026, 9, 4),
                                           "priority": 1})()
            handle_task_add(["Dentist", "--due", "2026-09-04"])

        out = capsys.readouterr().out
        assert "due 2026-09-04" in out

    def test_with_priority(self, capsys):
        with patch("janus.tasks_cli.add_task") as mock_add, \
             patch("janus.tasks_cli.list_tasks", return_value=[]):
            mock_add.return_value = type("Task", (),
                                          {"title": "Training",
                                           "due_date": None,
                                           "priority": 2})()
            handle_task_add(["Training", "--priority", "2"])

        out = capsys.readouterr().out
        assert "priority 2" in out

    def test_multiword_title(self, capsys):
        with patch("janus.tasks_cli.add_task") as mock_add, \
             patch("janus.tasks_cli.list_tasks", return_value=[]):
            mock_add.return_value = type("Task", (),
                                          {"title": "Buy running shoes",
                                           "due_date": None,
                                           "priority": 1})()
            handle_task_add(["Buy", "running", "shoes"])

        out = capsys.readouterr().out
        assert "Buy running shoes" in out

    def test_missing_title_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_task_add([])
        err = capsys.readouterr().err
        assert "title is required" in err

    def test_invalid_due_date_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_task_add(["Task", "--due", "not-a-date"])
        err = capsys.readouterr().err
        assert "invalid due date" in err

    def test_invalid_priority_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_task_add(["Task", "--priority", "0"])
        err = capsys.readouterr().err
        assert "invalid priority" in err

    def test_empty_string_title_exits(self, capsys):
        with patch("janus.tasks_cli.add_task") as mock_add, \
             patch("janus.tasks_cli.list_tasks", return_value=[]):
            mock_add.side_effect = ValueError("Task title cannot be empty")
            with pytest.raises(SystemExit):
                handle_task_add(["   "])
        err = capsys.readouterr().err
        assert "title cannot be empty" in err

    def test_duplicate_title_aborts(self, capsys):
        """Duplicate title detected → error, no add_task call, exit 1."""
        with patch("janus.tasks_cli.add_task") as mock_add, \
             patch("janus.tasks_cli.list_tasks") as mock_list:
            mock_list.return_value = [
                type("Task", (), {"title": "Buy shoes"})(),
            ]
            with pytest.raises(SystemExit) as exc_info:
                handle_task_add(["Buy shoes"])

        err = capsys.readouterr().err
        assert "already exists" in err
        assert "Buy shoes" in err
        assert exc_info.value.code == 1
        assert mock_add.call_count == 0

    def test_no_duplicate_allows_creation(self, capsys):
        """No matching title → proceeds to add_task."""
        with patch("janus.tasks_cli.add_task") as mock_add, \
             patch("janus.tasks_cli.list_tasks") as mock_list:
            mock_list.return_value = [
                type("Task", (), {"title": "Some other task"})(),
            ]
            mock_add.return_value = type("Task", (),
                                          {"title": "Buy shoes",
                                           "due_date": None,
                                           "priority": 1})()
            handle_task_add(["Buy shoes"])

        out = capsys.readouterr().out
        assert "Added task:" in out
        assert "Buy shoes" in out
        assert mock_add.call_count == 1

    def test_empty_task_list_allows_creation(self, capsys):
        """Empty task store → proceeds to add_task."""
        with patch("janus.tasks_cli.add_task") as mock_add, \
             patch("janus.tasks_cli.list_tasks", return_value=[]):
            mock_add.return_value = type("Task", (),
                                          {"title": "Buy shoes",
                                           "due_date": None,
                                           "priority": 1})()
            handle_task_add(["Buy shoes"])

        out = capsys.readouterr().out
        assert "Added task:" in out
        assert mock_add.call_count == 1


class TestTaskAddIntegration:
    def test_add_persists_to_file(self, tmp_path, monkeypatch, capsys):
        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text("- [ ] Existing task\n")

        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
        handle_task_add(["New task", "--due", "2026-09-04", "--priority", "2"])

        content = tasks_file.read_text()
        assert "- [ ] Existing task" in content
        assert "- [ ] New task | due: 2026-09-04 | priority: 2" in content

    def test_duplicate_aborts_before_writing(self, tmp_path, monkeypatch, capsys):
        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text("- [ ] Buy shoes\n")

        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
        with pytest.raises(SystemExit) as exc_info:
            handle_task_add(["Buy shoes"])

        err = capsys.readouterr().err
        assert "already exists" in err
        assert exc_info.value.code == 1
        # File unchanged — no append happened
        content = tasks_file.read_text()
        assert content == "- [ ] Buy shoes\n"

    def test_completed_task_does_not_block_recreation(self, tmp_path, monkeypatch, capsys):
        """A completed task with the same title is not an open-task duplicate."""
        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text("- [x] Buy shoes\n")

        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
        handle_task_add(["Buy shoes"])

        content = tasks_file.read_text()
        assert content == "- [x] Buy shoes\n- [ ] Buy shoes\n"
