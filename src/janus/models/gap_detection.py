"""Gap detection model for Janus — Phase G (Self-Extending Skills).

A ``GapDetection`` represents a detected gap where a skill or tool
is needed but missing. This is the first stage of the self-extending
skills lifecycle.

Spec: ``docs/janus-agency-first-development-phase.md`` §13 Phase G.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class GapStatus(StrEnum):
    """Status of a gap detection."""

    DETECTED = "detected"
    """The gap has been detected but not yet addressed."""

    PROPOSED = "proposed"
    """A proposal has been made to address the gap."""

    GENERATING = "generating"
    """The capability is being generated."""

    TESTING = "testing"
    """The generated capability is being tested."""

    VERIFIED = "verified"
    """The generated capability has been verified."""

    APPROVED = "approved"
    """The generated capability has been approved."""

    INSTALLED = "installed"
    """The generated capability has been installed."""

    REJECTED = "rejected"
    """The gap was rejected and will not be addressed."""


@dataclass
class GapDetection:
    """A detected gap where a skill or tool is needed but missing.

    Attributes:
        id: Stable identity for the gap detection.
        description: Human-readable description of the gap.
        status: Current status of the gap detection.
        detected_at: When the gap was detected.
        context: Context in which the gap was detected.
        required_capability: Description of the capability needed.
        priority: Priority of the gap (1-5, 5 = highest).
        linked_task_title: Optional task that revealed the gap.
        linked_goal_title: Optional goal that revealed the gap.
        notes: Additional notes about the gap.
    """

    id: str
    description: str
    status: GapStatus = GapStatus.DETECTED
    detected_at: datetime | None = None
    context: str = ""
    required_capability: str = ""
    priority: int = 3  # 1-5
    linked_task_title: str = ""
    linked_goal_title: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("GapDetection.id must not be empty")
        if not self.description or not self.description.strip():
            raise ValueError("GapDetection.description must not be empty")
        if not isinstance(self.status, GapStatus):
            raise ValueError(
                f"Invalid status: {self.status!r}. "
                f"Allowed: {', '.join(s.value for s in GapStatus)}"
            )
        if self.priority not in (1, 2, 3, 4, 5):
            raise ValueError(
                f"Invalid priority: {self.priority!r}. "
                f"Allowed: 1, 2, 3, 4, 5"
            )
        if self.detected_at is None:
            self.detected_at = datetime.now()

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        from dataclasses import asdict

        raw = asdict(self)
        raw["status"] = self.status.value
        if self.detected_at and hasattr(self.detected_at, "isoformat"):
            raw["detected_at"] = self.detected_at.isoformat()
        return raw
