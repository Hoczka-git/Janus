"""Execution domain models for the Execution Engine V1.

This module defines the structured execution result data model that captures
what happened when an approved ActionProposal was executed.

V1 supports CREATE_TASK, UPDATE_TASK, and RESCHEDULE_TASK actions.
Execution is controlled: it requires an explicit approval and passes
through a policy gate before performing any state change.

Design reference: docs/design/action_proposal_engine_v1.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from janus.proposal.models import ActionType


# ── Enums ────────────────────────────────────────────────────────────────────


class ExecutionStatus(StrEnum):
    """Status of an execution attempt.

    Members:
        SUCCESS — the action was executed successfully.
        FAILED  — the action failed (e.g., target not found, invalid params).
        SKIPPED — the action was skipped (e.g., already executed, policy denied).
    """

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


# ── ExecutionResult model ────────────────────────────────────────────────────


@dataclass
class ExecutionResult:
    """The result of executing an ActionProposal.

    This is the core data model of the Execution Engine V1.
    It captures what action was attempted, on what target, whether it
    succeeded, and any error information.

    Attributes:
        execution_id: Stable identity (``EX-<8-hex>``).
        proposal_id: The proposal that was executed.
        status: The execution status (SUCCESS, FAILED, SKIPPED).
        action_type: The type of action that was executed.
        target_id: Optional reference to the target entity.
        timestamp: When the execution occurred.
        result_details: Additional structured data about the execution.
        error: Error message if the execution failed.
    """

    execution_id: str = ""
    proposal_id: str = ""
    status: ExecutionStatus = ExecutionStatus.SKIPPED
    action_type: ActionType = ActionType.CREATE_TASK
    target_id: str | None = None
    timestamp: datetime | None = None
    result_details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        if self.execution_id and not self.execution_id.strip():
            raise ValueError("ExecutionResult.execution_id must not be empty")
        if self.timestamp is None:
            self.timestamp = datetime.now().astimezone()

    @property
    def is_success(self) -> bool:
        """True if the execution succeeded."""
        return self.status == ExecutionStatus.SUCCESS

    @property
    def is_failed(self) -> bool:
        """True if the execution failed."""
        return self.status == ExecutionStatus.FAILED

    @property
    def is_skipped(self) -> bool:
        """True if the execution was skipped."""
        return self.status == ExecutionStatus.SKIPPED

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "execution_id": self.execution_id,
            "proposal_id": self.proposal_id,
            "status": self.status.value,
            "action_type": self.action_type.value,
            "target_id": self.target_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "result_details": dict(self.result_details),
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionResult:
        """Deserialize from a plain dict."""
        return cls(
            execution_id=data.get("execution_id", ""),
            proposal_id=data.get("proposal_id", ""),
            status=ExecutionStatus(data.get("status", "SKIPPED")),
            action_type=ActionType(data.get("action_type", "CREATE_TASK")),
            target_id=data.get("target_id"),
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else None,
            result_details=data.get("result_details") or {},
            error=data.get("error"),
        )


# ── PolicyDecision model ──────────────────────────────────────────────────────


@dataclass
class PolicyDecision:
    """The result of a policy gate evaluation.

    Attributes:
        allowed: Whether the execution is allowed.
        reason: Human-readable explanation.
        proposal_id: The proposal that was evaluated.
    """

    allowed: bool = False
    reason: str = ""
    proposal_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "proposal_id": self.proposal_id,
        }
