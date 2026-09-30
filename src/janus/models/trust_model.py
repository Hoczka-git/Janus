"""Trust model for generated capabilities — Phase G (Self-Extending Skills).

A ``TrustModel`` defines the trust levels and rules for generated
capabilities. Generated capabilities start untrusted and must earn
trust through verification and approval.

Spec: ``docs/janus-agency-first-development-phase.md`` §13 Phase G.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class TrustLevel(StrEnum):
    """Trust level for a generated capability."""

    UNTRUSTED = "untrusted"
    """The capability is untrusted and cannot be used."""

    LOW = "low"
    """The capability has low trust and can be used with supervision."""

    MEDIUM = "medium"
    """The capability has medium trust and can be used with caution."""

    HIGH = "high"
    """The capability has high trust and can be used freely."""


#: Valid trust level transitions.
#: untrusted → low, low → medium, medium → high
TRUST_LEVEL_TRANSITIONS: dict[str, set[str]] = {
    "untrusted": {"low"},
    "low": {"medium"},
    "medium": {"high"},
    "high": set(),
}


def is_valid_trust_transition(from_level: str, to_level: str) -> bool:
    """Return True if the trust level transition is valid."""
    return to_level in TRUST_LEVEL_TRANSITIONS.get(from_level, set())


@dataclass
class TrustModel:
    """Trust model for generated capabilities.

    Attributes:
        id: Stable identity for the trust model.
        name: Name of the trust model.
        description: Description of the trust model.
        rules: List of rules for the trust model.
        created_at: When the trust model was created.
        updated_at: When the trust model was last updated.
        active: Whether the trust model is currently active.
    """

    id: str
    name: str
    description: str = ""
    rules: list[dict] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    active: bool = True

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("TrustModel.id must not be empty")
        if not self.name or not self.name.strip():
            raise ValueError("TrustModel.name must not be empty")
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()
        if self.rules is None:
            self.rules = []

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        from dataclasses import asdict

        raw = asdict(self)
        if self.created_at and hasattr(self.created_at, "isoformat"):
            raw["created_at"] = self.created_at.isoformat()
        if self.updated_at and hasattr(self.updated_at, "isoformat"):
            raw["updated_at"] = self.updated_at.isoformat()
        return raw
