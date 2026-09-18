"""Tests for task completion service."""

from pathlib import Path
from datetime import date

import pytest

from janus.services.tasks import complete_task, TASKS_PATH


def _write_tasks_file(tmp_path, content):
    tasks_file = tmp_path / "tasks.md"
    tasks_file.write_text(content)
    return tasks_file


class TestCompleteTaskService:
    def test_complete_existing_open_task(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [ ] Buy running shoes | due: 2026-09-04 | priority: 1\n"
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        task = complete_task("Buy running shoes")

        assert task.title == "Buy running shoes"
        content = tasks_file.read_text()
        assert "- [x] Buy running shoes | due: 2026-09-04 | priority: 1" in content
        assert "- [ ] Buy running shoes" not in content

    def test_checkbox_changes_to_completed(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Some task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        complete_task("Some task")

        content = tasks_file.read_text()
        assert "- [x] Some task" in content

    def test_metadata_preserved(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [ ] Task name | due: 2026-08-30 | priority: 2\n"
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        complete_task("Task name")

        content = tasks_file.read_text()
        assert "due: 2026-08-30" in content
        assert "priority: 2" in content
        assert "- [x] Task name | due: 2026-08-30 | priority: 2" in content

    def test_unknown_metadata_preserved(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [ ] Task | due: 2026-08-30 | priority: 1 | tag: fitness\n"
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        complete_task("Task")

        content = tasks_file.read_text()
        assert "tag: fitness" in content
        assert "- [x] Task | due: 2026-08-30 | priority: 1 | tag: fitness" in content

    def test_blank_lines_and_comments_preserved(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(
            tmp_path,
            "# Tasks\n"
            "\n"
            "- [ ] Buy running shoes\n"
            "\n"
            "# Comment line\n"
            "\n"
            "- [ ] Another task\n"
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        complete_task("Buy running shoes")

        content = tasks_file.read_text()
        assert "# Tasks" in content
        assert "# Comment line" in content
        assert "- [x] Buy running shoes" in content
        assert "- [ ] Another task" in content

    def test_task_not_found_raises(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Some task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        with pytest.raises(ValueError, match="Task not found: Missing task"):
            complete_task("Missing task")

    def test_completed_task_cannot_be_completed_again(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(tmp_path, "- [x] Done task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        with pytest.raises(ValueError, match="Task not found: Done task"):
            complete_task("Done task")

    def test_duplicate_open_task_titles_raises(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [ ] Duplicate task\n"
            "- [ ] Duplicate task\n"
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        with pytest.raises(ValueError, match="Multiple open tasks found with title: Duplicate task"):
            complete_task("Duplicate task")

    def test_only_matching_task_modified(self, tmp_path, monkeypatch):
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [ ] Buy running shoes | priority: 1\n"
            "- [ ] Another task | priority: 2\n"
            "- [ ] Third task\n"
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        complete_task("Buy running shoes")

        content = tasks_file.read_text()
        assert "- [x] Buy running shoes | priority: 1" in content
        assert "- [ ] Another task | priority: 2" in content
        assert "- [ ] Third task" in content


class TestCompleteTaskCLIServiceIntegration:
    def test_complete_persists_to_file(self, tmp_path, monkeypatch, capsys):
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Test task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        from janus.tasks_cli import handle_task_complete
        handle_task_complete(["Test task"])

        content = tasks_file.read_text()
        assert "- [x] Test task" in content
        assert "Completed task:" in capsys.readouterr().out


class TestCompleteTaskCLIDuplicateSafeguard:
    def test_complete_duplicate_match_warns_and_refuses(self, tmp_path, monkeypatch, capsys):
        """CLI warns the user and exits 1 when multiple open tasks share a title.

        The service-layer guard raises ValueError; the CLI must turn this into
        an actionable 'Warning:' message on stderr and refuse to proceed.
        """
        tasks_file = _write_tasks_file(
            tmp_path,
            "- [ ] Duplicate task\n"
            "- [ ] Duplicate task\n"
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        from janus.tasks_cli import handle_task_complete
        with pytest.raises(SystemExit) as exc_info:
            handle_task_complete(["Duplicate task"])

        err = capsys.readouterr().err
        out = capsys.readouterr().out
        assert exc_info.value.code == 1
        assert "Warning:" in err
        # The warning states the exact number of matches found
        assert "Multiple open tasks found with title" in err
        # Actionable guidance is included
        assert "janus task list" in err
        assert "more specific task ID or line reference" in err
        # No completion message on stdout
        assert "Completed task:" not in out
        # File is untouched — neither duplicate was completed
        content = tasks_file.read_text()
        assert content.count("- [ ] Duplicate task") == 2

    def test_complete_no_match_cli_message(self, tmp_path, monkeypatch, capsys):
        """CLI reports 'Error:' (not 'Warning:'), exit 1, file untouched."""
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Some task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        from janus.tasks_cli import handle_task_complete
        with pytest.raises(SystemExit) as exc_info:
            handle_task_complete(["Missing task"])

        err = capsys.readouterr().err
        assert exc_info.value.code == 1
        assert "Error:" in err
        assert "Task not found: Missing task" in err
        # File untouched
        assert tasks_file.read_text() == "- [ ] Some task\n"
