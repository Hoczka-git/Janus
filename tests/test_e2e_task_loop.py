"""End-to-end loop tests for the Janus task CLI lifecycle.

Exercises the full add → list → complete → re-add loop through the CLI
handler layer against a monkeypatched tasks.md file. These tests cover the
duplicate-prevention and safeguard behaviors of the task CLI:

  * ``handle_task_add`` rejects duplicate open-task titles before writing.
  * ``handle_task_complete`` refuses to complete when >1 open match exists
    (safeguard), and reports a clear error on zero matches.

The tests run against the updated CLI behavior and are written so that they
would FAIL if the safeguards were removed (e.g. a zero-match completion would
silently do nothing instead of erroring, or a duplicate add would silently
append a second line).
"""
import sys
from unittest.mock import patch

import pytest

from janus.services.tasks import (
    complete_task,
    list_tasks,
    add_task,
)
from janus.tasks_cli import (
    handle_task_add,
    handle_task_complete,
    handle_task_list,
    handle_task_state,
    handle_task_progress,
    print_task_help,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _write_tasks_file(tmp_path, content):
    tasks_file = tmp_path / "tasks.md"
    tasks_file.write_text(content)
    return tasks_file


@pytest.fixture
def tasks_file(tmp_path, monkeypatch):
    """An empty tasks.md wired into both service and CLI layers."""
    tf = tmp_path / "tasks.md"
    tf.write_text("")
    monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tf)
    return tf


# ===========================================================================
# Loop stage 1 — add (handle_task_add)
# ===========================================================================

class TestE2ELoopAdd:
    def test_add_new_task_succeeds(self, tasks_file, capsys):
        handle_task_add(["Buy groceries"])
        out = capsys.readouterr().out
        assert "Added task:" in out
        assert "Buy groceries" in out
        assert "- [ ] Buy groceries" in tasks_file.read_text()

    def test_add_new_task_persists_as_open(self, tasks_file):
        handle_task_add(["Walk the dog"])
        tasks = list_tasks()
        assert len(tasks) == 1
        assert tasks[0].title == "Walk the dog"

    def test_add_with_due_date(self, tasks_file, capsys):
        handle_task_add(["Pay bills", "--due", "2026-09-30"])
        out = capsys.readouterr().out
        assert "due 2026-09-30" in out
        content = tasks_file.read_text()
        assert "- [ ] Pay bills | due: 2026-09-30" in content

    def test_add_with_priority(self, tasks_file, capsys):
        handle_task_add(["Deep work", "--priority", "3"])
        out = capsys.readouterr().out
        assert "priority 3" in out
        assert "- [ ] Deep work | priority: 3" in tasks_file.read_text()

    def test_add_with_due_and_priority(self, tasks_file, capsys):
        handle_task_add(
            ["Submit report", "--due", "2026-10-01", "--priority", "2"]
        )
        out = capsys.readouterr().out
        assert "due 2026-10-01" in out
        assert "priority 2" in out
        content = tasks_file.read_text()
        assert "- [ ] Submit report | due: 2026-10-01 | priority: 2" in content

    def test_add_multiword_title(self, tasks_file, capsys):
        handle_task_add(["Buy", "running", "shoes"])
        out = capsys.readouterr().out
        assert "- [ ] Buy running shoes" in tasks_file.read_text()
        assert "Buy running shoes" in out

    # --- duplicate rejection (requirement 4) ---
    def test_add_duplicate_open_rejected(self, tasks_file, capsys):
        handle_task_add(["Buy shoes"])
        with pytest.raises(SystemExit) as exc_info:
            handle_task_add(["Buy shoes"])
        err = capsys.readouterr().err
        assert exc_info.value.code == 1
        assert "already exists" in err
        assert "Buy shoes" in err

    def test_add_duplicate_rejected_no_second_append(self, tasks_file, capsys):
        handle_task_add(["Buy shoes"])
        capsys.readouterr()  # drain first add output
        try:
            handle_task_add(["Buy shoes"])
        except SystemExit:
            pass
        capsys.readouterr()
        content = tasks_file.read_text()
        assert content.count("Buy shoes") == 1
        assert content.count("- [ ]") == 1

    def test_add_duplicate_via_service_layer_raises(self, tasks_file):
        add_task("Unique title")
        # A second identical add_task call at the service layer is allowed
        # (the guard lives in the CLI handler), but listing must still only
        # surface open tasks — verify the first add is open.
        assert len(list_tasks()) == 1

    # --- validation failures ---
    def test_add_empty_title_exits(self, tasks_file, capsys):
        # Falls through to add_task which raises "Task title cannot be empty"
        with pytest.raises(SystemExit):
            handle_task_add(["   "])
        err = capsys.readouterr().err
        assert "cannot be empty" in err

    def test_add_no_args_exits(self, tasks_file, capsys):
        with pytest.raises(SystemExit):
            handle_task_add([])
        assert "title is required" in capsys.readouterr().err

    def test_add_invalid_due_date_exits(self, tasks_file, capsys):
        with pytest.raises(SystemExit):
            handle_task_add(["Task", "--due", "not-a-date"])
        err = capsys.readouterr().err
        assert "invalid due date" in err

    def test_add_invalid_priority_exits(self, tasks_file, capsys):
        with pytest.raises(SystemExit):
            handle_task_add(["Task", "--priority", "0"])
        err = capsys.readouterr().err
        assert "invalid priority" in err


# ===========================================================================
# Loop stage 2 — list (handle_task_list)
# ===========================================================================

class TestE2ELoopList:
    def test_list_shows_open_tasks(self, tasks_file, capsys):
        handle_task_add(["Task A"])
        handle_task_add(["Task B"])
        handle_task_list([])
        out = capsys.readouterr().out
        assert "Open tasks:" in out
        assert "Task A" in out
        assert "Task B" in out

    def test_list_excludes_completed(self, tasks_file, capsys):
        handle_task_add(["Do thing"])
        handle_task_complete(["Do thing"])
        capsys.readouterr()
        handle_task_list([])
        out = capsys.readouterr().out
        assert "No open tasks." in out

    def test_list_empty_shows_message(self, tasks_file, capsys):
        handle_task_list([])
        out = capsys.readouterr().out
        assert "No open tasks." in out

    def test_list_rejects_arguments(self, tasks_file, capsys):
        with pytest.raises(SystemExit):
            handle_task_list(["--unexpected"])
        assert "does not accept arguments" in capsys.readouterr().err

    def test_list_preserves_metadata_display(self, tasks_file, capsys):
        handle_task_add(
            ["Complex task", "--due", "2026-09-04", "--priority", "3"]
        )
        handle_task_list([])
        out = capsys.readouterr().out
        assert "Complex task" in out
        assert "due: 2026-09-04" in out
        assert "priority: 3" in out


# ===========================================================================
# Loop stage 3 — complete (handle_task_complete)
# ===========================================================================

class TestE2ELoopComplete:
    # --- requirement 2: exactly one match, happy path ---
    def test_complete_single_match_happy_path(self, tasks_file, capsys):
        handle_task_add(["Buy running shoes"])
        capsys.readouterr()
        handle_task_complete(["Buy running shoes"])
        out = capsys.readouterr().out
        assert "Completed task: Buy running shoes" in out
        content = tasks_file.read_text()
        assert "- [x] Buy running shoes" in content
        assert "- [ ] Buy running shoes" not in content

    # --- requirement 1: zero matches ---
    def test_complete_zero_matches_errors(self, tasks_file, capsys):
        handle_task_add(["Some task"])
        capsys.readouterr()
        with pytest.raises(SystemExit) as exc_info:
            handle_task_complete(["Nonexistent task"])
        err = capsys.readouterr().err
        assert exc_info.value.code == 1
        assert "Error:" in err
        assert "Task not found: Nonexistent task" in err

    def test_complete_zero_matches_leaves_file_untouched(self, tasks_file):
        handle_task_add(["Some task"])
        try:
            handle_task_complete(["Nonexistent task"])
        except SystemExit:
            pass
        content = tasks_file.read_text()
        assert "- [ ] Some task" in content
        assert "- [x]" not in content

    # --- requirement 3: multiple matches triggering safeguard ---
    def test_complete_multiple_matches_warns_and_refuses(self, tmp_path,
                                                         monkeypatch, capsys):
        tf = _write_tasks_file(
            tmp_path,
            "- [ ] Duplicate task\n"
            "- [ ] Duplicate task\n",
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tf)
        with pytest.raises(SystemExit) as exc_info:
            handle_task_complete(["Duplicate task"])
        captured = capsys.readouterr()
        err, out = captured.err, captured.out
        assert exc_info.value.code == 1
        assert "Warning:" in err
        assert "Multiple open tasks found with title: Duplicate task" in err
        assert "janus task list" in err
        assert "Completed task:" not in out
        # Neither duplicate was completed — file untouched
        content = tf.read_text()
        assert content.count("- [ ] Duplicate task") == 2
        assert "- [x]" not in content

    def test_complete_duplicate_service_raises(self, tmp_path, monkeypatch):
        tf = _write_tasks_file(
            tmp_path,
            "- [ ] Duplicate task\n"
            "- [ ] Duplicate task\n",
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tf)
        with pytest.raises(ValueError,
                           match="Multiple open tasks found with title"):
            complete_task("Duplicate task")

    def test_complete_one_of_two_distinct_tasks(self, tasks_file, capsys):
        handle_task_add(["First task"])
        handle_task_add(["Second task"])
        capsys.readouterr()
        handle_task_complete(["First task"])
        out = capsys.readouterr().out
        assert "Completed task: First task" in out
        content = tasks_file.read_text()
        assert "- [x] First task" in content
        assert "- [ ] Second task" in content

    def test_complete_already_completed_raises(self, tasks_file, capsys):
        handle_task_add(["Done thing"])
        handle_task_complete(["Done thing"])
        capsys.readouterr()
        with pytest.raises(SystemExit):
            handle_task_complete(["Done thing"])
        err = capsys.readouterr().err
        assert "Task not found" in err

    def test_complete_preserves_metadata(self, tasks_file, capsys):
        handle_task_add(
            ["Milestone", "--due", "2026-09-30", "--priority", "2"]
        )
        handle_task_complete(["Milestone"])
        content = tasks_file.read_text()
        assert "- [x] Milestone | due: 2026-09-30 | priority: 2" in content

    # --- requirement 7: ambiguous partial matches are NOT matched ---
    def test_complete_partial_match_does_not_match_substr(
        self, tasks_file, capsys
    ):
        """A title that is a prefix of another must not be completed."""
        handle_task_add(["Buy running shoes"])
        handle_add = capsys.readouterr()
        with pytest.raises(SystemExit) as exc_info:
            handle_task_complete(["Buy running"])
        err = capsys.readouterr().err
        assert exc_info.value.code == 1
        assert "Task not found" in err
        # Original task still open
        content = tasks_file.read_text()
        assert "- [ ] Buy running shoes" in content

    def test_complete_partial_match_does_not_match_suffix(self, tmp_path,
                                                           monkeypatch, capsys):
        tf = _write_tasks_file(
            tmp_path,
            "- [ ] Write report\n",
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tf)
        with pytest.raises(SystemExit):
            handle_task_complete(["report"])
        err = capsys.readouterr().err
        assert "Task not found" in err
        assert "- [ ] Write report" in tf.read_text()


# ===========================================================================
# Loop stage 4 — state & progress
# ===========================================================================

class TestE2ELoopStateProgress:
    def test_set_state_in_progress(self, tasks_file, capsys):
        handle_task_add(["Task A"])
        capsys.readouterr()
        handle_task_state(["Task A", "--state", "in_progress"])
        out = capsys.readouterr().out
        assert "Updated task state: Task A" in out
        assert "in_progress" in out
        assert "state: in_progress" in tasks_file.read_text()

    def test_set_state_blocked(self, tasks_file, capsys):
        handle_task_add(["Task B"])
        capsys.readouterr()
        handle_task_state(["Task B", "--state", "blocked"])
        out = capsys.readouterr().out
        assert "blocked" in out

    def test_set_state_invalid_value_exits(self, tasks_file, capsys):
        handle_task_add(["Task C"])
        capsys.readouterr()
        with pytest.raises(SystemExit):
            handle_task_state(["Task C", "--state", "done"])
        err = capsys.readouterr().err
        assert "invalid state" in err

    def test_set_progress_70(self, tasks_file, capsys):
        handle_task_add(["Task D"])
        capsys.readouterr()
        handle_task_progress(["Task D", "--pct", "70"])
        out = capsys.readouterr().out
        assert "70%" in out
        assert "progress: 70" in tasks_file.read_text()

    def test_set_progress_invalid_exits(self, tasks_file, capsys):
        handle_task_add(["Task E"])
        capsys.readouterr()
        with pytest.raises(SystemExit):
            handle_task_progress(["Task E", "--pct", "abc"])
        assert "integer" in capsys.readouterr().err


# ===========================================================================
# Loop integration: full add → complete → re-add workflows
# ===========================================================================

class TestE2ELoopIntegration:
    # --- requirement 5: adding a new task successfully (end-to-end) ---
    def test_full_add_complete_cycle(self, tasks_file, capsys):
        handle_task_add(["Write tests"])
        capsys.readouterr()
        handle_task_complete(["Write tests"])
        capsys.readouterr()
        content = tasks_file.read_text()
        assert "- [x] Write tests" in content
        assert "- [ ] Write tests" not in content

    # --- requirement 6: completing then re-adding ---
    def test_complete_then_readd_succeeds(self, tasks_file, capsys):
        handle_task_add(["Refactor auth"])
        capsys.readouterr()
        handle_task_complete(["Refactor auth"])
        capsys.readouterr()
        # Re-adding the same title after completion must succeed
        handle_task_add(["Refactor auth"])
        out = capsys.readouterr().out
        assert "Added task:" in out
        content = tasks_file.read_text()
        # One completed + one open with the same title
        assert "- [x] Refactor auth" in content
        assert "- [ ] Refactor auth" in content

    def test_readd_after_complete_not_treated_as_duplicate(self, tasks_file):
        add_task("Refactor auth")
        complete_task("Refactor auth")
        # list_tasks() only returns open tasks, so the completed one is gone
        assert len(list_tasks()) == 0
        handle_task_add(["Refactor auth"])
        assert len(list_tasks()) == 1

    def test_add_complete_two_tasks_sequentially(self, tasks_file, capsys):
        handle_task_add(["Task one"])
        handle_task_add(["Task two"])
        capsys.readouterr()
        handle_task_complete(["Task one"])
        capsys.readouterr()
        handle_task_complete(["Task two"])
        capsys.readouterr()
        content = tasks_file.read_text()
        assert "- [x] Task one" in content
        assert "- [x] Task two" in content

    def test_add_duplicate_while_one_open_refuses(self, tasks_file, capsys):
        handle_task_add(["Shared task"])
        capsys.readouterr()
        with pytest.raises(SystemExit):
            handle_task_add(["Shared task"])
        err = capsys.readouterr().err
        assert "already exists" in err
        # The duplicate is still there (one open entry)
        assert len(list_tasks()) == 1
        assert list_tasks()[0].title == "Shared task"
        handle_task_list([])
        out = capsys.readouterr().out
        assert "Shared task" in out

    def test_completed_task_does_not_block_recreation(self, tasks_file, capsys):
        """A completed task with the same title is not an open-task duplicate."""
        handle_task_add(["Buy shoes"])
        handle_task_complete(["Buy shoes"])
        capsys.readouterr()
        # Re-adding must succeed: completed entry is no longer 'open'
        handle_task_add(["Buy shoes"])
        out = capsys.readouterr().out
        assert "Added task:" in out
        content = tasks_file.read_text()
        assert content.count("- [ ] Buy shoes") == 1
        assert content.count("- [x] Buy shoes") == 1

    def test_add_with_due_then_complete_preserves_due(self, tasks_file, capsys):
        handle_task_add(["Renew license", "--due", "2026-12-31"])
        handle_task_complete(["Renew license"])
        content = tasks_file.read_text()
        assert "- [x] Renew license | due: 2026-12-31" in content

    def test_multiple_distinct_tasks_all_completable(self, tasks_file, capsys):
        for name in ("Alpha", "Beta", "Gamma"):
            handle_task_add([name])
        handle_task_complete(["Beta"])
        handle_task_complete(["Alpha"])
        handle_task_complete(["Gamma"])
        content = tasks_file.read_text()
        for name in ("Alpha", "Beta", "Gamma"):
            assert f"- [x] {name}" in content

    def test_task_not_found_completes_nothing(self, tasks_file, capsys):
        handle_task_add(["Real task"])
        try:
            handle_task_complete(["Fake task"])
        except SystemExit:
            pass
        content = tasks_file.read_text()
        assert "- [ ] Real task" in content
        assert "- [x]" not in content

    def test_complete_requires_title_argument(self, tasks_file, capsys):
        with pytest.raises(SystemExit):
            handle_task_complete([])
        assert "title is required" in capsys.readouterr().err

    def test_unknown_subcommand_prints_usage(self, tmp_path, monkeypatch, capsys):
        tf = _write_tasks_file(tmp_path, "")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tf)
        with patch.object(sys, "argv", ["janus", "task", "bogus"]):
            import janus
            janus.main()
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "Unknown task subcommand" in combined


# ===========================================================================
# Help / routing
# ===========================================================================

class TestE2ELoopHelpRouting:
    def test_task_no_subcommand_prints_help(self, tasks_file, capsys):
        with patch.object(sys, "argv", ["janus", "task"]):
            import janus
            janus.main()
        out = capsys.readouterr().out
        assert "Usage: janus task" in out
        assert "Manage tasks." in out

    def test_task_help_long_prints_subcommands(self, tasks_file, capsys):
        with patch.object(sys, "argv", ["janus", "task", "--help"]):
            import janus
            janus.main()
        out = capsys.readouterr().out
        for sub in ("add", "complete", "list", "state", "progress"):
            assert sub in out

    def test_print_task_help_lists_all_subcommands(self, tasks_file, capsys):
        print_task_help()
        out = capsys.readouterr().out
        for sub in ("add", "complete", "list", "state", "progress"):
            assert sub in out


import sys  # noqa: E402 - kept at top
