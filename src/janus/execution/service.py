"""Execution service — persistence and idempotency for execution results.

This module provides the ExecutionService which wraps the TaskExecutor
with persistence and idempotency checks. It ensures that:
1. Execution results are persisted to disk (auditable).
2. The same proposal cannot be executed more than once.
3. The execution lifecycle is fully auditable.

Design reference: docs/design/action_proposal_engine_v1.md
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from janus.execution.executor import TaskExecutor
from janus.execution.models import ExecutionResult, ExecutionStatus
from janus.execution.policy import PolicyGate
from janus.proposal.models import ActionProposal

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXECUTIONS_PATH = PROJECT_ROOT / "data" / "executions.jsonl"


class ExecutionService:
    """Service for executing approved proposals with persistence.

    This service wraps the TaskExecutor with:
    - Idempotency: tracks which proposals have been executed
    - Persistence: writes execution results to data/executions.jsonl
    - Audit trail: preserves the complete execution lifecycle
    """

    def __init__(
        self,
        executor: TaskExecutor | None = None,
        executions_path: Path | None = None,
    ) -> None:
        """Initialize the execution service.

        Args:
            executor: Optional executor instance. If not provided,
                a default TaskExecutor is created.
            executions_path: Optional path to the executions file.
                Defaults to data/executions.jsonl.
        """
        self._executions_path = executions_path or EXECUTIONS_PATH
        self._executor = executor or TaskExecutor(
            policy_gate=PolicyGate(is_executed=self.is_executed),
        )

    def execute(self, proposal: ActionProposal) -> ExecutionResult:
        """Execute an approved proposal with persistence.

        Args:
            proposal: The approved proposal to execute.

        Returns:
            An ExecutionResult indicating success, failure, or skip.
        """
        # Check idempotency
        if self.is_executed(proposal.proposal_id):
            execution_id = f"EX-{proposal.proposal_id[:8]}"
            return ExecutionResult(
                execution_id=execution_id,
                proposal_id=proposal.proposal_id,
                status=ExecutionStatus.SKIPPED,
                action_type=proposal.action_type,
                target_id=proposal.target_id,
                error="Proposal has already been executed",
            )

        # Execute
        result = self._executor.execute(proposal)

        # Persist
        self._persist(result)

        return result

    def is_executed(self, proposal_id: str) -> bool:
        """Check if a proposal has already been executed.

        Args:
            proposal_id: The proposal ID to check.

        Returns:
            True if the proposal has been executed, False otherwise.
        """
        if not self._executions_path.exists():
            return False

        try:
            content = self._executions_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if record.get("proposal_id") == proposal_id:
                        return True
                except json.JSONDecodeError:
                    continue
        except OSError:
            return False

        return False

    def get_execution(self, execution_id: str) -> ExecutionResult | None:
        """Retrieve an execution result by ID.

        Args:
            execution_id: The execution ID to look up.

        Returns:
            The ExecutionResult if found, None otherwise.
        """
        if not self._executions_path.exists():
            return None

        try:
            content = self._executions_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if record.get("execution_id") == execution_id:
                        return ExecutionResult.from_dict(record)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
        except OSError:
            return None

        return None

    def list_executions(self) -> list[ExecutionResult]:
        """List all execution results.

        Returns:
            A list of all ExecutionResult records.
        """
        results: list[ExecutionResult] = []

        if not self._executions_path.exists():
            return results

        try:
            content = self._executions_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    results.append(ExecutionResult.from_dict(record))
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
        except OSError:
            pass

        return results

    def _persist(self, result: ExecutionResult) -> None:
        """Persist an execution result to the executions file.

        Args:
            result: The ExecutionResult to persist.
        """
        self._executions_path.parent.mkdir(parents=True, exist_ok=True)

        record = json.dumps(result.to_dict(), ensure_ascii=False)
        with self._executions_path.open("a", encoding="utf-8") as f:
            f.write(record + "\n")

        logger.info(
            "Execution %s persisted: %s %s -> %s",
            result.execution_id,
            result.action_type.value,
            result.proposal_id,
            result.status.value,
        )
