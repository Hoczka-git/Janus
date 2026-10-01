"""Routine model for Janus — Phase C (Personal State).

A ``Routine`` represents a recurring activity or habit that the user
wants to track. Routines are tracked as part of the PersonalState
aggregate to provide a complete view of the user's current state.

Spec: ``docs/janus-agency-first-development-phase.md`` §13 Phase C.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class RoutineFrequency(StrEnum):
    """Frequency of a routine."""

    DAILY = "daily"
    """The routine occurs daily."""

    WEEKLY = "weekly"
    """The routine occurs weekly."""

    MONTHLY = "monthly"
    """The routine occurs monthly."""

    CUSTOM = "custom"
    """The routine occurs on a custom schedule."""


@dataclass
class Routine:
    """A recurring activity or habit.

    Attributes:
        id: Stable identity for the routine.
        title: Human-readable description of the routine.
        frequency: How often the routine occurs.
        status: Current status of the routine.
        created_at: When the routine was created.
        last_completed: When the routine was last completed.
        streak: Current streak of consecutive completions.
        linked_goal_title: Optional goal this routine relates to.
        notes: Additional notes about the routine.
    """

    id: str
    title: str
    frequency: RoutineFrequency = RoutineFrequency.DAILY
    status: str = "active"  # active | paused | completed
    created_at: datetime | None = None
    last_completed: datetime | None = None
    streak: int = 0
    linked_goal_title: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("Routine.id must not be empty")
        if not self.title or not self.title.strip():
            raise ValueError("Routine.title must not be empty")
        if not isinstance(self.frequency, RoutineFrequency):
            raise ValueError(
                f"Invalid frequency: {self.frequency!r}. "
                f"Allowed: {', '.join(f.value for f in RoutineFrequency)}"
            )
        if self.status not in ("active", "paused", "completed"):
            raise ValueError(
                f"Invalid status: {self.status!r}. "
                f"Allowed: active, paused, completed"
            )
        if self.created_at is None:
            self.created_at = datetime.now()

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        from dataclasses import asdict

        raw = asdict(self)
        raw["frequency"] = self.frequency.value
        if self.created_at and hasattr(self.created_at, "isoformat"):
            raw["created_at"] = self.created_at.isoformat()
        if self.last_completed and hasattr(self.last_completed, "isoformat"):
            raw["last_completed"] = self.last_completed.isoformat()
        return raw
