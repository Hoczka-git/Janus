"""Commitment model for Janus — Phase C (Personal State).

A ``Commitment`` represents a personal commitment or obligation that
the user has made. Commitments are tracked as part of the PersonalState
aggregate to provide a complete view of the user's current state.

Spec: ``docs/janus-agency-first-development-phase.md`` §13 Phase C.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class CommitmentStatus(StrEnum):
    """Status of a commitment."""

    ACTIVE = "active"
    """The commitment is currently active."""

    COMPLETED = "completed"
    """The commitment has been fulfilled."""

    BROKEN = "broken"
    """The commitment was not fulfilled."""

    DEFERRED = "deferred"
    """The commitment has been deferred to a later time."""


@dataclass
class Commitment:
    """A personal commitment or obligation.

    Attributes:
        id: Stable identity for the commitment.
        title: Human-readable description of the commitment.
        status: Current status of the commitment.
        due_date: Optional date by which the commitment should be fulfilled.
        created_at: When the commitment was created.
        completed_at: When the commitment was completed (if applicable).
        linked_goal_title: Optional goal this commitment relates to.
        notes: Additional notes about the commitment.
    """

    id: str
    title: str
    status: CommitmentStatus = CommitmentStatus.ACTIVE
    due_date: date | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None
    linked_goal_title: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("Commitment.id must not be empty")
        if not self.title or not self.title.strip():
            raise ValueError("Commitment.title must not be empty")
        if not isinstance(self.status, CommitmentStatus):
            raise ValueError(
                f"Invalid status: {self.status!r}. "
                f"Allowed: {', '.join(s.value for s in CommitmentStatus)}"
            )
        if self.created_at is None:
            self.created_at = datetime.now()

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        from dataclasses import asdict

        raw = asdict(self)
        raw["status"] = self.status.value
        if self.created_at and hasattr(self.created_at, "isoformat"):
            raw["created_at"] = self.created_at.isoformat()
        if self.completed_at and hasattr(self.completed_at, "isoformat"):
            raw["completed_at"] = self.completed_at.isoformat()
        if self.due_date and hasattr(self.due_date, "isoformat"):
            raw["due_date"] = self.due_date.isoformat()
        return raw
