"""Action Proposal domain models for the Action Proposal Engine V1.

This module defines the structured proposal data model that captures
action type, target reference, rationale, and approval status.

V1 is proposal-only: the engine generates ActionProposal objects but
never executes them. No mutation methods are exposed.

Design reference: docs/design/action_proposal_engine_v1.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from janus.models.policy import RiskLevel


# ── Enums ────────────────────────────────────────────────────────────────────


class ActionType(StrEnum):
    """Types of actions that can be proposed.

    Each action type corresponds to a potential future mutation that
    the proposal engine can suggest but V1 cannot execute.

    Members:
        CREATE_TASK — propose creating a new task.
        UPDATE_TASK — propose updating an existing task's fields.
        RESCHEDULE_TASK — propose changing a task's due date.
        CHANGE_PRIORITY — propose changing a task's priority.
        CREATE_CALENDAR_EVENT — propose creating a calendar event.
    """

    CREATE_TASK = "CREATE_TASK"
    UPDATE_TASK = "UPDATE_TASK"
    RESCHEDULE_TASK = "RESCHEDULE_TASK"
    CHANGE_PRIORITY = "CHANGE_PRIORITY"
    CREATE_CALENDAR_EVENT = "CREATE_CALENDAR_EVENT"


class ProposalStatus(StrEnum):
    """Approval status of a proposal.

    V1 only produces PROPOSED proposals. Other statuses are for
    future approval/execution workflow.

    Members:
        PROPOSED — awaiting human decision (initial state).
        APPROVED — human approved; ready for future execution.
        REJECTED — human rejected; terminal.
        EXECUTED — action was executed; terminal.
    """

    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"


# ── Proposal model ───────────────────────────────────────────────────────────


@dataclass
class ActionProposal:
    """A structured proposal for a future action.

    This is the core data model of the Action Proposal Engine V1.
    It captures what action should be taken, on what target, why,
    and the current approval status.

    V1 is proposal-only: the engine generates these objects but
    never executes them. No mutation methods are exposed.

    Attributes:
        proposal_id: Stable identity (``AP-<8-hex>``).
        action_type: The type of action being proposed.
        target_id: Optional reference to the target entity
            (task title, goal title, or event title).
        parameters: Action-specific parameters (e.g., new due date,
            new priority, task title for CREATE_TASK).
        reason: Human-readable justification for this proposal.
        source: Origin of the proposal (e.g., "weekly_planner",
            "rule:overdue", "rule:missing_task").
        risk: Risk level of the proposed action.
        status: Current approval status.
        created_at: When the proposal was created.
        updated_at: When the proposal last changed.
        metadata: Additional structured data.
    """

    proposal_id: str = ""
    action_type: ActionType = ActionType.CREATE_TASK
    target_id: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    source: str = ""
    risk: RiskLevel = RiskLevel.LOW
    status: ProposalStatus = ProposalStatus.PROPOSED
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.proposal_id and not self.proposal_id.strip():
            raise ValueError("ActionProposal.proposal_id must not be empty")
        if not self.reason or not self.reason.strip():
            raise ValueError("ActionProposal.reason must not be empty")
        if self.created_at is None:
            self.created_at = datetime.now().astimezone()
        if self.updated_at is None:
            self.updated_at = self.created_at

    @property
    def is_actionable(self) -> bool:
        """True if the proposal is in a state that can be acted upon."""
        return self.status == ProposalStatus.PROPOSED

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "proposal_id": self.proposal_id,
            "action_type": self.action_type.value,
            "target_id": self.target_id,
            "parameters": dict(self.parameters),
            "reason": self.reason,
            "source": self.source,
            "risk": self.risk.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActionProposal:
        """Deserialize from a plain dict."""
        return cls(
            proposal_id=data.get("proposal_id", ""),
            action_type=ActionType(data.get("action_type", "CREATE_TASK")),
            target_id=data.get("target_id"),
            parameters=data.get("parameters") or {},
            reason=data.get("reason", ""),
            source=data.get("source", ""),
            risk=RiskLevel(data.get("risk", "low")),
            status=ProposalStatus(data.get("status", "PROPOSED")),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
            metadata=data.get("metadata") or {},
        )
