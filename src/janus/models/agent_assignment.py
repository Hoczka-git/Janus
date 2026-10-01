"""Agent assignment model for multi-agent orchestration.

This module defines the AgentAssignment dataclass — the dispatch
decision returned by the dispatch_task() function. It extends the
existing TaskAgency with agent-role granularity.

Design reference: docs/design/phase_h_multi_agent_orchestration.md
"""

from dataclasses import dataclass, field

from janus.models.agent_role import AgentRole
from janus.models.execution_mode import ExecutionMode
from janus.models.support_mode import SupportMode


@dataclass
class AgentAssignment:
    """Dispatch decision for a single task.

    Derived at planning time from task properties, goal context,
    and user state. Not persisted — recomputed on each planning cycle.

    Attributes:
        execution_mode: Who should perform this task.
        support_mode: How much support is needed.
        agent_role: Which specialized agent role is needed (None if no
            specialized agent is needed — the task is handled by the
            existing flow).
        reason: Human-readable explanation of the dispatch decision.
        confidence: 0.0-1.0, how confident the dispatch is.
        required_capabilities: List of capability strings needed for
            this task (used for skill matching and gap detection).
    """

    execution_mode: ExecutionMode
    support_mode: SupportMode
    agent_role: AgentRole | None = None
    reason: str = ""
    confidence: float = 0.5
    required_capabilities: list[str] | None = field(default=None)

    def __post_init__(self) -> None:
        """Validate field values after initialization."""
        if not isinstance(self.execution_mode, ExecutionMode):
            raise TypeError(
                f"execution_mode must be an ExecutionMode, got {type(self.execution_mode).__name__}"
            )
        if not isinstance(self.support_mode, SupportMode):
            raise TypeError(
                f"support_mode must be a SupportMode, got {type(self.support_mode).__name__}"
            )
        if self.agent_role is not None and not isinstance(self.agent_role, AgentRole):
            raise TypeError(
                f"agent_role must be an AgentRole or None, got {type(self.agent_role).__name__}"
            )
        if not isinstance(self.reason, str):
            raise TypeError(f"reason must be a str, got {type(self.reason).__name__}")
        if not isinstance(self.confidence, (int, float)):
            raise TypeError(
                f"confidence must be a number, got {type(self.confidence).__name__}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {self.confidence}"
            )
        if self.required_capabilities is not None:
            if not isinstance(self.required_capabilities, list):
                raise TypeError(
                    f"required_capabilities must be a list or None, got {type(self.required_capabilities).__name__}"
                )
            for cap in self.required_capabilities:
                if not isinstance(cap, str):
                    raise TypeError(
                        f"required_capabilities items must be str, got {type(cap).__name__}"
                    )

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict.

        Returns:
            Dict with execution_mode, support_mode as strings,
            agent_role as string or None, reason as str,
            confidence as float, required_capabilities as list or None.
        """
        return {
            "execution_mode": self.execution_mode.value,
            "support_mode": self.support_mode.value,
            "agent_role": self.agent_role.value if self.agent_role else None,
            "reason": self.reason,
            "confidence": self.confidence,
            "required_capabilities": self.required_capabilities,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentAssignment":
        """Deserialize from a plain dict (inverse of :meth:`to_dict`).

        Tolerates missing keys — every field has a sensible default so a
        partial or truncated dict reconstructs a valid AgentAssignment.

        Args:
            data: Dict with optional keys execution_mode, support_mode,
                agent_role, reason, confidence, required_capabilities.

        Returns:
            A new AgentAssignment instance.
        """
        agent_role = None
        raw_role = data.get("agent_role")
        if raw_role is not None:
            agent_role = AgentRole(raw_role)
        return cls(
            execution_mode=ExecutionMode(data.get("execution_mode", "user")),
            support_mode=SupportMode(data.get("support_mode", "explain")),
            agent_role=agent_role,
            reason=data.get("reason", ""),
            confidence=data.get("confidence", 0.5),
            required_capabilities=data.get("required_capabilities"),
        )
