"""Regression test harness and fixtures for Janus lifecycle tests.

Provides:
- TestHarness: orchestrates setup/teardown for lifecycle regression tests.
- Lifecycle state fixtures: tasks in specific states.
- Gate mock fixtures: mock/stub strategies for gates.
- Failure injection fixtures: claim timeout, gate failure, hook error.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Callable
from unittest import mock

import pytest


# ──────────────────────────────────────────────────────────────────────
# TestHarness
# ──────────────────────────────────────────────────────────────────────


class TestHarness:
    """Orchestrates setup/teardown for lifecycle regression tests."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        self._tmp_path = tmp_path
        self._monkeypatch = monkeypatch
        self._cleanup_stack: list[Callable[[], None]] = []

    def register_cleanup(self, fn: Callable[[], None]) -> None:
        self._cleanup_stack.append(fn)

    def cleanup(self) -> None:
        for fn in reversed(self._cleanup_stack):
            try:
                fn()
            except Exception:
                pass

    def __enter__(self) -> "TestHarness":
        return self

    def __exit__(self, *args) -> None:
        self.cleanup()


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestHarness]:
    with TestHarness(tmp_path, monkeypatch) as h:
        yield h


# ──────────────────────────────────────────────────────────────────────
# Git helpers
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
# Lifecycle state fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create an isolated git repo with a single commit."""
    _init_repo(tmp_path, {"README.md": "# Test\n"})
    return tmp_path


@pytest.fixture
def task_todo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Create a single task in todo state."""
    tasks_file = _write_tasks_file(tmp_path, "- [ ] Test task\n")
    monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
    return {"title": "Test task", "status": "todo", "file": tasks_file}


@pytest.fixture
def task_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Create a single task in running state (claimed)."""
    tasks_file = _write_tasks_file(tmp_path, "- [ ] Test task | state: in_progress\n")
    monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
    return {"title": "Test task", "status": "running", "file": tasks_file}


@pytest.fixture
def task_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Create a single task in blocked state."""
    tasks_file = _write_tasks_file(tmp_path, "- [ ] Test task | state: blocked\n")
    monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
    return {"title": "Test task", "status": "blocked", "file": tasks_file}


@pytest.fixture
def task_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Create a single task in done state."""
    tasks_file = _write_tasks_file(tmp_path, "- [x] Test task\n")
    monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
    return {"title": "Test task", "status": "done", "file": tasks_file}


@pytest.fixture
def task_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Create a single task in review state."""
    tasks_file = _write_tasks_file(tmp_path, "- [ ] Test task | review: true\n")
    monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
    return {"title": "Test task", "status": "review", "file": tasks_file}


@pytest.fixture
def task_changes_requested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Create a single task in changes_requested state."""
    tasks_file = _write_tasks_file(tmp_path, "- [ ] Test task | changes_requested: true\n")
    monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
    return {"title": "Test task", "status": "changes_requested", "file": tasks_file}


# ──────────────────────────────────────────────────────────────────────
# Gate mock fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_integration_gate_pass(monkeypatch: pytest.MonkeyPatch) -> mock.MagicMock:
    """Install a mock for the integration gate that passes."""
    from janus.services.tasks import CompletionGateResult
    m = mock.MagicMock(return_value=CompletionGateResult(ok=True, integration_not_applicable=True))
    monkeypatch.setattr("janus.services.tasks.run_completion_gates", m)
    return m


@pytest.fixture
def mock_integration_gate_fail(monkeypatch: pytest.MonkeyPatch) -> mock.MagicMock:
    """Install a mock for the integration gate that fails."""
    from janus.services.tasks import CompletionGateResult, GATE_INTEGRATION_FAILED
    m = mock.MagicMock(return_value=CompletionGateResult(
        ok=False,
        blocked_reason=GATE_INTEGRATION_FAILED,
        blocked_message="Integration failed",
    ))
    monkeypatch.setattr("janus.services.tasks.run_completion_gates", m)
    return m


@pytest.fixture
def mock_integration_gate_skip(monkeypatch: pytest.MonkeyPatch) -> mock.MagicMock:
    """Install a mock for the integration gate that skips (non-git)."""
    from janus.services.tasks import CompletionGateResult
    m = mock.MagicMock(return_value=CompletionGateResult(
        ok=True,
        integration_not_applicable=True,
    ))
    monkeypatch.setattr("janus.services.tasks.run_completion_gates", m)
    return m


@pytest.fixture
def mock_completion_gate_pass(monkeypatch: pytest.MonkeyPatch) -> mock.MagicMock:
    """Install a mock for the completion gate that passes."""
    from janus.services.tasks import CompletionGateResult
    m = mock.MagicMock(return_value=CompletionGateResult(ok=True))
    monkeypatch.setattr("janus.services.tasks.run_completion_gates", m)
    return m


@pytest.fixture
def mock_completion_gate_fail(monkeypatch: pytest.MonkeyPatch) -> mock.MagicMock:
    """Install a mock for the completion gate that fails."""
    from janus.services.tasks import CompletionGateResult, GATE_WORKING_TREE_NOT_CLEAN
    m = mock.MagicMock(return_value=CompletionGateResult(
        ok=False,
        blocked_reason=GATE_WORKING_TREE_NOT_CLEAN,
        blocked_message="Working tree not clean",
    ))
    monkeypatch.setattr("janus.services.tasks.run_completion_gates", m)
    return m


@pytest.fixture
def mock_all_hooks(monkeypatch: pytest.MonkeyPatch) -> dict[str, mock.MagicMock]:
    """Install mocks for all lifecycle hooks."""
    hooks: dict[str, mock.MagicMock] = {}
    hook_names = [
        "kanban_task_claimed",
        "kanban_task_completed",
        "kanban_task_blocked",
        "kanban_task_unblocked",
    ]
    for name in hook_names:
        m = mock.MagicMock()
        hooks[name] = m
    return hooks


# ──────────────────────────────────────────────────────────────────────
# Failure injection fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def inject_gate_failure(monkeypatch: pytest.MonkeyPatch) -> mock.MagicMock:
    """Inject a failure into the integration gate."""
    from janus.services.tasks import CompletionGateError
    m = mock.MagicMock(side_effect=CompletionGateError("test", "injected failure"))
    monkeypatch.setattr("janus.services.tasks.run_completion_gates", m)
    return m


@pytest.fixture
def inject_hook_error(monkeypatch: pytest.MonkeyPatch) -> mock.MagicMock:
    """Inject an error into a lifecycle hook."""
    m = mock.MagicMock(side_effect=RuntimeError("hook exploded"))
    return m
