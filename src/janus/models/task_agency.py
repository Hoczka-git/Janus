"""Agency-aware task classification model.

This module defines the TaskAgency dataclass — the derived classification
for a single task that captures who should perform it (execution_mode)
and how much support the user needs (support_mode).

TaskAgency is a planning-layer concern.  It is derived at planning time
from task properties, goal context, and user state — it is NOT persisted
as a task field.  This avoids schema changes and keeps the model flexible.
"""

from dataclasses import dataclass

from janus.models.execution_mode import ExecutionMode
from janus.models.support_mode import SupportMode


@dataclass
class TaskAgency:
    """Agency-aware classification for a single task.

    Derived at planning time from task properties, goal context,
    and user state. Not persisted — recomputed on each planning cycle.

    Attributes:
        execution_mode: Who should perform this task.
            ExecutionMode.USER | ExecutionMode.JANUS | ExecutionMode.COLLABORATIVE
        support_mode: How much support the user needs.
            SupportMode.EXPLAIN | COACH | SCAFFOLD | REVIEW | EXECUTE
        reason: Human-readable explanation of the classification.
        confidence: 0.0-1.0, how confident the classification is.
    """

    execution_mode: ExecutionMode
    support_mode: SupportMode
    reason: str
    confidence: float = 0.5

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

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict.

        Returns:
            Dict with execution_mode, support_mode as strings,
            reason as str, confidence as float.
        """
        return {
            "execution_mode": self.execution_mode.value,
            "support_mode": self.support_mode.value,
            "reason": self.reason,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskAgency":
        """Deserialize from a plain dict (inverse of :meth:`to_dict`).

        Tolerates missing keys — every field has a sensible default so a
        partial or truncated dict reconstructs a valid TaskAgency.

        Args:
            data: Dict with optional keys execution_mode, support_mode,
                reason, confidence.

        Returns:
            A new TaskAgency instance.
        """
        return cls(
            execution_mode=ExecutionMode(data.get("execution_mode", "user")),
            support_mode=SupportMode(data.get("support_mode", "explain")),
            reason=data.get("reason", ""),
            confidence=data.get("confidence", 0.5),
        )
