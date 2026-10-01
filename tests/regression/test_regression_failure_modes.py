"""Regression tests for failure modes (F1-F10).

Covers:
- F1: Gate failure blocks completion (working tree not clean)
- F2: Gate failure blocks completion (tests fail)
- F3: Gate failure blocks completion (sync conflict)
- F4: Gate failure blocks completion (contract verification failure)
- F5: Integration failure blocks completion
- F6: Hook error during completion
- F7: Non-git path skips gates (no failure)
- F8: Swarm root with children not done blocks
- F9: Multiple gate failures - first one wins
- F10: Gate error (exception) during completion
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from janus.services.tasks import (
    GATE_CHILDREN_NOT_DONE,
    GATE_CONTRACT_VERIFICATION_FAILED,
    GATE_INTEGRATION_FAILED,
    GATE_SYNC_CONFLICT,
    GATE_TESTS_FAILED,
    GATE_WORKING_TREE_NOT_CLEAN,
    CompletionGateError,
    UnifiedCompletionGateError,
    CompletionGateResult,
    UnifiedGateResult,
    IntegrationGateResult,
    _children_all_done,
    _is_swarm_root,
    complete_task,
    run_completion_gates,
    run_unified_completion_gates,
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


def _setup_tasks(tmp_path: Path, monkeypatch: Any, content: str = "- [ ] Placeholder\n") -> Path:
    """Write tasks.md and monkeypatch TASKS_PATH."""
    tasks_file = _write_tasks_file(tmp_path, content)
    import janus.services.tasks as tasks_mod
    monkeypatch.setattr(tasks_mod, "TASKS_PATH", tasks_file)
    try:
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")
    except Exception:
        pass
    return tasks_file


# ──────────────────────────────────────────────────────────────────────
# F1: Gate failure blocks completion (working tree not clean)
# ──────────────────────────────────────────────────────────────────────


class TestF1_WorkingTreeNotClean:
    """F1: A dirty working tree blocks completion with GATE_WORKING_TREE_NOT_CLEAN."""

    def test_f1_dirty_tree_blocks_completion(self, tmp_path: Path, monkeypatch: Any) -> None:
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        tasks_file = _setup_tasks(tmp_path, monkeypatch, "- [ ] Dirty task\n")
        (tmp_path / "stray.txt").write_text("hello\n")

        with pytest.raises(UnifiedCompletionGateError) as exc_info:
            complete_task("Dirty task")

        assert "working_tree_not_clean" in str(exc_info.value)
        content = tasks_file.read_text()
        assert "- [ ] Dirty task" in content
        assert "- [x] Dirty task" not in content


# ──────────────────────────────────────────────────────────────────────
# F2: Gate failure blocks completion (tests fail)
# ──────────────────────────────────────────────────────────────────────


class TestF2_TestsFail:
    """F2: Failing tests block completion with GATE_TESTS_FAILED."""

    def test_f2_failing_tests_block_completion(self, tmp_path: Path, monkeypatch: Any) -> None:
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Test task\n")

        failed_result = CompletionGateResult(
            ok=False,
            blocked_reason=GATE_TESTS_FAILED,
            blocked_message="Pre-completion gate failed: tests did not pass after rebase",
        )

        with mock.patch("janus.services.tasks.run_unified_completion_gates") as mock_gates:
            mock_gates.return_value = UnifiedGateResult(
                overall="blocked",
                blocked_reason=GATE_TESTS_FAILED,
                blocked_message="Pre-completion gate failed: tests did not pass after rebase",
                adr004=failed_result,
                integration_required=IntegrationGateResult(passed=True, skipped=True),
            )
            with pytest.raises(UnifiedCompletionGateError) as exc_info:
                complete_task("Test task")

        assert GATE_TESTS_FAILED in str(exc_info.value)


# ──────────────────────────────────────────────────────────────────────
# F3: Gate failure blocks completion (sync conflict)
# ──────────────────────────────────────────────────────────────────────


class TestF3_SyncConflict:
    """F3: A sync conflict blocks completion with GATE_SYNC_CONFLICT."""

    def test_f3_sync_conflict_blocks_completion(self, tmp_path: Path, monkeypatch: Any) -> None:
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Conflict task\n")

        conflict_result = CompletionGateResult(
            ok=False,
            blocked_reason=GATE_SYNC_CONFLICT,
            blocked_message="Phase 1 re-sync conflict; Route to merge-reconciler.",
        )

        with mock.patch("janus.services.tasks.run_unified_completion_gates") as mock_gates:
            mock_gates.return_value = UnifiedGateResult(
                overall="blocked",
                blocked_reason=GATE_SYNC_CONFLICT,
                blocked_message="Phase 1 re-sync conflict; Route to merge-reconciler.",
                adr004=conflict_result,
                integration_required=IntegrationGateResult(passed=True, skipped=True),
            )
            with pytest.raises(UnifiedCompletionGateError) as exc_info:
                complete_task("Conflict task")

        assert GATE_SYNC_CONFLICT in str(exc_info.value)


# ──────────────────────────────────────────────────────────────────────
# F4: Gate failure blocks completion (contract verification failure)
# ──────────────────────────────────────────────────────────────────────


class TestF4_ContractVerificationFailure:
    """F4: Contract verification failure blocks completion."""

    def test_f4_contract_failure_blocks(self, tmp_path: Path, monkeypatch: Any) -> None:
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Contract task\n")

        contract_result = CompletionGateResult(
            ok=False,
            blocked_reason=GATE_CONTRACT_VERIFICATION_FAILED,
            blocked_message="Contract verification failed: 2 check(s) failed.",
        )

        with mock.patch("janus.services.tasks.run_unified_completion_gates") as mock_gates:
            mock_gates.return_value = UnifiedGateResult(
                overall="blocked",
                blocked_reason=GATE_CONTRACT_VERIFICATION_FAILED,
                blocked_message="Contract verification failed: 2 check(s) failed.",
                adr004=contract_result,
                integration_required=IntegrationGateResult(passed=True, skipped=True),
            )
            with pytest.raises(UnifiedCompletionGateError) as exc_info:
                complete_task("Contract task")

        assert GATE_CONTRACT_VERIFICATION_FAILED in str(exc_info.value)


# ──────────────────────────────────────────────────────────────────────
# F5: Integration failure blocks completion
# ──────────────────────────────────────────────────────────────────────


class TestF5_IntegrationFailure:
    """F5: Integration failure blocks completion with GATE_INTEGRATION_FAILED."""

    def test_f5_integration_failure_blocks(self, tmp_path: Path, monkeypatch: Any) -> None:
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Integration task\n")

        integration_result = CompletionGateResult(
            ok=False,
            blocked_reason=GATE_INTEGRATION_FAILED,
            blocked_message="Integration failed (merge_conflict): could not merge",
        )

        with mock.patch("janus.services.tasks.run_unified_completion_gates") as mock_gates:
            mock_gates.return_value = UnifiedGateResult(
                overall="blocked",
                blocked_reason=GATE_INTEGRATION_FAILED,
                blocked_message="Integration failed (merge_conflict): could not merge",
                adr004=integration_result,
                integration_required=IntegrationGateResult(passed=True, skipped=True),
            )
            with pytest.raises(UnifiedCompletionGateError) as exc_info:
                complete_task("Integration task")

        assert GATE_INTEGRATION_FAILED in str(exc_info.value)


# ──────────────────────────────────────────────────────────────────────
# F6: Hook error during completion
# ──────────────────────────────────────────────────────────────────────


class TestF6_HookError:
    """F6: A hook error during completion is handled gracefully."""

    def test_f6_hook_error_propagates(self, tmp_path: Path, monkeypatch: Any) -> None:
        """A hook error (emit failure) propagates to the caller."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Hook task\n")

        # Mock run_unified_completion_gates to pass
        with mock.patch("janus.services.tasks.run_unified_completion_gates",
                        return_value=UnifiedGateResult(overall="pass")):
            # emit errors propagate to the caller (not swallowed)
            with mock.patch("janus.services.tasks.emit", side_effect=RuntimeError("hook exploded")):
                with pytest.raises(RuntimeError, match="hook exploded"):
                    complete_task("Hook task")


# ──────────────────────────────────────────────────────────────────────
# F7: Non-git path skips gates (no failure)
# ──────────────────────────────────────────────────────────────────────


class TestF7_NonGitPathSkipsGates:
    """F7: Non-git paths skip gates and complete normally."""

    def test_f7_non_git_path_completes(self, tmp_path: Path, monkeypatch: Any) -> None:
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Non-git task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        task = complete_task("Non-git task")
        assert task.title == "Non-git task"
        content = tasks_file.read_text()
        assert "- [x] Non-git task" in content


# ──────────────────────────────────────────────────────────────────────
# F8: Swarm root with children not done blocks
# ──────────────────────────────────────────────────────────────────────


class TestF8_SwarmRootChildrenNotDone:
    """F8: A swarm root with children not done blocks completion."""

    def test_f8_swarm_root_children_not_done_blocks(self, tmp_path: Path, monkeypatch: Any) -> None:
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        tasks_file = _setup_tasks(tmp_path, monkeypatch, "- [ ] Swarm: Test root\n")

        with mock.patch("janus.services.tasks._children_all_done", return_value=False):
            with pytest.raises(CompletionGateError) as exc_info:
                complete_task("Swarm: Test root")

        assert exc_info.value.reason == GATE_CHILDREN_NOT_DONE
        content = tasks_file.read_text()
        assert "- [ ] Swarm: Test root" in content
        assert "- [x] Swarm: Test root" not in content


# ──────────────────────────────────────────────────────────────────────
# F9: Multiple gate failures - first one wins
# ──────────────────────────────────────────────────────────────────────


class TestF9_MultipleGateFailures:
    """F9: When multiple gates fail, the first failure is reported."""

    def test_f9_first_failure_wins(self, tmp_path: Path, monkeypatch: Any) -> None:
        """If Phase 1 (sync) fails, Phase 3 (tests) is never reached."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Multi-fail task\n")

        call_order: list[str] = []

        def _fake_resync(git_root):
            call_order.append("phase1")
            return CompletionGateResult(
                ok=False,
                blocked_reason=GATE_SYNC_CONFLICT,
                blocked_message="Sync conflict",
            )

        def _fake_checks(config):
            call_order.append("phase3")
            from janus.verification import VerificationReport
            return VerificationReport(task_id="test")

        with mock.patch("janus.services.tasks._phase1_resync", _fake_resync), \
             mock.patch("janus.services.tasks.run_default_checks", _fake_checks):
            result = run_completion_gates(root=tmp_path, test_command="true")

        assert result.ok is False
        assert result.blocked_reason == GATE_SYNC_CONFLICT
        assert call_order == ["phase1"]  # Phase 3 never reached


# ──────────────────────────────────────────────────────────────────────
# F10: Gate error (exception) during completion
# ──────────────────────────────────────────────────────────────────────


class TestF10_GateException:
    """F10: An exception in the gate runner is handled gracefully."""

    def test_f10_gate_exception_propagates(self, tmp_path: Path, monkeypatch: Any) -> None:
        """An unhandled exception in run_completion_gates should propagate."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Exception task\n")

        with mock.patch("janus.services.tasks.run_unified_completion_gates",
                        side_effect=RuntimeError("gate crashed")):
            with pytest.raises(RuntimeError, match="gate crashed"):
                complete_task("Exception task")
