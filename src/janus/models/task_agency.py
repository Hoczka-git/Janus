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
