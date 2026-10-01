"""Tests for the unified completion gate (ADR-004 + integration_required).

Covers:
- UnifiedGateResult and IntegrationGateResult dataclasses
- run_unified_completion_gates() emits correct audit events
- complete_task() idempotency (already-completed tasks return early)
- complete_task() raises UnifiedCompletionGateError on block
- Integration gate logic (explicit_false, provider_error, pr_not_merged, ci_not_green, pass)
- No-op CI provider skips with provider_error
- service.task.mutated carries gate_results field
- dispatch_completion() uses unified gate
- Plugin catches UnifiedCompletionGateError

These tests build isolated temporary git repositories and monkeypatch
TASKS_PATH so they don't depend on the real Janus working tree.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from janus.services.tasks import (
    CompletionGateError,
    CompletionGateResult,
    GATE_WORKING_TREE_NOT_CLEAN,
    IntegrationGateResult,
    IntegrationState,
    TASKS_PATH,
    UnifiedCompletionGateError,
    UnifiedGateResult,
    complete_task,
    no_op_integration_state_provider,
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
# UnifiedGateResult and IntegrationGateResult dataclasses
# ──────────────────────────────────────────────────────────────────────


class TestUnifiedGateResultDataclasses:
    def test_unified_gate_result_defaults(self):
        r = UnifiedGateResult()
        assert r.overall == "pass"
        assert r.blocked_reason is None
        assert r.blocked_message is None
        assert r.adr004 is None
        assert r.integration_required is None
        assert r.phase_results == []
        assert r.duration_ms == 0.0

    def test_integration_gate_result_defaults(self):
        r = IntegrationGateResult()
        assert r.passed is True
        assert r.skipped is False
        assert r.skip_reason is None
        assert r.failure_reason is None

    def test_integration_state_defaults(self):
        s = IntegrationState()
        assert s.pr_url is None
        assert s.pr_merged is False
        assert s.ci_status == "unknown"
        assert s.ci_checks_passed is False
        assert s.error is None

    def test_no_op_provider_returns_unknown(self):
        state = no_op_integration_state_provider("some_branch")
        assert state.pr_url is None
        assert state.pr_merged is False
        assert state.ci_status == "unknown"
        assert state.ci_checks_passed is False
        assert state.error == "no_ci_provider_configured"


# ──────────────────────────────────────────────────────────────────────
# run_unified_completion_gates — audit events
# ──────────────────────────────────────────────────────────────────────


class TestUnifiedGateAuditEvents:
    def test_gate_started_event_emitted(self, tmp_path: Path):
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        with mock.patch("janus.services.tasks.emit") as mock_emit:
            run_unified_completion_gates(
                "Test task",
                root=tmp_path,
                test_command="true",
                integration_required_override=False,
            )

        # Check that completion.gate.started was emitted
        event_names = [call.args[1] for call in mock_emit.call_args_list]
        assert "completion.gate.started" in event_names

    def test_gate_finished_event_emitted(self, tmp_path: Path):
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        with mock.patch("janus.services.tasks.emit") as mock_emit:
            run_unified_completion_gates(
                "Test task",
                root=tmp_path,
                test_command="true",
                integration_required_override=False,
            )

        event_names = [call.args[1] for call in mock_emit.call_args_list]
        assert "completion.gate.finished" in event_names

    def test_unified_record_emitted_on_success(self, tmp_path: Path):
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        with mock.patch("janus.services.tasks.emit") as mock_emit:
            run_unified_completion_gates(
                "Test task",
                root=tmp_path,
                test_command="true",
                integration_required_override=False,
            )

        event_names = [call.args[1] for call in mock_emit.call_args_list]
        assert "completion.unified_record" in event_names

    def test_phase_result_events_emitted(self, tmp_path: Path):
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        with mock.patch("janus.services.tasks.emit") as mock_emit:
            run_unified_completion_gates(
                "Test task",
                root=tmp_path,
                test_command="true",
                integration_required_override=False,
            )

        event_names = [call.args[1] for call in mock_emit.call_args_list]
        assert "completion.gate.phase_result" in event_names

    def test_integration_required_checked_event_emitted(self, tmp_path: Path):
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        with mock.patch("janus.services.tasks.emit") as mock_emit:
            run_unified_completion_gates(
                "Test task",
                root=tmp_path,
                test_command="true",
                integration_required_override=False,
            )

        event_names = [call.args[1] for call in mock_emit.call_args_list]
        assert "completion.integration_required.checked" in event_names


# ──────────────────────────────────────────────────────────────────────
# run_unified_completion_gates — integration gate logic
# ──────────────────────────────────────────────────────────────────────


class TestIntegrationGateLogic:
    def test_explicit_false_skips_integration_gate(self, tmp_path: Path):
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        result = run_unified_completion_gates(
            "Test task",
            root=tmp_path,
            test_command="true",
            integration_required_override=False,
        )

        assert result.overall == "pass"
        assert result.integration_required is not None
        assert result.integration_required.skipped is True
        assert result.integration_required.skip_reason == "explicit_false"

    def test_no_op_provider_skips_with_provider_error(self, tmp_path: Path):
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        result = run_unified_completion_gates(
            "Test task",
            root=tmp_path,
            test_command="true",
            integration_required_override=True,
            integration_state_provider=no_op_integration_state_provider,
        )

        assert result.overall == "pass"
        assert result.integration_required is not None
        assert result.integration_required.skipped is True
        assert result.integration_required.skip_reason == "provider_error"

    def test_pr_not_merged_blocks(self, tmp_path: Path):
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        def _provider(branch: str) -> IntegrationState:
            return IntegrationState(
                pr_url="https://example.com/pr/1",
                pr_merged=False,
                ci_status="green",
                ci_checks_passed=True,
            )

        result = run_unified_completion_gates(
            "Test task",
            root=tmp_path,
            test_command="true",
            integration_required_override=True,
            integration_state_provider=_provider,
        )

        assert result.overall == "blocked"
        assert result.integration_required is not None
        assert result.integration_required.passed is False
        assert result.integration_required.failure_reason == "pr_not_merged"

    def test_ci_not_green_blocks(self, tmp_path: Path):
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        def _provider(branch: str) -> IntegrationState:
            return IntegrationState(
                pr_url="https://example.com/pr/1",
                pr_merged=True,
                ci_status="red",
                ci_checks_passed=False,
            )

        result = run_unified_completion_gates(
            "Test task",
            root=tmp_path,
            test_command="true",
            integration_required_override=True,
            integration_state_provider=_provider,
        )

        assert result.overall == "blocked"
        assert result.integration_required is not None
        assert result.integration_required.passed is False
        assert result.integration_required.failure_reason == "ci_not_green"

    def test_passing_integration_gate(self, tmp_path: Path):
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        def _provider(branch: str) -> IntegrationState:
            return IntegrationState(
                pr_url="https://example.com/pr/1",
                pr_merged=True,
                ci_status="green",
                ci_checks_passed=True,
            )

        result = run_unified_completion_gates(
            "Test task",
            root=tmp_path,
            test_command="true",
            integration_required_override=True,
            integration_state_provider=_provider,
        )

        assert result.overall == "pass"
        assert result.integration_required is not None
        assert result.integration_required.passed is True
        assert result.integration_required.skipped is False


# ──────────────────────────────────────────────────────────────────────
# complete_task — idempotency
# ──────────────────────────────────────────────────────────────────────


class TestCompleteTaskIdempotency:
    def test_already_completed_task_returns_early(self, tmp_path: Path, monkeypatch: Any) -> None:
        """An already-completed task (``- [x]``) returns without running gates."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _setup_tasks(tmp_path, monkeypatch, "- [x] Already done\n")
        # Dirty working tree — but since the task is already complete, gates
        # should be skipped.
        (tmp_path / "stray.txt").write_text("hello\n")

        task = complete_task("Already done")
        assert task.title == "Already done"
        content = (tmp_path / "tasks.md").read_text()
        assert "- [x] Already done" in content

    def test_already_completed_does_not_raise(self, tmp_path: Path, monkeypatch: Any) -> None:
        """Calling complete_task twice on the same task does not raise."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Test task\n")

        # Mock the ADR-004 gate to pass (temp repo has no tests/ dir)
        with mock.patch("janus.services.tasks.run_completion_gates") as mock_gates:
            mock_gates.return_value = CompletionGateResult(ok=True, integration_not_applicable=True)
            # First call completes the task
            task1 = complete_task("Test task")
            assert task1.title == "Test task"

            # Second call is idempotent (no error, no gate call)
            task2 = complete_task("Test task")
            assert task2.title == "Test task"


# ──────────────────────────────────────────────────────────────────────
# complete_task — UnifiedCompletionGateError
# ──────────────────────────────────────────────────────────────────────


class TestCompleteTaskUnifiedGateError:
    def test_raises_unified_error_on_block(self, tmp_path: Path, monkeypatch: Any) -> None:
        """When the unified gate blocks, complete_task raises UnifiedCompletionGateError."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        (tmp_path / "stray.txt").write_text("hello\n")
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        with pytest.raises(UnifiedCompletionGateError) as exc_info:
            complete_task("Test task")

        assert exc_info.value.result is not None
        assert exc_info.value.result.overall == "blocked"
        assert exc_info.value.result.blocked_reason == GATE_WORKING_TREE_NOT_CLEAN

    def test_unified_error_is_value_error(self) -> None:
        result = UnifiedGateResult(overall="blocked", blocked_reason="test")
        err = UnifiedCompletionGateError(result)
        assert isinstance(err, ValueError)
        assert err.result is result


# ──────────────────────────────────────────────────────────────────────
# complete_task — gate_results in service.task.mutated
# ──────────────────────────────────────────────────────────────────────


class TestCompleteTaskGateResults:
    def test_service_task_mutated_carries_gate_results(self, tmp_path: Path, monkeypatch: Any) -> None:
        """The service.task.mutated event includes a gate_results field."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        tasks_file = _setup_tasks(tmp_path, monkeypatch, "- [ ] Test task\n")

        with mock.patch("janus.services.tasks.emit") as mock_emit, \
             mock.patch("janus.services.tasks.run_completion_gates") as mock_gates:
            mock_gates.return_value = CompletionGateResult(ok=True, integration_not_applicable=True)
            complete_task("Test task")

        # Find the service.task.mutated call
        mutated_calls = [
            call for call in mock_emit.call_args_list
            if call.args[1] == "service.task.mutated"
        ]
        assert len(mutated_calls) == 1
        call_kwargs = mutated_calls[0].kwargs
        assert "gate_results" in call_kwargs
        gate_results = call_kwargs["gate_results"]
        assert gate_results["overall"] == "pass"
        assert "adr004" in gate_results
        assert "integration_required" in gate_results


# ──────────────────────────────────────────────────────────────────────
# dispatch_completion — unified gate
# ──────────────────────────────────────────────────────────────────────


class TestDispatchCompletionUnifiedGate:
    def test_dispatch_uses_unified_gate(self, tmp_path: Path, monkeypatch: Any) -> None:
        """dispatch_completion calls run_unified_completion_gates for open tasks."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Test task\n")

        from janus.services.execution_feedback import (
            EvidencePackage,
            JanusDomainMetadata,
            dispatch_completion,
        )
        md = JanusDomainMetadata(object="task", title="Test task")
        ev = EvidencePackage(
            task_id="t_abc",
            summary="Test task",
            completed_at="2026-09-18T10:00:00Z",
            tests_passed=True,
        )

        with mock.patch("janus.services.tasks.run_unified_completion_gates") as mock_unified:
            from janus.services.tasks import UnifiedGateResult, CompletionGateResult
            mock_unified.return_value = UnifiedGateResult(
                overall="pass",
                adr004=CompletionGateResult(ok=True, integration_not_applicable=True),
                integration_required=IntegrationGateResult(passed=True, skipped=True, skip_reason="explicit_false"),
            )
            result = dispatch_completion(md, ev)

        assert mock_unified.called
        assert result["task"] is not None

    def test_dispatch_raises_unified_error_on_block(self, tmp_path: Path, monkeypatch: Any) -> None:
        """dispatch_completion raises UnifiedCompletionGateError when unified gate blocks."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        (tmp_path / "stray.txt").write_text("hello\n")
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Dirty task\n")

        from janus.services.execution_feedback import (
            EvidencePackage,
            JanusDomainMetadata,
            dispatch_completion,
        )
        md = JanusDomainMetadata(object="task", title="Dirty task")
        ev = EvidencePackage(
            task_id="t_abc",
            summary="Dirty task",
            completed_at="2026-09-18T10:00:00Z",
            tests_passed=True,
        )

        with pytest.raises(UnifiedCompletionGateError):
            dispatch_completion(md, ev)


# ──────────────────────────────────────────────────────────────────────
# Plugin — UnifiedCompletionGateError handling
# ──────────────────────────────────────────────────────────────────────


class TestPluginUnifiedGateError:
    def test_plugin_catches_unified_error(self, tmp_path: Path) -> None:
        """The plugin's on_task_completed catches UnifiedCompletionGateError."""
        from janus.services.tasks import UnifiedCompletionGateError, UnifiedGateResult
        from plugins.janus_sync import on_task_completed

        result = UnifiedGateResult(
            overall="blocked",
            blocked_reason="pr_not_merged",
            blocked_message="Integration required gate failed: pr_not_merged",
        )
        uce = UnifiedCompletionGateError(result)

        with mock.patch("plugins.janus_sync._run_sync", side_effect=uce):
            with mock.patch("plugins.janus_sync._handle_gate_block") as mock_block:
                ret = on_task_completed("t_test_123")

        assert ret is not None
        assert ret["status"] == "blocked"
        assert ret["reason"] == "pr_not_merged"
        assert mock_block.called


# ──────────────────────────────────────────────────────────────────────
# Determinism — same inputs produce same outcome
# ──────────────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_non_git_path_deterministic(self, tmp_path: Path) -> None:
        """Non-git tasks always pass the gate (deterministic)."""
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Non-git task\n")
        import janus.services.tasks as m
        original = m.TASKS_PATH
        m.TASKS_PATH = tasks_file
        try:
            result1 = run_unified_completion_gates(
                "Non-git task",
                root=tmp_path,
                integration_required_override=False,
            )
            result2 = run_unified_completion_gates(
                "Non-git task",
                root=tmp_path,
                integration_required_override=False,
            )
            assert result1.overall == result2.overall == "pass"
        finally:
            m.TASKS_PATH = original

    def test_integration_gate_deterministic_with_same_provider(self, tmp_path: Path) -> None:
        """Same provider + same inputs = same outcome."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        call_count = [0]

        def _provider(branch: str) -> IntegrationState:
            call_count[0] += 1
            return IntegrationState(
                pr_url="https://example.com/pr/1",
                pr_merged=True,
                ci_status="green",
                ci_checks_passed=True,
            )

        # Mock run_completion_gates to pass (temp repo has no tests/ dir)
        with mock.patch("janus.services.tasks.run_completion_gates") as mock_gates:
            mock_gates.return_value = CompletionGateResult(ok=True, integration_not_applicable=True)
            result1 = run_unified_completion_gates(
                "Test task",
                root=tmp_path,
                test_command="true",
                integration_required_override=True,
                integration_state_provider=_provider,
            )
            result2 = run_unified_completion_gates(
                "Test task",
                root=tmp_path,
                test_command="true",
                integration_required_override=True,
                integration_state_provider=_provider,
            )

        assert result1.overall == result2.overall == "pass"
        assert result1.integration_required is not None
        assert result2.integration_required is not None
        assert result1.integration_required.passed is True
        assert result2.integration_required.passed is True
