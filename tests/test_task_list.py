"""Tests for 'janus task list' — service and CLI handler."""

from io import StringIO
from unittest.mock import patch

import pytest

from janus.services.tasks import list_tasks


def _write_tasks_file(tmp_path, content):
    tasks_file = tmp_path / "tasks.md"
    tasks_file.write_text(content)
    return tasks_file


# =============================================================================
# Service tests
# =============================================================================


class TestListTasksService:
    def test_returns_only_open_tasks(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [ ] Open task\n"
            "- [x] Completed task\n"
            "- [ ] Another open task\n",
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        tasks = list_tasks()

        assert len(tasks) == 2
        titles = [t.title for t in tasks]
        assert "Open task" in titles
        assert "Another open task" in titles
        assert "Completed task" not in titles

    def test_empty_file_returns_empty_list(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        tasks = list_tasks()

        assert tasks == []

    def test_preserves_metadata_on_listed_tasks(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [ ] Test task | due: 2026-09-04 | priority: 2 | state: in_progress | progress: 50\n",
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        tasks = list_tasks()

        assert len(tasks) == 1
        task = tasks[0]
        assert task.due_date is not None
        assert task.due_date.isoformat() == "2026-09-04"
        assert task.priority == 2
        assert task.state == "in_progress"
        assert task.progress == 50

    def test_preserves_extra_metadata(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [ ] Test task | tag: fitness\n",
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        tasks = list_tasks()

        assert len(tasks) == 1
        extra = tasks[0].extra_metadata
        assert extra is not None
        assert "tag: fitness" in extra


# =============================================================================
# CLI tests
# =============================================================================


class TestTaskListCLI:
    def test_list_shows_open_tasks(self, tmp_path, monkeypatch, capsys):
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [ ] Buy running shoes | due: 2026-09-04\n"
            "- [x] Done task\n"
            "- [ ] Prepare training plan\n",
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        from janus.tasks_cli import handle_task_list

        handle_task_list([])

        out = capsys.readouterr().out
        assert "Open tasks:" in out
        assert "Buy running shoes" in out
        assert "due: 2026-09-04" in out
        assert "Prepare training plan" in out
        assert "Done task" not in out

    def test_list_empty_shows_message(self, tmp_path, monkeypatch, capsys):
        tasks_file = _write_tasks_file(tmp_path, "")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        from janus.tasks_cli import handle_task_list

        handle_task_list([])

        out = capsys.readouterr().out
        assert "No open tasks." in out

    def test_list_rejects_arguments(self, tmp_path, monkeypatch, capsys):
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Test task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        from janus.tasks_cli import handle_task_list

        with pytest.raises(SystemExit):
            handle_task_list(["--unexpected"])

        err = capsys.readouterr().err
        assert "does not accept arguments" in err

    def test_list_shows_priority_state_progress(self, tmp_path, monkeypatch, capsys):
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [ ] Complex task | due: 2026-09-04 | priority: 3 | state: blocked | progress: 70\n",
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        from janus.tasks_cli import handle_task_list

        handle_task_list([])

        out = capsys.readouterr().out
        assert "Complex task" in out
        assert "due: 2026-09-04" in out
        assert "priority: 3" in out
        assert "state: blocked" in out
        assert "progress: 70%" in out

    def test_list_skips_default_priority_and_state(self, tmp_path, monkeypatch, capsys):
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [ ] Simple task\n",
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        from janus.tasks_cli import handle_task_list

        handle_task_list([])

        out = capsys.readouterr().out
        assert "Simple task" in out
        # default priority (1) and no state should not appear
        assert "priority:" not in out
        assert "state:" not in out
        assert "progress:" not in out
