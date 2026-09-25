"""Tests for task completion service."""

from pathlib import Path
from datetime import date

import pytest

from janus.services.tasks import complete_task, _build_completed_line, TASKS_PATH


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


# ===========================================================================
# 13.4 / §14.1 — completed_at metadata and _build_completed_line
# ===========================================================================
class TestBuildCompletedLine:
    """Tests for _build_completed_line — design §13.4 / §14.1.

    Completes a task by writing ``completed_at: <YYYY-MM-DD>`` into the
    task line's metadata section so health diagnostics can compute
    days_since_last_activity and task-based progress_delta.
    """

    def test_appends_completed_at_to_simple_task(self):
        """A bare ``- [ ] Task`` line becomes ``- [x] Task | completed_at: <date>``."""
        result = _build_completed_line("- [ ] Buy milk", "2026-09-06")
        assert result == "- [x] Buy milk | completed_at: 2026-09-06"

    def test_preserves_existing_metadata(self):
        """Existing metadata fields are preserved, completed_at appended last."""
        result = _build_completed_line(
            "- [ ] Task name | due: 2026-08-30 | priority: 2",
            "2026-09-06",
        )
        assert result == "- [x] Task name | due: 2026-08-30 | priority: 2 | completed_at: 2026-09-06"

    def test_preserves_unknown_fields(self):
        """Unknown metadata fields (tags, etc.) are preserved."""
        result = _build_completed_line(
            "- [ ] Task | due: 2026-08-30 | priority: 1 | tag: fitness",
            "2026-09-06",
        )
        assert "tag: fitness" in result
        assert "completed_at: 2026-09-06" in result
        # completed_at is last
        assert result.endswith("completed_at: 2026-09-06")

    def test_replaces_existing_completed_at(self):
        """Idempotent: re-completing replaces the old completed_at."""
        result = _build_completed_line(
            "- [ ] Task | completed_at: 2026-09-01 | priority: 2",
            "2026-09-06",
        )
        assert result == "- [x] Task | priority: 2 | completed_at: 2026-09-06"
        # Old date must not appear
        assert "2026-09-01" not in result

    def test_accepts_iso_timestamp(self):
        """completed_at accepts full ISO datetime strings too."""
        result = _build_completed_line("- [ ] Task", "2026-09-06T14:30:00+02:00")
        assert result == "- [x] Task | completed_at: 2026-09-06T14:30:00+02:00"


class TestCompleteTaskWritesCompletionDate:
    """complete_task records completed_at metadata (§13.4)."""

    def test_complete_writes_completed_at_metadata(self, tmp_path, monkeypatch):
        """Completing a task records ``completed_at`` in the line."""
        tasks_file = _write_tasks_file(
            tmp_path, "- [ ] Buy running shoes | priority: 1\n"
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        from datetime import date
        complete_task("Buy running shoes")

        content = tasks_file.read_text()
        today_str = date.today().isoformat()
        assert f"completed_at: {today_str}" in content
        assert content.startswith("- [x] Buy running shoes")

    def test_complete_preserves_metadata_and_adds_completed_at(self, tmp_path, monkeypatch):
        """Existing metadata is preserved alongside the new completed_at."""
        tasks_file = _write_tasks_file(
            tmp_path, "- [ ] Task A | due: 2026-08-30 | priority: 2\n"
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        complete_task("Task A")

        content = tasks_file.read_text()
        assert "due: 2026-08-30" in content
        assert "priority: 2" in content
        assert "completed_at:" in content

    def test_complete_without_prior_metadata_gets_completed_at(self, tmp_path, monkeypatch):
        """A bare task line gets completed_at appended after a separator."""
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Simple task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        complete_task("Simple task")

        content = tasks_file.read_text()
        assert "- [x] Simple task | completed_at:" in content
