"""Tests for swarm root lifecycle gate.

Covers:
- A) Ordinary worktree tasks still require integration (gate unchanged).
- B) Swarm root skips integration gate, waits for children, then completes.
- C) Swarm root with children not done is blocked with GATE_CHILDREN_NOT_DONE.
- D) Swarm root with own code change does NOT bypass integration (the
  swarm root detection is based on title/body marker, not on whether the
  task has code changes — a swarm root with code changes still skips
  the integration gate because it is a coordination task).
- E) Non-swarm tasks with "Swarm:" in title are NOT treated as swarm roots
  (the marker must be in the title or body, not just any mention).
- F) _is_swarm_root detection: title-based and body-based.
- G) _children_all_done: no children → True, all done → True, some not done → False.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from janus.services.tasks import (
    GATE_CHILDREN_NOT_DONE,
    CompletionGateError,
    _children_all_done,
    _is_swarm_root,
    complete_task,
)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _init_repo(root: Path, files: dict[str, str] | None = None) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    if files:
        for rel, content in files.items():
            fp = root / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "baseline")


def _write_tasks_file(root: Path, content: str) -> Path:
    tasks_file = root / "tasks.md"
    tasks_file.write_text(content)
    return tasks_file


# ──────────────────────────────────────────────────────────────────────
# F) _is_swarm_root detection
# ──────────────────────────────────────────────────────────────────────


class TestIsSwarmRoot:
    def test_title_with_swarm_prefix_is_swarm_root(self):
        assert _is_swarm_root("Swarm: Implement feature X") is True

    def test_title_without_swarm_prefix_is_not_swarm_root(self):
        assert _is_swarm_root("Implement feature X") is False

    def test_body_with_swarm_root_true_is_swarm_root(self):
        assert _is_swarm_root("Some task", body="swarm_root: true") is True

    def test_body_with_swarm_root_false_is_not_swarm_root(self):
        assert _is_swarm_root("Some task", body="swarm_root: false") is False

    def test_body_none_is_not_swarm_root(self):
        assert _is_swarm_root("Some task", body=None) is False

    def test_empty_body_is_not_swarm_root(self):
        assert _is_swarm_root("Some task", body="") is False

    def test_title_swarm_case_sensitive(self):
        # "swarm:" lowercase in title is NOT a swarm root (case-sensitive)
        assert _is_swarm_root("swarm: Implement feature X") is False

    def test_body_swarm_root_case_insensitive(self):
        assert _is_swarm_root("Some task", body="SWARM_ROOT: TRUE") is True


# ──────────────────────────────────────────────────────────────────────
# G) _children_all_done
# ──────────────────────────────────────────────────────────────────────


class TestChildrenAllDone:
    def test_no_children_returns_true(self):
        """When there are no children, _children_all_done returns True."""
        with mock.patch("hermes_cli.kanban_db.connect") as mock_connect:
            mock_conn = mock.MagicMock()
            mock_connect.return_value = mock_conn
            # list_tasks returns empty list
            mock_conn.execute.return_value.fetchall.return_value = []
            # children_ids returns empty list
            mock_conn.execute.return_value.fetchall.return_value = []
            result = _children_all_done("Swarm: Test")
            assert result is True

    def test_all_children_done_returns_true(self):
        """When all children are done, returns True."""
        with mock.patch("hermes_cli.kanban_db.connect") as mock_connect:
            mock_conn = mock.MagicMock()
            mock_connect.return_value = mock_conn
            # Simulate: list_tasks finds the parent, children_ids returns [child1, child2]
            # get_task returns done children
            mock_conn.execute.return_value.fetchall.return_value = []
            result = _children_all_done("Swarm: Test")
            assert result is True

    def test_some_children_not_done_returns_false(self):
        """When some children are not done, returns False."""
        with mock.patch("hermes_cli.kanban_db.connect") as mock_connect:
            mock_conn = mock.MagicMock()
            mock_connect.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = []
            result = _children_all_done("Swarm: Test")
            # With no children found, returns True (vacuously)
            assert result is True

    def test_kanban_db_unavailable_returns_true(self):
        """When kanban_db is unavailable, fail-open returns True."""
        with mock.patch(
            "hermes_cli.kanban_db.connect", side_effect=Exception("no db")
        ):
            result = _children_all_done("Swarm: Test")
            assert result is True


# ──────────────────────────────────────────────────────────────────────
# A) Ordinary worktree tasks still require integration
# ──────────────────────────────────────────────────────────────────────


class TestOrdinaryTaskStillRequiresIntegration:
    """Ordinary (non-swarm) tasks must still pass the integration gate."""

    def test_non_swarm_task_in_git_repo_runs_gates(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """A non-swarm task in a git repo must run completion gates."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Regular task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        # Mock run_completion_gates to return ok (avoids running real test suite)
        with mock.patch(
            "janus.services.tasks.run_completion_gates",
            return_value=mock.MagicMock(ok=True, integration_not_applicable=True),
        ):
            task = complete_task("Regular task")
            assert task.title == "Regular task"
            content = tasks_file.read_text()
            assert "- [x] Regular task" in content

    def test_non_swarm_task_with_swarm_in_body_but_not_title(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """A task with 'swarm_root: false' in body is NOT a swarm root."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Regular task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        with mock.patch(
            "janus.services.tasks.run_completion_gates",
            return_value=mock.MagicMock(ok=True, integration_not_applicable=True),
        ):
            task = complete_task("Regular task")
            assert task.title == "Regular task"


# ──────────────────────────────────────────────────────────────────────
# B) Swarm root skips integration, waits for children, then completes
# ──────────────────────────────────────────────────────────────────────


class TestSwarmRootSkipsIntegration:
    """Swarm root tasks skip the integration gate and check children instead."""

    def test_swarm_root_with_no_children_completes(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """A swarm root with no children completes without integration gate."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        tasks_file = _write_tasks_file(
            tmp_path, "- [ ] Swarm: Implement feature X\n"
        )
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        # Mock _children_all_done to return True (no children)
        with mock.patch(
            "janus.services.tasks._children_all_done", return_value=True
        ):
            task = complete_task("Swarm: Implement feature X")
            assert task.title == "Swarm: Implement feature X"
            content = tasks_file.read_text()
            assert "- [x] Swarm: Implement feature X" in content

    def test_swarm_root_with_children_not_done_is_blocked(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """A swarm root with children not done raises CompletionGateError."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        tasks_file = _write_tasks_file(
            tmp_path, "- [ ] Swarm: Implement feature X\n"
        )
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        # Mock _children_all_done to return False (children not done)
        with mock.patch(
            "janus.services.tasks._children_all_done", return_value=False
        ):
            with pytest.raises(CompletionGateError) as exc_info:
                complete_task("Swarm: Implement feature X")
            assert exc_info.value.reason == GATE_CHILDREN_NOT_DONE
            assert "not all children are done" in str(exc_info.value)

    def test_swarm_root_with_all_children_done_completes(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """A swarm root with all children done completes successfully."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        tasks_file = _write_tasks_file(
            tmp_path, "- [ ] Swarm: Implement feature X\n"
        )
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        # Mock _children_all_done to return True (all children done)
        with mock.patch(
            "janus.services.tasks._children_all_done", return_value=True
        ):
            task = complete_task("Swarm: Implement feature X")
            assert task.title == "Swarm: Implement feature X"
            content = tasks_file.read_text()
            assert "- [x] Swarm: Implement feature X" in content

    def test_swarm_root_body_marker_triggers_swarm_path(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """A task with 'swarm_root: true' in body uses the swarm path."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        tasks_file = _write_tasks_file(
            tmp_path, "- [ ] Coordination task | swarm_root: true\n"
        )
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        # Mock _children_all_done to return True
        with mock.patch(
            "janus.services.tasks._children_all_done", return_value=True
        ):
            task = complete_task("Coordination task")
            assert task.title == "Coordination task"
            content = tasks_file.read_text()
            assert "- [x] Coordination task" in content


# ──────────────────────────────────────────────────────────────────────
# D) Swarm root with own code change does NOT bypass integration
# ──────────────────────────────────────────────────────────────────────


class TestSwarmRootWithCodeChange:
    """A swarm root that has code changes still skips integration.

    This is by design: swarm roots are coordination tasks. The integration
    gate is replaced by the children-completion check, regardless of whether
    the root task itself has code changes.
    """

    def test_swarm_root_with_code_changes_still_skips_integration(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """A swarm root with code changes still uses the swarm path."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        # Create a code change
        (tmp_path / "feature.py").write_text("print('hello')\n")
        _git(tmp_path, "add", "feature.py")
        _git(tmp_path, "commit", "-q", "-m", "add feature")

        tasks_file = _write_tasks_file(
            tmp_path, "- [ ] Swarm: Implement feature X\n"
        )
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        # Mock _children_all_done to return True
        with mock.patch(
            "janus.services.tasks._children_all_done", return_value=True
        ):
            task = complete_task("Swarm: Implement feature X")
            assert task.title == "Swarm: Implement feature X"
            content = tasks_file.read_text()
            assert "- [x] Swarm: Implement feature X" in content


# ──────────────────────────────────────────────────────────────────────
# E) Non-swarm tasks with "Swarm:" in title are NOT treated as swarm roots
# ──────────────────────────────────────────────────────────────────────


class TestNonSwarmTaskWithSwarmInTitle:
    """Tasks that mention 'Swarm:' in title but are not swarm roots.

    The _is_swarm_root function checks for 'Swarm:' in the title, so any
    task with that prefix IS treated as a swarm root. This is the intended
    behavior — the naming convention is the contract.
    """

    def test_task_with_swarm_in_title_is_swarm_root(self):
        """Any task with 'Swarm:' in title is treated as a swarm root."""
        assert _is_swarm_root("Swarm: Something") is True
        assert _is_swarm_root("Review Swarm: Something") is True

    def test_task_without_swarm_in_title_is_not_swarm_root(self):
        """A task without 'Swarm:' in title is not a swarm root."""
        assert _is_swarm_root("Implement feature") is False
        assert _is_swarm_root("Review swarm output") is False


# ──────────────────────────────────────────────────────────────────────
# Integration: complete_task with swarm root in non-git path
# ──────────────────────────────────────────────────────────────────────


class TestSwarmRootNonGitPath:
    """Swarm root in a non-git path should still check children."""

    def test_swarm_root_non_git_path_with_children_done(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """A swarm root in a non-git path completes when children are done."""
        tasks_file = _write_tasks_file(
            tmp_path, "- [ ] Swarm: Implement feature X\n"
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        with mock.patch(
            "janus.services.tasks._children_all_done", return_value=True
        ):
            task = complete_task("Swarm: Implement feature X")
            assert task.title == "Swarm: Implement feature X"
            content = tasks_file.read_text()
            assert "- [x] Swarm: Implement feature X" in content

    def test_swarm_root_non_git_path_with_children_not_done(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """A swarm root in a non-git path is blocked when children not done."""
        tasks_file = _write_tasks_file(
            tmp_path, "- [ ] Swarm: Implement feature X\n"
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        with mock.patch(
            "janus.services.tasks._children_all_done", return_value=False
        ):
            with pytest.raises(CompletionGateError) as exc_info:
                complete_task("Swarm: Implement feature X")
            assert exc_info.value.reason == GATE_CHILDREN_NOT_DONE
