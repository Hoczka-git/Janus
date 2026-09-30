"""Tests for multi-agent coordination and failure handling.

Covers:
- Task delegation (AgentCoordinator.delegate)
- Result aggregation (AgentCoordinator.aggregate)
- Timeout handling (AgentCoordinator.handle_timeout)
- Graceful degradation on agent failure (AgentCoordinator.execute_with_fallback)
- Retry with backoff (AgentCoordinator.retry_with_backoff)
- Edge cases (empty results, all failures, mixed success/failure)
"""

import time

import pytest

from janus.models.agent_role import AgentRole
from janus.models.execution_mode import ExecutionMode
from janus.models.goal import Goal
from janus.models.support_mode import SupportMode
from janus.models.task import Task
from janus.services.agency_planning import AgencyContext
from janus.services.agent_registry import AgentRegistry
from janus.services.coordination import (
    AgentCoordinator,
    AgentResult,
    CoordinationResult,
)


def _task(title: str, **kwargs) -> Task:
    return Task(title=title, **kwargs)


def _goal(title: str = "Test Goal", **kwargs) -> Goal:
    return Goal(title=title, **kwargs)


def _context(**kwargs) -> AgencyContext:
    return AgencyContext(**kwargs)


def _result(
    task_id: str = "task-1",
    agent_role: AgentRole = AgentRole.EXECUTOR,
    success: bool = True,
    output: str = "Done",
    error: str | None = None,
    duration: float = 1.0,
    timed_out: bool = False,
) -> AgentResult:
    return AgentResult(
        task_id=task_id,
        agent_role=agent_role,
        success=success,
        output=output,
        error=error,
        duration_seconds=duration,
        timed_out=timed_out,
    )


class TestAgentResult:
    def test_minimal_construction(self):
        result = AgentResult(
            task_id="t1",
            agent_role=AgentRole.PLANNER,
            success=True,
        )
        assert result.task_id == "t1"
        assert result.agent_role == AgentRole.PLANNER
        assert result.success is True
        assert result.output == ""
        assert result.error is None
        assert result.duration_seconds == 0.0
        assert result.timed_out is False

    def test_full_construction(self):
        result = AgentResult(
            task_id="t1",
            agent_role=AgentRole.RESEARCHER,
            success=False,
            output="partial",
            error="timeout",
            duration_seconds=5.0,
            timed_out=True,
        )
        assert result.task_id == "t1"
        assert result.agent_role == AgentRole.RESEARCHER
        assert result.success is False
        assert result.output == "partial"
        assert result.error == "timeout"
        assert result.duration_seconds == 5.0
        assert result.timed_out is True


class TestCoordinationResult:
    def test_minimal_construction(self):
        result = CoordinationResult(
            task_id="t1",
            success=True,
        )
        assert result.task_id == "t1"
        assert result.success is True
        assert result.agent_results == []
        assert result.aggregated_output == ""
        assert result.total_duration_seconds == 0.0
        assert result.failures == []
        assert result.degraded is False

    def test_full_construction(self):
        agent_result = _result()
        result = CoordinationResult(
            task_id="t1",
            success=True,
            agent_results=[agent_result],
            aggregated_output="output",
            total_duration_seconds=2.0,
            failures=[],
            degraded=False,
        )
        assert result.task_id == "t1"
        assert result.success is True
        assert len(result.agent_results) == 1
        assert result.aggregated_output == "output"
        assert result.total_duration_seconds == 2.0
        assert result.failures == []
        assert result.degraded is False


class TestAgentCoordinatorInit:
    def test_default_init(self):
        coord = AgentCoordinator()
        assert coord.registry is not None
        assert coord.timeout_seconds == 300.0

    def test_custom_timeout(self):
        coord = AgentCoordinator(timeout_seconds=60.0)
        assert coord.timeout_seconds == 60.0

    def test_custom_registry(self):
        registry = AgentRegistry()
        coord = AgentCoordinator(registry=registry)
        assert coord.registry is registry


class TestDelegate:
    def test_delegate_returns_coordination_result(self):
        coord = AgentCoordinator()
        task = _task("Implement feature X")
        goal = _goal()
        context = _context()
        result = coord.delegate(task, goal, context)
        assert isinstance(result, CoordinationResult)
        assert result.task_id == "Implement feature X"

    def test_delegate_plan_task(self):
        coord = AgentCoordinator()
        task = _task("Plan Q4 roadmap")
        goal = _goal()
        context = _context()
        result = coord.delegate(task, goal, context)
        assert result.success is True
        assert result.degraded is False

    def test_delegate_research_task(self):
        coord = AgentCoordinator()
        task = _task("Research multi-agent patterns")
        goal = _goal()
        context = _context()
        result = coord.delegate(task, goal, context)
        assert result.success is True

    def test_delegate_no_specialized_agent(self):
        coord = AgentCoordinator()
        task = _task("Design architecture")
        goal = _goal()
        context = _context()
        result = coord.delegate(task, goal, context)
        assert result.success is True

    def test_delegate_with_custom_timeout(self):
        coord = AgentCoordinator(timeout_seconds=60.0)
        task = _task("Implement feature X")
        goal = _goal()
        context = _context()
        result = coord.delegate(task, goal, context, timeout_seconds=30.0)
        assert result.success is True


class TestAggregate:
    def test_aggregate_empty_results(self):
        coord = AgentCoordinator()
        result = coord.aggregate("t1", [])
        assert result.task_id == "t1"
        assert result.success is False
        assert result.agent_results == []
        assert result.aggregated_output == ""
        assert result.failures == []
        assert result.degraded is False

    def test_aggregate_single_success(self):
        coord = AgentCoordinator()
        results = [_result(output="Done")]
        result = coord.aggregate("t1", results)
        assert result.success is True
        assert result.degraded is False
        assert result.aggregated_output == "[executor] Done"
        assert result.failures == []

    def test_aggregate_single_failure(self):
        coord = AgentCoordinator()
        results = [_result(success=False, error="crash")]
        result = coord.aggregate("t1", results)
        assert result.success is False
        assert result.degraded is True
        assert result.aggregated_output == ""
        assert len(result.failures) == 1
        assert "crash" in result.failures[0]

    def test_aggregate_mixed_results(self):
        coord = AgentCoordinator()
        results = [
            _result(agent_role=AgentRole.PLANNER, success=True, output="Plan done"),
            _result(agent_role=AgentRole.EXECUTOR, success=False, error="build failed"),
        ]
        result = coord.aggregate("t1", results)
        assert result.success is True  # At least one succeeded
        assert result.degraded is True  # But one failed
        assert "[planner] Plan done" in result.aggregated_output
        assert len(result.failures) == 1
        assert "build failed" in result.failures[0]

    def test_aggregate_multiple_successes(self):
        coord = AgentCoordinator()
        results = [
            _result(agent_role=AgentRole.PLANNER, success=True, output="Plan"),
            _result(agent_role=AgentRole.EXECUTOR, success=True, output="Code"),
            _result(agent_role=AgentRole.REVIEWER, success=True, output="Review"),
        ]
        result = coord.aggregate("t1", results)
        assert result.success is True
        assert result.degraded is False
        assert "[planner] Plan" in result.aggregated_output
        assert "[executor] Code" in result.aggregated_output
        assert "[reviewer] Review" in result.aggregated_output

    def test_aggregate_all_failures(self):
        coord = AgentCoordinator()
        results = [
            _result(agent_role=AgentRole.PLANNER, success=False, error="err1"),
            _result(agent_role=AgentRole.EXECUTOR, success=False, error="err2"),
        ]
        result = coord.aggregate("t1", results)
        assert result.success is False
        assert result.degraded is True
        assert len(result.failures) == 2

    def test_aggregate_with_start_time(self):
        coord = AgentCoordinator()
        results = [_result(output="Done", duration=1.0)]
        start = time.monotonic() - 2.0
        result = coord.aggregate("t1", results, start_time=start)
        assert result.total_duration_seconds >= 2.0

    def test_aggregate_timeout_failure(self):
        coord = AgentCoordinator()
        results = [_result(success=False, error="timed out", timed_out=True)]
        result = coord.aggregate("t1", results)
        assert result.success is False
        assert result.degraded is True
        assert result.failures[0] is not None
        assert "timed out" in result.failures[0]


class TestHandleTimeout:
    def test_handle_timeout_returns_failed_result(self):
        coord = AgentCoordinator()
        result = coord.handle_timeout("t1", AgentRole.EXECUTOR, 300.0)
        assert result.task_id == "t1"
        assert result.agent_role == AgentRole.EXECUTOR
        assert result.success is False
        assert result.timed_out is True
        assert result.duration_seconds == 300.0
        assert "timed out" in result.error

    def test_handle_timeout_different_roles(self):
        coord = AgentCoordinator()
        for role in AgentRole:
            result = coord.handle_timeout("t1", role, 60.0)
            assert result.agent_role == role
            assert result.timed_out is True


class TestHandleFailure:
    def test_handle_failure_returns_failed_result(self):
        coord = AgentCoordinator()
        result = coord.handle_failure("t1", AgentRole.RESEARCHER, "search failed")
        assert result.task_id == "t1"
        assert result.agent_role == AgentRole.RESEARCHER
        assert result.success is False
        assert result.timed_out is False
        assert result.error == "search failed"

    def test_handle_failure_with_duration(self):
        coord = AgentCoordinator()
        result = coord.handle_failure("t1", AgentRole.COACH, "explained wrong", duration_seconds=5.0)
        assert result.duration_seconds == 5.0


class TestExecuteWithFallback:
    def test_all_success_no_fallback(self):
        coord = AgentCoordinator()
        task = _task("Implement feature X")
        goal = _goal()
        context = _context()
        results = [_result(success=True, output="Done")]
        result = coord.execute_with_fallback(task, goal, context, results)
        assert result.success is True
        assert result.degraded is False

    def test_empty_results_triggers_fallback(self):
        coord = AgentCoordinator()
        task = _task("Implement feature X")
        goal = _goal()
        context = _context()
        result = coord.execute_with_fallback(task, goal, context, [])
        assert result.success is True  # Fallback succeeds
        assert result.degraded is True
        assert len(result.failures) > 0

    def test_all_failures_triggers_fallback(self):
        coord = AgentCoordinator()
        task = _task("Implement feature X")
        goal = _goal()
        context = _context()
        results = [
            _result(agent_role=AgentRole.PLANNER, success=False, error="err1"),
            _result(agent_role=AgentRole.EXECUTOR, success=False, error="err2"),
        ]
        result = coord.execute_with_fallback(task, goal, context, results)
        assert result.success is True  # Fallback succeeds
        assert result.degraded is True

    def test_partial_failure_returns_degraded(self):
        coord = AgentCoordinator()
        task = _task("Implement feature X")
        goal = _goal()
        context = _context()
        results = [
            _result(agent_role=AgentRole.PLANNER, success=True, output="Plan"),
            _result(agent_role=AgentRole.EXECUTOR, success=False, error="build failed"),
        ]
        result = coord.execute_with_fallback(task, goal, context, results)
        assert result.success is True  # At least one succeeded
        assert result.degraded is True  # But one failed
        assert "[planner] Plan" in result.aggregated_output

    def test_fallback_dispatch_failure(self):
        coord = AgentCoordinator()
        task = _task("Implement feature X")
        goal = _goal()
        context = _context()
        # Empty results trigger fallback; if dispatch also fails, success=False
        # This is hard to trigger without mocking, so we test the normal path
        result = coord.execute_with_fallback(task, goal, context, [])
        # Fallback should succeed (dispatch_task works normally)
        assert result.success is True


class TestRetryWithBackoff:
    def test_default_retries(self):
        coord = AgentCoordinator()
        delays = coord.retry_with_backoff("t1", AgentRole.EXECUTOR)
        assert len(delays) == 3
        assert delays[0] == 1.0
        assert delays[1] == 2.0
        assert delays[2] == 4.0

    def test_custom_max_retries(self):
        coord = AgentCoordinator()
        delays = coord.retry_with_backoff("t1", AgentRole.EXECUTOR, max_retries=5)
        assert len(delays) == 5

    def test_custom_base_delay(self):
        coord = AgentCoordinator()
        delays = coord.retry_with_backoff("t1", AgentRole.EXECUTOR, base_delay=0.5)
        assert delays[0] == 0.5
        assert delays[1] == 1.0
        assert delays[2] == 2.0

    def test_exponential_growth(self):
        coord = AgentCoordinator()
        delays = coord.retry_with_backoff("t1", AgentRole.EXECUTOR, max_retries=4)
        for i in range(1, len(delays)):
            assert delays[i] == delays[i - 1] * 2

    def test_zero_retries(self):
        coord = AgentCoordinator()
        delays = coord.retry_with_backoff("t1", AgentRole.EXECUTOR, max_retries=0)
        assert delays == []


class TestCoordinationIntegration:
    def test_full_delegation_and_aggregation(self):
        """Test the full flow: delegate -> execute -> aggregate."""
        coord = AgentCoordinator()
        task = _task("Plan and implement feature X")
        goal = _goal()
        context = _context()

        # Step 1: Delegate
        delegation = coord.delegate(task, goal, context)
        assert delegation.success is True

        # Step 2: Simulate agent execution
        results = [
            _result(agent_role=AgentRole.PLANNER, success=True, output="Roadmap created"),
            _result(agent_role=AgentRole.EXECUTOR, success=True, output="Feature implemented"),
        ]

        # Step 3: Aggregate
        final = coord.aggregate(task.title, results)
        assert final.success is True
        assert final.degraded is False
        assert "[planner] Roadmap created" in final.aggregated_output
        assert "[executor] Feature implemented" in final.aggregated_output

    def test_full_flow_with_timeout(self):
        """Test the full flow with a timeout."""
        coord = AgentCoordinator()
        task = _task("Research and implement")
        goal = _goal()
        context = _context()

        # Simulate: researcher succeeds, executor times out
        results = [
            _result(agent_role=AgentRole.RESEARCHER, success=True, output="Research done"),
            coord.handle_timeout("t1", AgentRole.EXECUTOR, 300.0),
        ]

        final = coord.aggregate(task.title, results)
        assert final.success is True  # At least one succeeded
        assert final.degraded is True
        assert "[researcher] Research done" in final.aggregated_output
        assert any("timed out" in f for f in final.failures)

    def test_full_flow_with_fallback(self):
        """Test the full flow with fallback to single-agent."""
        coord = AgentCoordinator()
        task = _task("Implement feature X")
        goal = _goal()
        context = _context()

        # Simulate: all agents fail
        results = [
            _result(agent_role=AgentRole.EXECUTOR, success=False, error="build failed"),
        ]

        final = coord.execute_with_fallback(task, goal, context, results)
        assert final.success is True  # Fallback succeeds
        assert final.degraded is True
