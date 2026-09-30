"""Constraint model for Janus — Phase C (Personal State).

A ``Constraint`` represents a limitation or boundary that affects the
user's ability to execute tasks or achieve goals. Constraints are
tracked as part of the PersonalState aggregate to provide a complete
view of the user's current state.

Spec: ``docs/janus-agency-first-development-phase.md`` §13 Phase C.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class ConstraintType(StrEnum):
    """Type of constraint."""

    TIME = "time"
    """A time-based constraint (e.g., limited hours available)."""

    RESOURCE = "resource"
    """A resource-based constraint (e.g., limited budget)."""

    ENERGY = "energy"
    """An energy-based constraint (e.g., limited stamina)."""

    KNOWLEDGE = "knowledge"
    """A knowledge-based constraint (e.g., missing skills)."""

    EXTERNAL = "external"
    """An external constraint (e.g., dependency on others)."""

    OTHER = "other"
    """Any other type of constraint."""


@dataclass
class Constraint:
    """A limitation or boundary that affects execution.

    Attributes:
        id: Stable identity for the constraint.
        title: Human-readable description of the constraint.
        constraint_type: Type of constraint.
        severity: How severe the constraint is (low, medium, high).
        active: Whether the constraint is currently active.
        created_at: When the constraint was created.
        expires_at: When the constraint expires (if applicable).
        linked_goal_title: Optional goal this constraint relates to.
        notes: Additional notes about the constraint.
    """

    id: str
    title: str
    constraint_type: ConstraintType = ConstraintType.OTHER
    severity: str = "medium"  # low | medium | high
    active: bool = True
    created_at: datetime | None = None
    expires_at: date | None = None
    linked_goal_title: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("Constraint.id must not be empty")
        if not self.title or not self.title.strip():
            raise ValueError("Constraint.title must not be empty")
        if not isinstance(self.constraint_type, ConstraintType):
            raise ValueError(
                f"Invalid constraint_type: {self.constraint_type!r}. "
                f"Allowed: {', '.join(t.value for t in ConstraintType)}"
            )
        if self.severity not in ("low", "medium", "high"):
            raise ValueError(
                f"Invalid severity: {self.severity!r}. "
                f"Allowed: low, medium, high"
            )
        if self.created_at is None:
            self.created_at = datetime.now()

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        from dataclasses import asdict

        raw = asdict(self)
        raw["constraint_type"] = self.constraint_type.value
        if self.created_at and hasattr(self.created_at, "isoformat"):
            raw["created_at"] = self.created_at.isoformat()
        if self.expires_at and hasattr(self.expires_at, "isoformat"):
            raw["expires_at"] = self.expires_at.isoformat()
        return raw
