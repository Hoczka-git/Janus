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
