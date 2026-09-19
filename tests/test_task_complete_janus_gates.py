"""Tests for ADR-004 Phase 5 gate enforcement on the Hermes execution-feedback
path (``complete_janus_task`` via ``dispatch_completion``).

Covers:
- A task cannot reach final completion (via ``complete_janus_task``) without
  passing all applicable ADR-004 gates — when running inside a git repo.
- Each gate failure is properly detected and reported as a
  ``CompletionGateError``.
- Already-completed (``- [x]``) tasks skip gates (idempotency preserved).
- Non-git tasks skip gates (backward compatibility preserved).
- A task passes through all gates successfully under normal conditions.

These tests build isolated temporary git repositories and monkeypatch
``TASKS_PATH`` so they don't depend on the real Janus working tree.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from janus.services.tasks import (
    GATE_SYNC_CONFLICT,
    GATE_TESTS_FAILED,
    GATE_WORKING_TREE_NOT_CLEAN,
    CompletionGateError,
)


# ──────────────────────────────────────────────────────────────────────
# Helpers (mirrors test_task_complete_gates.py)
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


def _setup_tasks(tmp_path: Path, monkeypatch: Any, content: str = "- [ ] Placeholder\n") -> Path:
    """Write tasks.md and monkeypatch TASKS_PATH.

    If *tmp_path* is a git repo, commits tasks.md so the working tree stays
    clean at gate time (Phase 3 checks for an unclean tree).
    """
    tasks_file = _write_tasks_file(tmp_path, content)
    import janus.services.tasks as tasks_mod
    monkeypatch.setattr(tasks_mod, "TASKS_PATH", tasks_file)
    try:
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")
    except Exception:
        pass
    return tasks_file


_JANUS_DOMAIN_TASK = (
    "---\n"
    "janus_domain:\n"
    "  object: task\n"
    "  title: {}\n"
    "---\n"
    "Task body.\n"
)


def _build_evidence(task_id: str = "t_abc", summary: str = "Task summary"):
    from janus.services.execution_feedback import EvidencePackage, JanusDomainMetadata
    md = JanusDomainMetadata(object="task", title=summary)
    ev = EvidencePackage(
        task_id=task_id,
        summary=summary,
        completed_at="2026-09-18T10:00:00Z",
        tests_passed=True,
        pr_url="https://example.com/pr/1",
    )
    return md, ev


def _run_gates_with_noop_tests(git_root):
    """Call the real run_completion_gates but with a no-op test command so
    tests_pass_after_rebase succeeds in temp repos without a tests/ dir."""
    from janus.services import tasks as tasks_mod
    original = tasks_mod.run_completion_gates

    def _wrapped(root=None, *, test_command="uv run pytest tests/",
                 integration_report_path=None):
        return original(
            root=root or tasks_mod.PROJECT_ROOT,
            test_command="true",
            integration_report_path=integration_report_path,
        )
    return _wrapped


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


class TestCompleteJanusTaskGateEnforcement:
    """complete_janus_task must enforce ADR-004 gates via dispatch_completion
    when the task is open and git-backed."""

    def test_open_task_in_git_repo_passes_gates(self, tmp_path: Path, monkeypatch: Any) -> None:
        """A normal open task in a git repo with clean tree + passing tests
        completes successfully through complete_janus_task."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Task summary\n")

        from janus.services.execution_feedback import dispatch_completion
        md, ev = _build_evidence(summary="Task summary")

        # Patch run_completion_gates to use a no-op test command so the
        # temp repo's non-existent tests/ dir doesn't cause a failure.
        with mock.patch("janus.services.tasks.run_completion_gates",
                        side_effect=_run_gates_with_noop_tests(tmp_path)):
            result = dispatch_completion(md, ev)
        assert result["task"] is not None
        content = (tmp_path / "tasks.md").read_text()
        assert "- [x] Task summary" in content
        assert "janus_evidence_task_id: t_abc" in content

    def test_open_task_fails_phase3_blocking_tree(self, tmp_path: Path, monkeypatch: Any) -> None:
        """When Phase 3 (working tree not clean) fails, dispatch_completion
        raises CompletionGateError and the task is NOT marked complete."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Dirty task\n")
        # Introduce an untracked file to make the working tree unclean, AFTER
        # the tasks.md commit (so _setup_tasks's commit didn't include it).
        (tmp_path / "stray.txt").write_text("hello\n")

        from janus.services.execution_feedback import dispatch_completion
        md, ev = _build_evidence(summary="Dirty task")

        with pytest.raises(CompletionGateError) as exc_info:
            dispatch_completion(md, ev)
        assert exc_info.value.reason == GATE_WORKING_TREE_NOT_CLEAN
        # Task must NOT be marked complete.
        content = (tmp_path / "tasks.md").read_text()
        assert "- [ ] Dirty task" in content
        assert "- [x] Dirty task" not in content

    def test_open_task_fails_phase3_tests(self, tmp_path: Path, monkeypatch: Any) -> None:
        """When Phase 3 (tests pass after rebase) fails, dispatch_completion
        raises CompletionGateError with GATE_TESTS_FAILED."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Failing task\n")

        from janus.services.tasks import CompletionGateResult
        from janus.verification import VerificationReport

        failed_result = CompletionGateResult(
            ok=False,
            blocked_reason=GATE_TESTS_FAILED,
            blocked_message="Pre-completion gate failed: tests did not pass after rebase",
            pre_completion_report=VerificationReport(task_id="test"),
        )

        from janus.services.execution_feedback import dispatch_completion
        md, ev = _build_evidence(summary="Failing task")

        with mock.patch("janus.services.tasks.run_completion_gates",
                        return_value=failed_result):
            with pytest.raises(CompletionGateError) as exc_info:
                dispatch_completion(md, ev)
        assert exc_info.value.reason == GATE_TESTS_FAILED
        content = (tmp_path / "tasks.md").read_text()
        assert "- [ ] Failing task" in content
        assert "- [x] Failing task" not in content

    def test_open_task_fails_phase1_resync_conflict(self, tmp_path: Path, monkeypatch: Any) -> None:
        """When Phase 1 re-sync conflict occurs, dispatch_completion raises
        CompletionGateError with GATE_SYNC_CONFLICT."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Conflict task\n")

        from janus.services.tasks import CompletionGateResult
        conflict_result = CompletionGateResult(
            ok=False,
            blocked_reason=GATE_SYNC_CONFLICT,
            blocked_message="Phase 1 re-sync conflict; Route to merge-reconciler.",
        )

        from janus.services.execution_feedback import dispatch_completion
        md, ev = _build_evidence(summary="Conflict task")

        with mock.patch("janus.services.tasks.run_completion_gates",
                        return_value=conflict_result):
            with pytest.raises(CompletionGateError) as exc_info:
                dispatch_completion(md, ev)
        assert exc_info.value.reason == GATE_SYNC_CONFLICT

    def test_already_completed_task_skips_gates(self, tmp_path: Path, monkeypatch: Any) -> None:
        """An already-completed (``- [x]``) task skips gates (idempotency)
        even in a git repo with a dirty tree."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _setup_tasks(tmp_path, monkeypatch, "- [x] Already done\n")
        # Dirty working tree — but since the task is already complete, gates
        # should be skipped.
        (tmp_path / "stray.txt").write_text("hello\n")

        from janus.services.execution_feedback import dispatch_completion
        md, ev = _build_evidence(summary="Already done")

        result = dispatch_completion(md, ev)
        assert result["task"] is not None
        content = (tmp_path / "tasks.md").read_text()
        assert "- [x] Already done" in content
        # Evidence was still updated (idempotent re-evidence).
        assert "janus_evidence_task_id: t_abc" in content

    def test_non_git_task_skips_gates(self, tmp_path: Path, monkeypatch: Any) -> None:
        """A non-git task (no git root) skips gates and completes normally."""
        # No git repo initialized.
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Non-git task\n")

        from janus.services.execution_feedback import dispatch_completion
        md, ev = _build_evidence(summary="Non-git task")

        result = dispatch_completion(md, ev)
        assert result["task"] is not None
        content = (tmp_path / "tasks.md").read_text()
        assert "- [x] Non-git task" in content


class TestRunCompletionGatesOrdering:
    """Verify that Phase 1 re-sync runs before Phase 3 in run_completion_gates."""

    def test_phase1_runs_before_phase3(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        call_order: list[str] = []

        def _fake_resync(git_root):
            call_order.append("phase1")
            return None

        def _fake_checks(config):
            call_order.append("phase3")
            from janus.verification import VerificationReport
            r = VerificationReport(task_id="test")
            return r

        with mock.patch(
            "janus.services.tasks._phase1_resync", _fake_resync
        ), mock.patch(
            "janus.services.tasks.run_default_checks", _fake_checks
        ):
            from janus.services.tasks import run_completion_gates
            run_completion_gates(root=tmp_path, test_command="true")

        assert call_order == ["phase1", "phase3"]
