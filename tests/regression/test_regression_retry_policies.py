"""Regression tests for retry policies (T1-T13).

Covers:
- T1: Exponential backoff delays are correct
- T2: Max retries is respected
- T3: ConcurrentWriteError triggers retry
- T4: Retry succeeds after transient failure
- T5: Retry exhausts and raises
- T6: read_modify_write_with_retry retries on conflict
- T7: read_modify_write_with_retry succeeds on first try
- T8: read_modify_write_with_retry exhausts retries
- T9: AgentCoordinator.retry_with_backoff returns correct delays
- T10: AgentCoordinator.handle_timeout creates failed result
- T11: AgentCoordinator.handle_failure creates failed result
- T12: AgentCoordinator.execute_with_fallback handles all failures
- T13: AgentCoordinator.aggregate handles mixed results
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from janus.integrations.atomic_io import (
    ConcurrentWriteError,
    read_modify_write_with_retry,
)
from janus.services.coordination import (
    AgentCoordinator,
    AgentResult,
)
from janus.models.agent_role import AgentRole


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


# ──────────────────────────────────────────────────────────────────────
# T1: Exponential backoff delays are correct
# ──────────────────────────────────────────────────────────────────────


class TestT1_ExponentialBackoff:
    """T1: Exponential backoff delays are calculated correctly."""

    def test_t1_backoff_delays_correct(self) -> None:
        """retry_with_backoff returns [base, base*2, base*4, ...]."""
        coordinator = AgentCoordinator()
        delays = coordinator.retry_with_backoff("t1", AgentRole.RESEARCHER, max_retries=4, base_delay=1.0)
        assert delays == [1.0, 2.0, 4.0, 8.0]


# ──────────────────────────────────────────────────────────────────────
# T2: Max retries is respected
# ──────────────────────────────────────────────────────────────────────


class TestT2_MaxRetries:
    """T2: Max retries is respected in retry logic."""

    def test_t2_max_retries_zero(self) -> None:
        """Zero retries returns empty list."""
        coordinator = AgentCoordinator()
        delays = coordinator.retry_with_backoff("t2", AgentRole.RESEARCHER, max_retries=0, base_delay=1.0)
        assert delays == []

    def test_t2_max_retries_one(self) -> None:
        """One retry returns single delay."""
        coordinator = AgentCoordinator()
        delays = coordinator.retry_with_backoff("t2", AgentRole.RESEARCHER, max_retries=1, base_delay=0.5)
        assert delays == [0.5]


# ──────────────────────────────────────────────────────────────────────
# T3: ConcurrentWriteError triggers retry
# ──────────────────────────────────────────────────────────────────────


class TestT3_ConcurrentWriteErrorTriggersRetry:
    """T3: ConcurrentWriteError triggers retry in read_modify_write_with_retry."""

    def test_t3_concurrent_write_triggers_retry(self, tmp_path: Path) -> None:
        """A ConcurrentWriteError should cause a retry."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial\n")

        call_count = 0

        def _flaky_mutate(content: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConcurrentWriteError("simulated conflict")
            return content + "modified\n"

        # Patch read_modify_write to fail once
        with mock.patch("janus.integrations.atomic_io.read_modify_write") as mock_rmw:
            mock_rmw.side_effect = [
                ConcurrentWriteError("conflict"),
                None,  # second call succeeds
            ]
            read_modify_write_with_retry(test_file, _flaky_mutate, max_retries=2, backoff_base=0.01)

        assert mock_rmw.call_count == 2


# ──────────────────────────────────────────────────────────────────────
# T4: Retry succeeds after transient failure
# ──────────────────────────────────────────────────────────────────────


class TestT4_RetrySucceedsAfterTransient:
    """T4: Retry succeeds after a transient failure."""

    def test_t4_retry_succeeds(self, tmp_path: Path) -> None:
        """After a transient ConcurrentWriteError, retry succeeds."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial\n")

        attempts = 0

        def _mutate(content: str) -> str:
            nonlocal attempts
            attempts += 1
            return content + "line\n"

        with mock.patch("janus.integrations.atomic_io.read_modify_write") as mock_rmw:
            mock_rmw.side_effect = [
                ConcurrentWriteError("conflict 1"),
                ConcurrentWriteError("conflict 2"),
                None,  # third attempt succeeds
            ]
            read_modify_write_with_retry(test_file, _mutate, max_retries=3, backoff_base=0.01)

        assert mock_rmw.call_count == 3


# ──────────────────────────────────────────────────────────────────────
# T5: Retry exhausts and raises
# ──────────────────────────────────────────────────────────────────────


class TestT5_RetryExhausts:
    """T5: Retry exhausts and raises after max_retries."""

    def test_t5_retry_exhausts(self, tmp_path: Path) -> None:
        """After max_retries, ConcurrentWriteError is raised."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial\n")

        def _mutate(content: str) -> str:
            return content + "line\n"

        with mock.patch("janus.integrations.atomic_io.read_modify_write") as mock_rmw:
            mock_rmw.side_effect = ConcurrentWriteError("persistent conflict")
            with pytest.raises(ConcurrentWriteError):
                read_modify_write_with_retry(test_file, _mutate, max_retries=2, backoff_base=0.01)

        # Initial attempt + 2 retries = 3 calls
        assert mock_rmw.call_count == 3


# ──────────────────────────────────────────────────────────────────────
# T6: read_modify_write_with_retry retries on conflict
# ──────────────────────────────────────────────────────────────────────


class TestT6_RmwRetriesOnConflict:
    """T6: read_modify_write_with_retry retries on conflict."""

    def test_t6_rmw_retries(self, tmp_path: Path) -> None:
        """read_modify_write_with_retry retries on ConcurrentWriteError."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial\n")

        call_count = 0

        def _mutate(content: str) -> str:
            nonlocal call_count
            call_count += 1
            return content + f"line {call_count}\n"

        with mock.patch("janus.integrations.atomic_io.read_modify_write") as mock_rmw:
            mock_rmw.side_effect = [
                ConcurrentWriteError("conflict"),
                None,
            ]
            read_modify_write_with_retry(test_file, _mutate, max_retries=3, backoff_base=0.01)

        assert mock_rmw.call_count == 2


# ──────────────────────────────────────────────────────────────────────
# T7: read_modify_write_with_retry succeeds on first try
# ──────────────────────────────────────────────────────────────────────


class TestT7_RmwSucceedsFirstTry:
    """T7: read_modify_write_with_retry succeeds on first try when no conflict."""

    def test_t7_rmw_succeeds_first_try(self, tmp_path: Path) -> None:
        """When there's no conflict, read_modify_write_with_retry succeeds immediately."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial\n")

        def _mutate(content: str) -> str:
            return content + "modified\n"

        with mock.patch("janus.integrations.atomic_io.read_modify_write") as mock_rmw:
            mock_rmw.return_value = None
            read_modify_write_with_retry(test_file, _mutate, max_retries=3, backoff_base=0.01)

        assert mock_rmw.call_count == 1


# ──────────────────────────────────────────────────────────────────────
# T8: read_modify_write_with_retry exhausts retries
# ──────────────────────────────────────────────────────────────────────


class TestT8_RmwExhaustsRetries:
    """T8: read_modify_write_with_retry exhausts retries and raises."""

    def test_t8_rmw_exhausts(self, tmp_path: Path) -> None:
        """When all retries fail, ConcurrentWriteError is raised."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial\n")

        def _mutate(content: str) -> str:
            return content + "line\n"

        with mock.patch("janus.integrations.atomic_io.read_modify_write") as mock_rmw:
            mock_rmw.side_effect = ConcurrentWriteError("persistent")
            with pytest.raises(ConcurrentWriteError):
                read_modify_write_with_retry(test_file, _mutate, max_retries=1, backoff_base=0.01)

        # Initial + 1 retry = 2 calls
        assert mock_rmw.call_count == 2


# ──────────────────────────────────────────────────────────────────────
# T9: AgentCoordinator.retry_with_backoff returns correct delays
# ──────────────────────────────────────────────────────────────────────


class TestT9_CoordinatorRetryDelays:
    """T9: AgentCoordinator.retry_with_backoff returns correct delays."""

    def test_t9_coordinator_delays(self) -> None:
        """AgentCoordinator.retry_with_backoff returns correct exponential delays."""
        coordinator = AgentCoordinator()
        delays = coordinator.retry_with_backoff("t9", AgentRole.RESEARCHER, max_retries=3, base_delay=2.0)
        assert delays == [2.0, 4.0, 8.0]


# ──────────────────────────────────────────────────────────────────────
# T10: AgentCoordinator.handle_timeout creates failed result
# ──────────────────────────────────────────────────────────────────────


class TestT10_HandleTimeout:
    """T10: AgentCoordinator.handle_timeout creates a failed result."""

    def test_t10_handle_timeout(self) -> None:
        """handle_timeout creates a failed AgentResult with timed_out=True."""
        coordinator = AgentCoordinator()
        result = coordinator.handle_timeout("t10", AgentRole.RESEARCHER, 300.0)

        assert result.success is False
        assert result.timed_out is True
        assert result.error == "Agent timed out after 300.0s"
        assert result.duration_seconds == 300.0


# ──────────────────────────────────────────────────────────────────────
# T11: AgentCoordinator.handle_failure creates failed result
# ──────────────────────────────────────────────────────────────────────


class TestT11_HandleFailure:
    """T11: AgentCoordinator.handle_failure creates a failed result."""

    def test_t11_handle_failure(self) -> None:
        """handle_failure creates a failed AgentResult."""
        coordinator = AgentCoordinator()
        result = coordinator.handle_failure("t11", AgentRole.RESEARCHER, "LLM error")

        assert result.success is False
        assert result.timed_out is False
        assert result.error == "LLM error"


# ──────────────────────────────────────────────────────────────────────
# T12: AgentCoordinator.execute_with_fallback handles all failures
# ──────────────────────────────────────────────────────────────────────


class TestT12_ExecuteWithFallback:
    """T12: AgentCoordinator.execute_with_fallback handles all agent failures."""

    def test_t12_all_agents_failed_fallback(self) -> None:
        """When all agents fail, fallback to single-agent flow."""
        coordinator = AgentCoordinator()
        failed_results = [
            AgentResult(task_id="t12", agent_role=AgentRole.RESEARCHER, success=False, error="fail 1"),
            AgentResult(task_id="t12", agent_role=AgentRole.EXECUTOR, success=False, error="fail 2"),
        ]

        from janus.models.goal import Goal
        from janus.models.task import Task
        from janus.services.agency_planning import AgencyContext

        task = Task(title="Test task")
        goal = Goal(title="Test goal")
        context = AgencyContext()

        with mock.patch("janus.services.coordination.dispatch_task") as mock_dispatch:
            mock_dispatch.return_value = mock.MagicMock(agent_role=None)
            result = coordinator.execute_with_fallback(task, goal, context, failed_results)

        assert result.degraded is True
        assert len(result.failures) > 0


# ──────────────────────────────────────────────────────────────────────
# T13: AgentCoordinator.aggregate handles mixed results
# ──────────────────────────────────────────────────────────────────────


class TestT13_AggregateMixedResults:
    """T13: AgentCoordinator.aggregate handles mixed success/failure."""

    def test_t13_aggregate_mixed(self) -> None:
        """Aggregate correctly handles mixed results."""
        coordinator = AgentCoordinator()
        results = [
            AgentResult(task_id="t13", agent_role=AgentRole.RESEARCHER, success=True, output="found data"),
            AgentResult(task_id="t13", agent_role=AgentRole.EXECUTOR, success=False, error="timeout", timed_out=True),
        ]

        result = coordinator.aggregate("t13", results)

        assert result.success is True  # At least one succeeded
        assert result.degraded is True  # But some failed
        assert len(result.failures) == 1
        assert "found data" in result.aggregated_output
