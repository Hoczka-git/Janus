"""Execution Engine protocol — the interface for action execution.

This module defines the :class:`ActionExecutor` protocol that all
execution engine implementations must satisfy.

V1 supports CREATE_TASK, UPDATE_TASK, and RESCHEDULE_TASK actions.
Execution is controlled: it requires an explicit approval and passes
through a policy gate before performing any state change.

Design reference: docs/design/action_proposal_engine_v1.md
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from janus.execution.models import ExecutionResult
from janus.proposal.models import ActionProposal


@runtime_checkable
class ActionExecutor(Protocol):
    """Interface for action executor implementations.

    Implementations must provide a single ``execute`` method that takes
    an approved ActionProposal and returns an ExecutionResult.

    The executor is controlled: it only executes proposals that have
    been explicitly approved and have passed the policy gate. No
    autonomous execution is permitted.

    V1 implementation is ``TaskExecutor`` (supports CREATE_TASK,
    UPDATE_TASK, RESCHEDULE_TASK).

    Example usage::

        executor: ActionExecutor = TaskExecutor()
        result = executor.execute(proposal)
    """

    def execute(
        self,
        proposal: ActionProposal,
    ) -> ExecutionResult:
        """Execute an approved action proposal.

        Args:
            proposal: The approved action proposal to execute.

        Returns:
            An ExecutionResult indicating success, failure, or skip.

        Raises:
            ValueError: If the proposal is not approved or invalid.
        """
        ...
