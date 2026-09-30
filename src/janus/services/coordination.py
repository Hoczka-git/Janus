"""Multi-agent coordination and failure handling.

This module implements the coordination layer for Phase H multi-agent
orchestration. It builds on the core primitives (AgentRole, AgentAssignment,
AgentRegistry, dispatch_task) to provide:

- Task delegation: assign tasks to the appropriate agent role
- Result aggregation: combine results from multiple agent executions
- Timeout handling: gracefully handle agent execution timeouts
- Graceful degradation: fall back to single-agent flow on any failure

The coordination layer is a pure-logic module — it does not perform I/O
or spawn processes. It operates on AgentResult values that are produced
by the Hermes execution path, making it fully testable in isolation.

Design reference: docs/design/phase_h_multi_agent_orchestration.md
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from janus.models.agent_assignment import AgentAssignment
from janus.models.agent_role import AgentRole
from janus.models.execution_mode import ExecutionMode
from janus.models.goal import Goal
from janus.models.task import Task
from janus.services.agent_registry import AgentRegistry
from janus.services.agency_planning import AgencyContext, dispatch_task
from janus.services.execution_feedback import EvidencePackage

logger = logging.getLogger(__name__)


# ── Result models ────────────────────────────────────────────────────────────


@dataclass
class AgentResult:
    """Result from a single agent execution.

    Produced by the Hermes execution path after an agent completes
    (or fails) a task. The coordination layer consumes these results
    for aggregation and failure handling.

    Attributes:
        task_id: The task that was executed.
        agent_role: The agent role that executed the task.
        success: Whether the execution succeeded.
        output: The agent's output (e.g., summary, artifact content).
        evidence: Structured evidence of the execution (if any).
        error: Error message if the execution failed.
        duration_seconds: How long the execution took.
        timed_out: Whether the execution timed out.
    """

    task_id: str
    agent_role: AgentRole
    success: bool
    output: str = ""
    evidence: EvidencePackage | None = None
    error: str | None = None
    duration_seconds: float = 0.0
    timed_out: bool = False


@dataclass
class CoordinationResult:
    """Aggregated result from multi-agent coordination.

    Returned by the coordinator after delegating and executing a task.
    Contains the individual agent results plus an aggregated view.

    Attributes:
        task_id: The original task that was coordinated.
        success: Whether the overall coordination succeeded.
        agent_results: Individual results from each agent execution.
        aggregated_output: Combined output from all agents.
        total_duration_seconds: Total wall-clock time for coordination.
        failures: List of failure descriptions (empty if all succeeded).
        degraded: True if any agent failed and the system fell back
            to a degraded mode (e.g., single-agent flow).
    """

    task_id: str
    success: bool
    agent_results: list[AgentResult] = field(default_factory=list)
    aggregated_output: str = ""
    total_duration_seconds: float = 0.0
    failures: list[str] = field(default_factory=list)
    degraded: bool = False


# ── Coordinator ─────────────────────────────────────────────────────────────


class AgentCoordinator:
    """Coordinates multi-agent task execution.

    The coordinator is the main entry point for the coordination layer.
    It delegates tasks to the appropriate agent role, aggregates results,
    handles timeouts, and provides graceful degradation on failure.

    The coordinator is a pure-logic class — it does not perform I/O
    or spawn processes. The Hermes execution path is responsible for
    actually running agents and producing AgentResult values.

    Usage:
        coordinator = AgentCoordinator()
        result = coordinator.delegate(task, goal, context)
        if result.success:
            print(result.aggregated_output)
        else:
            print("Failures:", result.failures)
    """

    def __init__(
        self,
        registry: AgentRegistry | None = None,
        timeout_seconds: float = 300.0,
    ) -> None:
        """Initialize the coordinator.

        Args:
            registry: The agent registry to use for role matching.
                If None, a default registry is created.
            timeout_seconds: Default timeout for agent execution.
                Can be overridden per-delegation.
        """
        self.registry = registry or AgentRegistry()
        self.timeout_seconds = timeout_seconds

    def delegate(
        self,
        task: Task,
        goal: Goal,
        context: AgencyContext,
        timeout_seconds: float | None = None,
    ) -> CoordinationResult:
        """Delegate a task to the appropriate agent.

        This is the main entry point for task delegation. It:
        1. Calls dispatch_task() to determine the agent role
        2. If no specialized agent is needed, returns a single-agent result
        3. If a specialized agent is needed, returns a coordination result
           with the agent assignment

        The actual agent execution is performed by the Hermes execution
        path. This method returns the coordination plan; the caller
        executes the plan and calls aggregate() with the results.

        Args:
            task: The task to delegate.
            goal: The parent goal (provides context).
            context: Agency context signals.
            timeout_seconds: Override the default timeout for this delegation.

        Returns:
            A CoordinationResult with the delegation plan and any
            immediate results (e.g., fallback on dispatch failure).
        """
        start_time = time.monotonic()
        timeout = timeout_seconds or self.timeout_seconds

        try:
            assignment = dispatch_task(task, goal, context)
        except Exception as e:
            logger.warning("Dispatch failed for task %s: %s", task.title, e)
            return self._handle_dispatch_failure(task, str(e), start_time)

        if assignment.agent_role is None:
            # No specialized agent needed — single-agent flow
            return self._single_agent_result(task, assignment, start_time)

        # Specialized agent needed — return the coordination plan
        return CoordinationResult(
            task_id=task.title,
            success=True,  # Delegation succeeded; execution is separate
            agent_results=[],
            aggregated_output="",
            total_duration_seconds=time.monotonic() - start_time,
            failures=[],
            degraded=False,
        )

    def aggregate(
        self,
        task_id: str,
        results: list[AgentResult],
        start_time: float | None = None,
    ) -> CoordinationResult:
        """Aggregate results from multiple agent executions.

        Combines individual AgentResult values into a single
        CoordinationResult with:
        - Combined output from all successful agents
        - List of failures from failed agents
        - Degraded flag if any agent failed

        Args:
            task_id: The original task that was coordinated.
            results: Individual results from each agent execution.
            start_time: Optional start time for duration calculation.

        Returns:
            A CoordinationResult with the aggregated view.
        """
        if start_time is not None:
            total_duration = time.monotonic() - start_time
        else:
            total_duration = sum(r.duration_seconds for r in results)

        successes = [r for r in results if r.success]
        failures = [r for r in results if not r.success]

        # Build aggregated output from successful results
        output_parts: list[str] = []
        for r in successes:
            if r.output:
                output_parts.append(f"[{r.agent_role.value}] {r.output}")
        aggregated_output = "\n\n".join(output_parts)

        # Build failure descriptions
        failure_descs: list[str] = []
        for r in failures:
            desc = f"Agent {r.agent_role.value} failed"
            if r.timed_out:
                desc += " (timed out)"
            if r.error:
                desc += f": {r.error}"
            failure_descs.append(desc)

        # Degraded if any agent failed
        degraded = len(failures) > 0

        # Overall success if at least one agent succeeded
        overall_success = len(successes) > 0

        return CoordinationResult(
            task_id=task_id,
            success=overall_success,
            agent_results=results,
            aggregated_output=aggregated_output,
            total_duration_seconds=total_duration,
            failures=failure_descs,
            degraded=degraded,
        )

    def handle_timeout(
        self,
        task_id: str,
        agent_role: AgentRole,
        duration_seconds: float,
    ) -> AgentResult:
        """Handle an agent timeout gracefully.

        Creates a failed AgentResult with timed_out=True. The caller
        should then either retry, escalate, or fall back to the
        single-agent flow.

        Args:
            task_id: The task that timed out.
            agent_role: The agent role that timed out.
            duration_seconds: How long the agent ran before timing out.

        Returns:
            A failed AgentResult with timed_out=True.
        """
        logger.warning(
            "Agent %s timed out after %.1fs for task %s",
            agent_role.value,
            duration_seconds,
            task_id,
        )
        return AgentResult(
            task_id=task_id,
            agent_role=agent_role,
            success=False,
            error=f"Agent timed out after {duration_seconds:.1f}s",
            duration_seconds=duration_seconds,
            timed_out=True,
        )

    def handle_failure(
        self,
        task_id: str,
        agent_role: AgentRole,
        error: str,
        duration_seconds: float = 0.0,
    ) -> AgentResult:
        """Handle an agent failure gracefully.

        Creates a failed AgentResult. The caller should then either
        retry, escalate, or fall back to the single-agent flow.

        Args:
            task_id: The task that failed.
            agent_role: The agent role that failed.
            error: The error message.
            duration_seconds: How long the agent ran before failing.

        Returns:
            A failed AgentResult.
        """
        logger.warning(
            "Agent %s failed for task %s: %s",
            agent_role.value,
            task_id,
            error,
        )
        return AgentResult(
            task_id=task_id,
            agent_role=agent_role,
            success=False,
            error=error,
            duration_seconds=duration_seconds,
        )

    def execute_with_fallback(
        self,
        task: Task,
        goal: Goal,
        context: AgencyContext,
        agent_results: list[AgentResult],
    ) -> CoordinationResult:
        """Execute a task with graceful fallback on agent failure.

        If all agent results are successful, returns the aggregated result.
        If any agent failed, falls back to the single-agent flow by
        calling dispatch_task() with a degraded context.

        This is the main entry point for the Hermes execution path after
        agents have completed (or failed) their tasks.

        Args:
            task: The original task.
            goal: The parent goal.
            context: Agency context signals.
            agent_results: Results from agent executions.

        Returns:
            A CoordinationResult with the final outcome.
        """
        start_time = time.monotonic()

        if not agent_results:
            # No agents were run — fall back to single-agent flow
            return self._fallback_to_single(task, goal, context, start_time)

        # Check if all agents succeeded
        all_succeeded = all(r.success for r in agent_results)

        if all_succeeded:
            return self.aggregate(task.title, agent_results, start_time)

        # Some agents failed — aggregate what we have, then fall back
        partial = self.aggregate(task.title, agent_results, start_time)

        # If no agent succeeded at all, fall back to single-agent flow
        if not partial.success:
            return self._fallback_to_single(task, goal, context, start_time)

        # Some agents succeeded — return partial result with degraded flag
        return partial

    def retry_with_backoff(
        self,
        task_id: str,
        agent_role: AgentRole,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> list[float]:
        """Calculate retry delays with exponential backoff.

        Returns a list of delays (in seconds) to wait between retries.
        The caller is responsible for actually retrying the agent.

        Args:
            task_id: The task to retry (for logging).
            agent_role: The agent role to retry.
            max_retries: Maximum number of retry attempts.
            base_delay: Base delay in seconds (doubles each retry).

        Returns:
            A list of delays in seconds.
        """
        delays = []
        delay = base_delay
        for _ in range(max_retries):
            delays.append(delay)
            delay *= 2
        logger.info(
            "Retry plan for task %s (agent %s): %d retries, delays=%s",
            task_id,
            agent_role.value,
            max_retries,
            delays,
        )
        return delays

    # ── Private helpers ────────────────────────────────────────────────────

    def _handle_dispatch_failure(
        self,
        task: Task,
        error: str,
        start_time: float,
    ) -> CoordinationResult:
        """Handle dispatch failure by falling back to single-agent flow."""
        logger.warning(
            "Dispatch failed for task %s: %s — falling back to single-agent flow",
            task.title,
            error,
        )
        return CoordinationResult(
            task_id=task.title,
            success=True,  # Fallback is a success (degraded but functional)
            agent_results=[],
            aggregated_output="",
            total_duration_seconds=time.monotonic() - start_time,
            failures=[f"Dispatch failed: {error}"],
            degraded=True,
        )

    def _single_agent_result(
        self,
        task: Task,
        assignment: AgentAssignment,
        start_time: float,
    ) -> CoordinationResult:
        """Create a result for single-agent flow (no specialized agent)."""
        return CoordinationResult(
            task_id=task.title,
            success=True,
            agent_results=[],
            aggregated_output="",
            total_duration_seconds=time.monotonic() - start_time,
            failures=[],
            degraded=False,
        )

    def _fallback_to_single(
        self,
        task: Task,
        goal: Goal,
        context: AgencyContext,
        start_time: float,
    ) -> CoordinationResult:
        """Fall back to single-agent flow after agent failure."""
        try:
            assignment = dispatch_task(task, goal, context)
            return CoordinationResult(
                task_id=task.title,
                success=True,
                agent_results=[],
                aggregated_output="",
                total_duration_seconds=time.monotonic() - start_time,
                failures=["All agents failed — fell back to single-agent flow"],
                degraded=True,
            )
        except Exception as e:
            logger.error(
                "Fallback dispatch also failed for task %s: %s",
                task.title,
                e,
            )
            return CoordinationResult(
                task_id=task.title,
                success=False,
                agent_results=[],
                aggregated_output="",
                total_duration_seconds=time.monotonic() - start_time,
                failures=[f"Dispatch failed: {e}", "Fallback also failed"],
                degraded=True,
            )
