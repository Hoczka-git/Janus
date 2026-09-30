"""Generated capability model for Janus — Phase G (Self-Extending Skills).

A ``GeneratedCapability`` represents a capability that has been
generated to address a detected gap. This is the third stage of the
self-extending skills lifecycle.

Spec: ``docs/janus-agency-first-development-phase.md`` §13 Phase G.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class CapabilityStatus(StrEnum):
    """Status of a generated capability."""

    GENERATING = "generating"
    """The capability is being generated."""

    GENERATED = "generated"
    """The capability has been generated but not yet tested."""

    TESTING = "testing"
    """The capability is being tested."""

    TESTED = "tested"
    """The capability has been tested but not yet verified."""

    VERIFIED = "verified"
    """The capability has been verified."""

    APPROVED = "approved"
    """The capability has been approved."""

    INSTALLED = "installed"
    """The capability has been installed."""

    REJECTED = "rejected"
    """The capability has been rejected."""


@dataclass
class GeneratedCapability:
    """A capability that has been generated.

    Attributes:
        id: Stable identity for the capability.
        name: Name of the capability.
        description: Description of the capability.
        status: Current status of the capability.
        created_at: When the capability was created.
        updated_at: When the capability was last updated.
        proposal_id: The proposal this capability implements.
        code: The generated code for the capability.
        tests: The generated tests for the capability.
        sandbox_results: Results from sandbox execution.
        verification_results: Results from verification.
        trust_level: Trust level of the capability (untrusted, low, medium, high).
        notes: Additional notes about the capability.
    """

    id: str
    name: str
    description: str = ""
    status: CapabilityStatus = CapabilityStatus.GENERATING
    created_at: datetime | None = None
    updated_at: datetime | None = None
    proposal_id: str = ""
    code: str = ""
    tests: str = ""
    sandbox_results: dict = field(default_factory=dict)
    verification_results: dict = field(default_factory=dict)
    trust_level: str = "untrusted"  # untrusted | low | medium | high
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("GeneratedCapability.id must not be empty")
        if not self.name or not self.name.strip():
            raise ValueError("GeneratedCapability.name must not be empty")
        if not isinstance(self.status, CapabilityStatus):
            raise ValueError(
                f"Invalid status: {self.status!r}. "
                f"Allowed: {', '.join(s.value for s in CapabilityStatus)}"
            )
        if self.trust_level not in ("untrusted", "low", "medium", "high"):
            raise ValueError(
                f"Invalid trust_level: {self.trust_level!r}. "
                f"Allowed: untrusted, low, medium, high"
            )
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()
        if self.sandbox_results is None:
            self.sandbox_results = {}
        if self.verification_results is None:
            self.verification_results = {}

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        from dataclasses import asdict

        raw = asdict(self)
        raw["status"] = self.status.value
        if self.created_at and hasattr(self.created_at, "isoformat"):
            raw["created_at"] = self.created_at.isoformat()
        if self.updated_at and hasattr(self.updated_at, "isoformat"):
            raw["updated_at"] = self.updated_at.isoformat()
        return raw
