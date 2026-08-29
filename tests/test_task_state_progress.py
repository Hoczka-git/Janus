"""Tests for task state and progress functionality."""

import pytest
from datetime import date
from unittest.mock import patch
from pathlib import Path

from janus.models.task import Task, ALLOWED_STATES
from janus.integrations.markdown_tasks import (
    _parse_task_line,
    _format_task_line,
    _parse_state,
    _parse_progress,
    _extract_unknown_metadata,
)


# ── Model tests ─────────────────────────────────────────────────────────────


class TestTaskModel:

    def test_task_with_state(self):
        task = Task(title="Test", state="in_progress")
        assert task.state == "in_progress"

    def test_task_with_progress(self):
        task = Task(title="Test", progress=50)
        assert task.progress == 50

    def test_task_with_extra_metadata(self):
        task = Task(title="Test", extra_metadata=["comment: review later"])
        assert task.extra_metadata == ["comment: review later"]

    def test_invalid_state_raises(self):
        with pytest.raises(ValueError, match="Invalid task state"):
            Task(title="Test", state="done")

    def test_invalid_progress_above_100_raises(self):
        with pytest.raises(ValueError, match="Progress must be"):
            Task(title="Test", progress=150)

    def test_progress_negative_raises(self):
        with pytest.raises(ValueError):
            Task(title="Test", progress=-1)

    def test_progress_non_integer_raises(self):
        with pytest.raises(ValueError):
            Task(title="Test", progress="50")  # type: ignore[arg-type]

    def test_state_none_by_default(self):
        task = Task(title="Test")
        assert task.state is None

    def test_progress_none_by_default(self):
        task = Task(title="Test")
        assert task.progress is None

    def test_allowed_states_constant(self):
        assert ALLOWED_STATES == frozenset({"todo", "in_progress", "blocked"})


# ── Parser tests ─────────────────────────────────────────────────────────────


class TestMarkdownParsing:

    def _write_and_load(self, tmp_path, content):
        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text(content)
        import janus.integrations.markdown_tasks as mt
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(mt, "TASKS_PATH", tasks_file)
        result = mt.load_tasks()
        monkeypatch.undo()
        return result

    def test_parse_task_with_state(self, tmp_path):
        tasks = self._write_and_load(
            tmp_path, "- [ ] Test task | state: in_progress\n"
        )
        assert len(tasks) == 1
        assert tasks[0].state == "in_progress"

    def test_parse_task_with_progress(self, tmp_path):
        tasks = self._write_and_load(
            tmp_path, "- [ ] Test task | progress: 70\n"
        )
        assert tasks[0].progress == 70

    def test_parse_task_with_state_and_progress(self, tmp_path):
        tasks = self._write_and_load(
            tmp_path, "- [ ] Test task | state: blocked | progress: 30\n"
        )
        assert tasks[0].state == "blocked"
        assert tasks[0].progress == 30

    def test_parse_task_with_done_state_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid task state"):
            self._write_and_load(
                tmp_path, "- [ ] Test task | state: done\n"
            )

    def test_parse_task_without_state(self, tmp_path):
        tasks = self._write_and_load(tmp_path, "- [ ] Test task\n")
        assert tasks[0].state is None

    def test_parse_task_without_progress(self, tmp_path):
        tasks = self._write_and_load(tmp_path, "- [ ] Test task\n")
        assert tasks[0].progress is None

    def test_parse_task_with_unknown_metadata_preserved(self, tmp_path):
        tasks = self._write_and_load(
            tmp_path, "- [ ] Test task | state: todo | comment: review later\n"
        )
        assert tasks[0].state == "todo"
        assert "comment: review later" in tasks[0].extra_metadata

    def test_parse_completed_task_returns_none(self, tmp_path):
        tasks = self._write_and_load(
            tmp_path, "- [x] Completed task\n- [ ] Open task\n"
        )
        assert len(tasks) == 1
        assert tasks[0].title == "Open task"

    def test_parse_mixed_state_values(self, tmp_path):
        tasks = self._write_and_load(
            tmp_path,
            "- [ ] Task A | state: todo\n"
            "- [ ] Task B | state: in_progress\n"
            "- [ ] Task C | state: blocked\n"
            "- [ ] Task D\n",
        )
        assert len(tasks) == 4
        assert tasks[0].state == "todo"
        assert tasks[1].state == "in_progress"
        assert tasks[2].state == "blocked"
        assert tasks[3].state is None

    def test_parse_progress_edge_values(self, tmp_path):
        tasks = self._write_and_load(
            tmp_path,
            "- [ ] Task A | progress: 0\n"
            "- [ ] Task B | progress: 100\n"
            "- [ ] Task C\n",
        )
        assert len(tasks) == 3
        assert tasks[0].progress == 0
        assert tasks[1].progress == 100
        assert tasks[2].progress is None


# ── Serializer tests ─────────────────────────────────────────────────────────


class TestMarkdownSerializer:

    def test_format_basic(self):
        task = Task(title="Test task")
        assert _format_task_line(task) == "- [ ] Test task"

    def test_format_with_state(self):
        task = Task(title="Test", state="in_progress")
        line = _format_task_line(task)
        assert "state: in_progress" in line

    def test_format_with_progress(self):
        task = Task(title="Test", progress=50)
        line = _format_task_line(task)
        assert "progress: 50" in line

    def test_format_with_state_and_progress(self):
        task = Task(title="Test", state="blocked", progress=30)
        line = _format_task_line(task)
        assert "state: blocked" in line
        assert "progress: 30" in line

    def test_format_preserves_extra_metadata(self):
        task = Task(title="Test", state="todo", extra_metadata=["comment: review"])
        line = _format_task_line(task)
        assert "comment: review" in line

    def test_format_does_not_output_none_state(self):
        task = Task(title="Test", state=None)
        line = _format_task_line(task)
        assert "state:" not in line

    def test_format_does_not_output_none_progress(self):
        task = Task(title="Test", progress=None)
        line = _format_task_line(task)
        assert "progress:" not in line

    def test_format_with_due_and_priority(self):
        task = Task(
            title="Test",
            due_date=date(2026, 9, 4),
            priority=2,
            state="in_progress",
        )
        line = _format_task_line(task)
        assert "due: 2026-09-04" in line
        assert "priority: 2" in line
        assert "state: in_progress" in line

    def test_format_state_todo_is_output(self):
        # state: todo is valid but redundant; still serialized
        task = Task(title="Test", state="todo")
        line = _format_task_line(task)
        assert "state: todo" in line

    def test_format_order_due_priority_state_progress(self):
        task = Task(
            title="Test",
            due_date=date(2026, 9, 4),
            priority=2,
            state="blocked",
            progress=45,
        )
        line = _format_task_line(task)
        parts = line.split(" | ")
        assert parts[0] == "- [ ] Test"
        assert parts[1] == "due: 2026-09-04"
        assert parts[2] == "priority: 2"
        assert parts[3] == "state: blocked"
        assert parts[4] == "progress: 45"


# ── Service tests ────────────────────────────────────────────────────────────


class TestSetTaskState:

    def _setup_file(self, tmp_path, content):
        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text(content)
        return tasks_file

    def test_set_state_updates_task(self, tmp_path, monkeypatch):
        from janus.services.tasks import set_task_state, TASKS_PATH
        tasks_file = self._setup_file(tmp_path, "- [ ] Test task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
        task = set_task_state("Test task", "in_progress")
        assert task.state == "in_progress"
        content = tasks_file.read_text()
        assert "state: in_progress" in content

    def test_set_state_invalid_state_rejected(self, tmp_path, monkeypatch):
        from janus.services.tasks import set_task_state, TASKS_PATH
        tasks_file = self._setup_file(tmp_path, "- [ ] Test task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
        with pytest.raises(ValueError, match="Invalid task state"):
            set_task_state("Test task", "done")

    def test_set_state_task_not_found(self, tmp_path, monkeypatch):
        from janus.services.tasks import set_task_state, TASKS_PATH
        tasks_file = self._setup_file(tmp_path, "- [ ] Other task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
        with pytest.raises(ValueError, match="Task not found"):
            set_task_state("Test task", "in_progress")

    def test_set_state_completed_task_rejected(self, tmp_path, monkeypatch):
        from janus.services.tasks import set_task_state, TASKS_PATH
        tasks_file = self._setup_file(tmp_path, "- [x] Completed task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
        with pytest.raises(ValueError, match="Task not found"):
            set_task_state("Completed task", "in_progress")

    def test_set_state_preserves_metadata(self, tmp_path, monkeypatch):
        from janus.services.tasks import set_task_state, TASKS_PATH
        tasks_file = self._setup_file(
            tmp_path, "- [ ] Test task | due: 2026-09-04 | priority: 2\n"
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
        task = set_task_state("Test task", "blocked")
        assert task.state == "blocked"
        assert task.due_date is not None
        assert task.priority == 2
        content = tasks_file.read_text()
        assert "due: 2026-09-04" in content
        assert "priority: 2" in content
        assert "state: blocked" in content

    def test_set_state_multiple_matches_rejected(self, tmp_path, monkeypatch):
        from janus.services.tasks import set_task_state, TASKS_PATH
        tasks_file = self._setup_file(tmp_path, "- [ ] Test task\n- [ ] Test task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
        with pytest.raises(ValueError, match="Multiple open tasks"):
            set_task_state("Test task", "blocked")

    def test_set_state_empty_title_rejected(self, tmp_path, monkeypatch):
        from janus.services.tasks import set_task_state, TASKS_PATH
        tasks_file = self._setup_file(tmp_path, "- [ ] Test task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
        with pytest.raises(ValueError, match="title cannot be empty"):
            set_task_state("   ", "in_progress")


class TestSetTaskProgress:

    def _setup_file(self, tmp_path, content):
        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text(content)
        return tasks_file

    def test_set_progress_updates_task(self, tmp_path, monkeypatch):
        from janus.services.tasks import set_task_progress, TASKS_PATH
        tasks_file = self._setup_file(tmp_path, "- [ ] Test task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
        task = set_task_progress("Test task", 70)
        assert task.progress == 70
        content = tasks_file.read_text()
        assert "progress: 70" in content

    def test_set_progress_invalid_above_100(self, tmp_path, monkeypatch):
        from janus.services.tasks import set_task_progress, TASKS_PATH
        tasks_file = self._setup_file(tmp_path, "- [ ] Test task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
        with pytest.raises(ValueError, match="Progress must be"):
            set_task_progress("Test task", 150)

    def test_set_progress_negative_rejected(self, tmp_path, monkeypatch):
        from janus.services.tasks import set_task_progress, TASKS_PATH
        tasks_file = self._setup_file(tmp_path, "- [ ] Test task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
        with pytest.raises(ValueError):
            set_task_progress("Test task", -1)

    def test_set_progress_task_not_found(self, tmp_path, monkeypatch):
        from janus.services.tasks import set_task_progress, TASKS_PATH
        tasks_file = self._setup_file(tmp_path, "- [ ] Other task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
        with pytest.raises(ValueError, match="Task not found"):
            set_task_progress("Test task", 50)

    def test_set_progress_completed_task_rejected(self, tmp_path, monkeypatch):
        from janus.services.tasks import set_task_progress, TASKS_PATH
        tasks_file = self._setup_file(tmp_path, "- [x] Completed task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
        with pytest.raises(ValueError, match="Task not found"):
            set_task_progress("Completed task", 50)

    def test_set_progress_preserves_metadata(self, tmp_path, monkeypatch):
        from janus.services.tasks import set_task_progress, TASKS_PATH
        tasks_file = self._setup_file(
            tmp_path, "- [ ] Test task | due: 2026-09-04 | state: in_progress\n"
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
        task = set_task_progress("Test task", 80)
        assert task.progress == 80
        assert task.due_date is not None
        assert task.state == "in_progress"
        content = tasks_file.read_text()
        assert "due: 2026-09-04" in content
        assert "state: in_progress" in content
        assert "progress: 80" in content

    def test_set_progress_100_does_not_complete(self, tmp_path, monkeypatch):
        from janus.services.tasks import set_task_progress, TASKS_PATH
        tasks_file = self._setup_file(tmp_path, "- [ ] Test task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
        task = set_task_progress("Test task", 100)
        assert task.progress == 100
        assert task.state is None
        content = tasks_file.read_text()
        assert "[x]" not in content

    def test_set_progress_zero_is_valid(self, tmp_path, monkeypatch):
        from janus.services.tasks import set_task_progress, TASKS_PATH
        tasks_file = self._setup_file(tmp_path, "- [ ] Test task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
        task = set_task_progress("Test task", 0)
        assert task.progress == 0


# ── CLI tests ────────────────────────────────────────────────────────────────


class TestTaskStateCLI:

    def test_handle_task_state_valid(self, capsys):
        from janus.tasks_cli import handle_task_state
        with patch("janus.tasks_cli.set_task_state") as mock_set:
            mock_set.return_value = type("Task", (), {
                "title": "Test task",
                "state": "in_progress",
            })()
            handle_task_state(["Test task", "--state", "in_progress"])
        out = capsys.readouterr().out
        assert "Updated task state: Test task" in out
        assert "in_progress" in out

    def test_handle_task_state_invalid_state_exits(self, capsys):
        from janus.tasks_cli import handle_task_state
        with pytest.raises(SystemExit):
            handle_task_state(["Test task", "--state", "done"])
        err = capsys.readouterr().err
        assert "invalid state" in err

    def test_handle_task_state_missing_state_exits(self, capsys):
        from janus.tasks_cli import handle_task_state
        with pytest.raises(SystemExit):
            handle_task_state(["Test task"])
        err = capsys.readouterr().err
        assert "--state is required" in err

    def test_handle_task_state_missing_title_exits(self, capsys):
        from janus.tasks_cli import handle_task_state
        with pytest.raises(SystemExit):
            handle_task_state(["--state", "in_progress"])
        err = capsys.readouterr().err
        assert "title is required" in err

    def test_handle_task_state_task_not_found_exits(self, capsys):
        from janus.tasks_cli import handle_task_state
        with patch("janus.tasks_cli.set_task_state") as mock_set:
            mock_set.side_effect = ValueError("Task not found: Test task")
            with pytest.raises(SystemExit):
                handle_task_state(["Test task", "--state", "in_progress"])
        err = capsys.readouterr().err
        assert "Task not found" in err

    def test_handle_task_state_completed_task_exits(self, capsys):
        from janus.tasks_cli import handle_task_state
        with patch("janus.tasks_cli.set_task_state") as mock_set:
            mock_set.side_effect = ValueError(
                "Task not found: Completed task"
            )
            with pytest.raises(SystemExit):
                handle_task_state(["Completed task", "--state", "in_progress"])
        err = capsys.readouterr().err
        assert "Task not found" in err


class TestTaskProgressCLI:

    def test_handle_task_progress_valid(self, capsys):
        from janus.tasks_cli import handle_task_progress
        with patch("janus.tasks_cli.set_task_progress") as mock_set:
            mock_set.return_value = type("Task", (), {
                "title": "Test task",
                "progress": 70,
            })()
            handle_task_progress(["Test task", "--pct", "70"])
        out = capsys.readouterr().out
        assert "Updated task progress: Test task" in out
        assert "70%" in out

    def test_handle_task_progress_invalid_pct_exits(self, capsys):
        from janus.tasks_cli import handle_task_progress
        with pytest.raises(SystemExit):
            handle_task_progress(["Test task", "--pct", "150"])
        err = capsys.readouterr().err
        assert "integer between 0 and 100" in err

    def test_handle_task_progress_negative_exits(self, capsys):
        from janus.tasks_cli import handle_task_progress
        with pytest.raises(SystemExit):
            handle_task_progress(["Test task", "--pct", "-1"])
        err = capsys.readouterr().err
        assert "integer between 0 and 100" in err

    def test_handle_task_progress_missing_pct_exits(self, capsys):
        from janus.tasks_cli import handle_task_progress
        with pytest.raises(SystemExit):
            handle_task_progress(["Test task"])
        err = capsys.readouterr().err
        assert "--pct is required" in err

    def test_handle_task_progress_missing_title_exits(self, capsys):
        from janus.tasks_cli import handle_task_progress
        with pytest.raises(SystemExit):
            handle_task_progress(["--pct", "50"])
        err = capsys.readouterr().err
        assert "title is required" in err

    def test_handle_task_progress_non_integer_exits(self, capsys):
        from janus.tasks_cli import handle_task_progress
        with pytest.raises(SystemExit):
            handle_task_progress(["Test task", "--pct", "abc"])
        err = capsys.readouterr().err
        assert "integer between 0 and 100" in err


# ── Attention tests ──────────────────────────────────────────────────────────


class TestAttentionStateScoring:

    def _make_task(self, title, **kwargs):
        from janus.models.task import Task
        return Task(title=title, **kwargs)

    def test_blocked_task_gets_high_score(self):
        from janus.services.attention import get_attention_items
        from janus.models.event import Event
        from janus.models.goal import Goal

        today = date(2026, 8, 29)
        tasks = [self._make_task("Blocked task", state="blocked")]
        items = get_attention_items([], tasks, [], today)
        assert len(items) == 1
        assert items[0].score == 30
        assert items[0].category == "blocked_task"
        assert "Blocked task requiring attention" in items[0].reason

    def test_in_progress_task_gets_moderate_score(self):
        from janus.services.attention import get_attention_items
        from janus.models.event import Event
        from janus.models.goal import Goal

        today = date(2026, 8, 29)
        tasks = [self._make_task("In progress task", state="in_progress")]
        items = get_attention_items([], tasks, [], today)
        assert len(items) == 1
        assert items[0].score == 30
        assert items[0].category == "in_progress_task"
        assert "In-progress task" in items[0].reason

    def test_blocked_scores_higher_than_normal(self):
        from janus.services.attention import get_attention_items
        from janus.models.event import Event
        from janus.models.goal import Goal

        today = date(2026, 8, 29)
        tasks = [
            self._make_task("Normal task", priority=1),
            self._make_task("Blocked task", state="blocked"),
        ]
        items = get_attention_items([], tasks, [], today)
        assert len(items) == 1
        assert items[0].title == "Blocked task"

    def test_in_progress_surfaces_without_other_criteria(self):
        from janus.services.attention import get_attention_items
        from janus.models.event import Event
        from janus.models.goal import Goal

        today = date(2026, 8, 29)
        tasks = [
            self._make_task("Low priority task", priority=1, state="in_progress"),
        ]
        items = get_attention_items([], tasks, [], today)
        assert len(items) == 1
        assert items[0].score == 30
        assert items[0].category == "in_progress_task"

    def test_blocked_combined_with_overdue(self):
        from janus.services.attention import get_attention_items
        from janus.models.event import Event
        from janus.models.goal import Goal

        today = date(2026, 8, 29)
        tasks = [
            self._make_task(
                "Overdue blocked",
                due_date=date(2026, 8, 28),
                state="blocked",
            ),
        ]
        items = get_attention_items([], tasks, [], today)
        assert len(items) == 1
        assert items[0].score == 130  # overdue 100 + blocked 30
        assert items[0].category == "blocked_task"

    def test_in_progress_combined_with_high_priority(self):
        from janus.services.attention import get_attention_items
        from janus.models.event import Event
        from janus.models.goal import Goal

        today = date(2026, 8, 29)
        tasks = [
            self._make_task(
                "High priority in progress",
                priority=3,
                state="in_progress",
            ),
        ]
        items = get_attention_items([], tasks, [], today)
        assert len(items) == 1
        assert items[0].score == 80  # priority 50 + in_progress 30
        assert items[0].category == "in_progress_task"

    def test_todo_state_does_not_add_score(self):
        from janus.services.attention import get_attention_items
        from janus.models.event import Event
        from janus.models.goal import Goal

        today = date(2026, 8, 29)
        tasks = [self._make_task("Todo task", state="todo")]
        items = get_attention_items([], tasks, [], today)
        assert len(items) == 0

    def test_no_state_task_no_extra_score(self):
        from janus.services.attention import get_attention_items
        from janus.models.event import Event
        from janus.models.goal import Goal

        today = date(2026, 8, 29)
        tasks = [self._make_task("No state task")]
        items = get_attention_items([], tasks, [], today)
        assert len(items) == 0

    def test_blocked_takes_category_priority(self):
        from janus.services.attention import get_attention_items
        from janus.models.event import Event
        from janus.models.goal import Goal

        today = date(2026, 8, 29)
        tasks = [
            self._make_task(
                "Blocked but also high priority",
                priority=3,
                state="blocked",
            ),
        ]
        items = get_attention_items([], tasks, [], today)
        assert len(items) == 1
        # blocked category should win over high_priority_task
        assert items[0].category == "blocked_task"
        assert items[0].score == 80  # priority 50 + blocked 30

    def test_deterministic_sort_blocked_first(self):
        from janus.services.attention import get_attention_items
        from janus.models.event import Event
        from janus.models.goal import Goal

        today = date(2026, 8, 29)
        tasks = [
            self._make_task("Normal high priority", priority=3),
            self._make_task("Blocked low priority", state="blocked", priority=1),
        ]
        items = get_attention_items([], tasks, [], today)
        assert len(items) == 2
        # blocked (30) should rank above high_priority (50)? No, high_priority is 50, blocked is 30
        # Actually: normal high priority = 50, blocked low priority = 30
        # So normal high priority comes first
        assert items[0].title == "Normal high priority"
        assert items[0].score == 50
        assert items[1].title == "Blocked low priority"
        assert items[1].score == 30
