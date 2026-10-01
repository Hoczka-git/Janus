"""Resource model for Janus — Phase C (Personal State).

A ``Resource`` represents a resource that the user has available to
them. Resources are tracked as part of the PersonalState aggregate to
provide a complete view of the user's current state.

Spec: ``docs/janus-agency-first-development-phase.md`` §7.2/§13 Phase C.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class ResourceType(StrEnum):
    """Type of resource."""

    TIME = "time"
    """Time available for work."""

    ENERGY = "energy"
    """Energy/stamina available."""

    MONEY = "money"
    """Financial resources."""

    KNOWLEDGE = "knowledge"
    """Knowledge and skills."""

    TOOLS = "tools"
    """Tools and equipment."""

    NETWORK = "network"
    """Social/professional network."""

    OTHER = "other"
    """Any other type of resource."""


@dataclass
class Resource:
    """A resource available to the user.

    Attributes:
        id: Stable identity for the resource.
        title: Human-readable description of the resource.
        resource_type: Type of resource.
        capacity: Total capacity of the resource.
        used: Amount of the resource currently used.
        unit: Unit of measurement (e.g., "hours", "PLN", "kWh").
        available_from: When the resource becomes available.
        available_until: When the resource is no longer available.
        linked_goal_title: Optional goal this resource relates to.
        notes: Additional notes about the resource.
    """

    id: str
    title: str
    resource_type: ResourceType = ResourceType.OTHER
    capacity: float = 0.0
    used: float = 0.0
    unit: str = ""
    available_from: date | None = None
    available_until: date | None = None
    linked_goal_title: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("Resource.id must not be empty")
        if not self.title or not self.title.strip():
            raise ValueError("Resource.title must not be empty")
        if not isinstance(self.resource_type, ResourceType):
            raise ValueError(
                f"Invalid resource_type: {self.resource_type!r}. "
                f"Allowed: {', '.join(t.value for t in ResourceType)}"
            )
        if self.capacity < 0:
            raise ValueError("Resource.capacity must be non-negative")
        if self.used < 0:
            raise ValueError("Resource.used must be non-negative")
        if self.used > self.capacity:
            raise ValueError("Resource.used must not exceed capacity")

    @property
    def available(self) -> float:
        """Return the available amount of the resource."""
        return self.capacity - self.used

    @property
    def utilization(self) -> float:
        """Return the utilization ratio (0.0 to 1.0)."""
        if self.capacity == 0:
            return 0.0
        return self.used / self.capacity

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        from dataclasses import asdict

        raw = asdict(self)
        raw["resource_type"] = self.resource_type.value
        raw["available"] = self.available
        raw["utilization"] = self.utilization
        if self.available_from and hasattr(self.available_from, "isoformat"):
            raw["available_from"] = self.available_from.isoformat()
        if self.available_until and hasattr(self.available_until, "isoformat"):
            raw["available_until"] = self.available_until.isoformat()
        return raw
