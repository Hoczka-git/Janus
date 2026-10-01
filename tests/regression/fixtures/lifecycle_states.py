"""Fixtures for lifecycle state regression tests."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.regression.harness import TestHarness


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _init_repo(root: Path, files: dict[str, str] | None = None) -> None:
    """Init a git repo in *root*, create files, and commit them."""
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


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestHarness:
    """Provide a TestHarness instance."""
    return TestHarness(tmp_path, monkeypatch)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create an isolated git repo with a single commit."""
    _init_repo(tmp_path, {"README.md": "# Test\n"})
    return tmp_path


@pytest.fixture
def task_todo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    """Create a single task in todo state."""
    h = TestHarness(tmp_path, monkeypatch)
    task = h.create_task("Test task", status="todo")
    yield task
    h.cleanup()


@pytest.fixture
def task_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    """Create a single task in running state."""
    h = TestHarness(tmp_path, monkeypatch)
    task = h.create_task("Test task", status="in_progress")
    yield task
    h.cleanup()


@pytest.fixture
def task_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    """Create a single task in blocked state."""
    h = TestHarness(tmp_path, monkeypatch)
    task = h.create_task("Test task", status="blocked")
    yield task
    h.cleanup()


@pytest.fixture
def task_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    """Create a single task in done state."""
    h = TestHarness(tmp_path, monkeypatch)
    task = h.create_task("Test task", status="done")
    yield task
    h.cleanup()


@pytest.fixture
def task_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    """Create a single task in review state."""
    h = TestHarness(tmp_path, monkeypatch)
    task = h.create_task("Test task", status="review")
    yield task
    h.cleanup()


@pytest.fixture
def task_changes_requested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    """Create a single task in changes_requested state."""
    h = TestHarness(tmp_path, monkeypatch)
    task = h.create_task("Test task", status="changes_requested")
    yield task
    h.cleanup()


@pytest.fixture
def parent_with_children(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    """Parent task with 3 children in various states."""
    h = TestHarness(tmp_path, monkeypatch)
    parent = h.create_task("Parent task", status="todo")
    children = [
        h.create_task("Child 1", status="todo", parents=["Parent task"]),
        h.create_task("Child 2", status="in_progress", parents=["Parent task"]),
        h.create_task("Child 3", status="done", parents=["Parent task"]),
    ]
    yield {"parent": parent, "children": children}
    h.cleanup()


@pytest.fixture
def swarm_root_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    """Swarm root with all children done."""
    h = TestHarness(tmp_path, monkeypatch)
    root = h.create_task("Swarm: Test root", status="todo")
    children = [
        h.create_task("Child 1", status="done", parents=["Swarm: Test root"]),
        h.create_task("Child 2", status="done", parents=["Swarm: Test root"]),
    ]
    yield {"root": root, "children": children}
    h.cleanup()


@pytest.fixture
def swarm_root_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    """Swarm root with some children not done."""
    h = TestHarness(tmp_path, monkeypatch)
    root = h.create_task("Swarm: Test root", status="todo")
    children = [
        h.create_task("Child 1", status="done", parents=["Swarm: Test root"]),
        h.create_task("Child 2", status="todo", parents=["Swarm: Test root"]),
    ]
    yield {"root": root, "children": children}
    h.cleanup()


@pytest.fixture
def swarm_root_integration_opt_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    """Swarm root with integration_required=True."""
    h = TestHarness(tmp_path, monkeypatch)
    root = h.create_task("Swarm: Test root", status="todo", metadata={"integration_required": "true"})
    children = [
        h.create_task("Child 1", status="done", parents=["Swarm: Test root"]),
    ]
    yield {"root": root, "children": children}
    h.cleanup()


@pytest.fixture
def worktree_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    """Task with workspace_kind=worktree and real branch."""
    h = TestHarness(tmp_path, monkeypatch)
    task = h.create_task("Worktree task", status="in_progress", metadata={"workspace_kind": "worktree"})
    yield task
    h.cleanup()
