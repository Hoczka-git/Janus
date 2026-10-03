"""Task executor — V1 implementation of ActionExecutor.

This module implements the execution engine for task-related actions.
It supports CREATE_TASK, UPDATE_TASK, and RESCHEDULE_TASK by delegating
to the existing Janus task services.

The executor is controlled: it only executes proposals that have been
explicitly approved and have passed the policy gate. No autonomous
execution is permitted.

Design reference: docs/design/action_proposal_engine_v1.md
"""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from typing import Any

from janus.execution.models import ExecutionResult, ExecutionStatus
from janus.execution.policy import PolicyGate
from janus.proposal.models import ActionProposal, ActionType


class TaskExecutor:
    """V1 task executor — executes approved task-related proposals.

    Supports:
        - CREATE_TASK: creates a new task via add_task()
        - UPDATE_TASK: updates task state/progress via set_task_state()
        - RESCHEDULE_TASK: updates task due date via set_task_due_date()

    The executor is idempotent: it checks whether a proposal has already
    been executed before performing any state change.
    """

    def __init__(
        self,
        policy_gate: PolicyGate | None = None,
        is_executed: Any = None,
    ) -> None:
        """Initialize the task executor.

        Args:
            policy_gate: Optional policy gate instance. If not provided,
                a default gate is created with the given is_executed callback.
            is_executed: Optional callable that takes a proposal_id and
                returns True if the proposal has already been executed.
        """
        self._policy_gate = policy_gate or PolicyGate(is_executed=is_executed)
        self._is_executed = is_executed

    def execute(self, proposal: ActionProposal) -> ExecutionResult:
        """Execute an approved action proposal.

        Args:
            proposal: The approved action proposal to execute.

        Returns:
            An ExecutionResult indicating success, failure, or skip.
        """
        # Generate execution ID
        execution_id = f"EX-{uuid.uuid4().hex[:8]}"

        # Policy gate check
        decision = self._policy_gate.evaluate(proposal)
        if not decision.allowed:
            return ExecutionResult(
                execution_id=execution_id,
                proposal_id=proposal.proposal_id,
                status=ExecutionStatus.SKIPPED,
                action_type=proposal.action_type,
                target_id=proposal.target_id,
                error=decision.reason,
                result_details={"policy_decision": decision.to_dict()},
            )

        # Execute based on action type
        try:
            if proposal.action_type == ActionType.CREATE_TASK:
                return self._execute_create_task(proposal, execution_id)
            elif proposal.action_type == ActionType.UPDATE_TASK:
                return self._execute_update_task(proposal, execution_id)
            elif proposal.action_type == ActionType.RESCHEDULE_TASK:
                return self._execute_reschedule_task(proposal, execution_id)
            else:
                return ExecutionResult(
                    execution_id=execution_id,
                    proposal_id=proposal.proposal_id,
                    status=ExecutionStatus.FAILED,
                    action_type=proposal.action_type,
                    target_id=proposal.target_id,
                    error=f"Unsupported action type: {proposal.action_type.value}",
                )
        except Exception as exc:
            return ExecutionResult(
                execution_id=execution_id,
                proposal_id=proposal.proposal_id,
                status=ExecutionStatus.FAILED,
                action_type=proposal.action_type,
                target_id=proposal.target_id,
                error=str(exc),
            )

    def _execute_create_task(
        self,
        proposal: ActionProposal,
        execution_id: str,
    ) -> ExecutionResult:
        """Execute a CREATE_TASK proposal."""
        from janus.services.tasks import add_task

        title = proposal.parameters.get("title")
        if not title:
            return ExecutionResult(
                execution_id=execution_id,
                proposal_id=proposal.proposal_id,
                status=ExecutionStatus.FAILED,
                action_type=proposal.action_type,
                target_id=proposal.target_id,
                error="Missing required parameter: title",
            )

        # Parse optional parameters
        due_date_str = proposal.parameters.get("due_date")
        due_date = None
        if due_date_str:
            try:
                due_date = date.fromisoformat(due_date_str)
            except ValueError:
                return ExecutionResult(
                    execution_id=execution_id,
                    proposal_id=proposal.proposal_id,
                    status=ExecutionStatus.FAILED,
                    action_type=proposal.action_type,
                    target_id=proposal.target_id,
                    error=f"Invalid due date: {due_date_str}",
                )

        priority = proposal.parameters.get("priority", 1)
        if isinstance(priority, str):
            try:
                priority = int(priority)
            except ValueError:
                return ExecutionResult(
                    execution_id=execution_id,
                    proposal_id=proposal.proposal_id,
                    status=ExecutionStatus.FAILED,
                    action_type=proposal.action_type,
                    target_id=proposal.target_id,
                    error=f"Invalid priority: {priority}",
                )

        task = add_task(title, due_date, priority)

        return ExecutionResult(
            execution_id=execution_id,
            proposal_id=proposal.proposal_id,
            status=ExecutionStatus.SUCCESS,
            action_type=proposal.action_type,
            target_id=task.title,
            result_details={
                "task_title": task.title,
                "due_date": task.due_date.isoformat() if task.due_date else None,
                "priority": task.priority,
            },
        )

    def _execute_update_task(
        self,
        proposal: ActionProposal,
        execution_id: str,
    ) -> ExecutionResult:
        """Execute an UPDATE_TASK proposal."""
        from janus.services.tasks import set_task_state

        target_id = proposal.target_id
        if not target_id:
            return ExecutionResult(
                execution_id=execution_id,
                proposal_id=proposal.proposal_id,
                status=ExecutionStatus.FAILED,
                action_type=proposal.action_type,
                target_id=proposal.target_id,
                error="Missing target_id",
            )

        # For V1, UPDATE_TASK sets the task state to in_progress
        # (the risk_description parameter is informational)
        new_state = proposal.parameters.get("new_state", "in_progress")
        if new_state not in ("todo", "in_progress", "blocked"):
            return ExecutionResult(
                execution_id=execution_id,
                proposal_id=proposal.proposal_id,
                status=ExecutionStatus.FAILED,
                action_type=proposal.action_type,
                target_id=proposal.target_id,
                error=f"Invalid state: {new_state}",
            )

        task = set_task_state(target_id, new_state)

        return ExecutionResult(
            execution_id=execution_id,
            proposal_id=proposal.proposal_id,
            status=ExecutionStatus.SUCCESS,
            action_type=proposal.action_type,
            target_id=task.title,
            result_details={
                "task_title": task.title,
                "new_state": task.state,
                "risk_description": proposal.parameters.get("risk_description"),
            },
        )

    def _execute_reschedule_task(
        self,
        proposal: ActionProposal,
        execution_id: str,
    ) -> ExecutionResult:
        """Execute a RESCHEDULE_TASK proposal."""
        from janus.services.tasks import set_task_due_date

        target_id = proposal.target_id
        if not target_id:
            return ExecutionResult(
                execution_id=execution_id,
                proposal_id=proposal.proposal_id,
                status=ExecutionStatus.FAILED,
                action_type=proposal.action_type,
                target_id=proposal.target_id,
                error="Missing target_id",
            )

        new_due_date_str = proposal.parameters.get("new_due_date")
        if not new_due_date_str:
            return ExecutionResult(
                execution_id=execution_id,
                proposal_id=proposal.proposal_id,
                status=ExecutionStatus.FAILED,
                action_type=proposal.action_type,
                target_id=proposal.target_id,
                error="Missing required parameter: new_due_date",
            )

        try:
            new_due_date = date.fromisoformat(new_due_date_str)
        except ValueError:
            return ExecutionResult(
                execution_id=execution_id,
                proposal_id=proposal.proposal_id,
                status=ExecutionStatus.FAILED,
                action_type=proposal.action_type,
                target_id=proposal.target_id,
                error=f"Invalid due date: {new_due_date_str}",
            )

        task = set_task_due_date(target_id, new_due_date)

        return ExecutionResult(
            execution_id=execution_id,
            proposal_id=proposal.proposal_id,
            status=ExecutionStatus.SUCCESS,
            action_type=proposal.action_type,
            target_id=task.title,
            result_details={
                "task_title": task.title,
                "new_due_date": task.due_date.isoformat() if task.due_date else None,
                "old_due_date": proposal.parameters.get("old_due_date"),
            },
        )
