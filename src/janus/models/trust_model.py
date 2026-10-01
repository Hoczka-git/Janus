"""Trust model for generated capabilities (Phase G, G9).

Generated capabilities start UNTRUSTED and must earn trust through
verification and explicit approval before installation. The trust model
defines the levels and the conditions for advancing between them.

Design reference: docs/janus-agency-first-development-phase.md §Phase G
"""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime


class TrustLevel(Enum):
    """Trust levels for generated capabilities.

    UNTRUSTED  — newly generated, no verification performed.
    SANDBOXED  — ran in sandbox without errors.
    VERIFIED    — passed verification against specification.
    APPROVED    — human or trust-model approved for installation.
    TRUSTED     — installed and operational; trust earned through use.
    REVOKED     — trust revoked (e.g. after failure or policy change).
    """

    UNTRUSTED = "untrusted"
    SANDBOXED = "sandboxed"
    VERIFIED = "verified"
    APPROVED = "approved"
    TRUSTED = "trusted"
    REVOKED = "revoked"

    @property
    def is_operational(self) -> bool:
        """True when the capability can be used in production."""
        return self in (TrustLevel.APPROVED, TrustLevel.TRUSTED)

    @property
    def is_terminal(self) -> bool:
        return self is TrustLevel.REVOKED


#: Valid trust-level transitions (including self-transitions for re-evaluation).
TRUST_TRANSITIONS: dict[TrustLevel, frozenset[TrustLevel]] = {
    TrustLevel.UNTRUSTED: frozenset({TrustLevel.UNTRUSTED, TrustLevel.SANDBOXED, TrustLevel.REVOKED}),
    TrustLevel.SANDBOXED: frozenset({TrustLevel.SANDBOXED, TrustLevel.VERIFIED, TrustLevel.REVOKED}),
    TrustLevel.VERIFIED: frozenset({TrustLevel.VERIFIED, TrustLevel.APPROVED, TrustLevel.REVOKED}),
    TrustLevel.APPROVED: frozenset({TrustLevel.APPROVED, TrustLevel.TRUSTED, TrustLevel.REVOKED}),
    TrustLevel.TRUSTED: frozenset({TrustLevel.TRUSTED, TrustLevel.REVOKED}),
    TrustLevel.REVOKED: frozenset({TrustLevel.REVOKED}),  # Terminal (self only)
}


def is_valid_trust_transition(from_level: TrustLevel, to_level: TrustLevel) -> bool:
    """Check if a trust-level transition is valid."""
    return to_level in TRUST_TRANSITIONS.get(from_level, frozenset())


@dataclass
class TrustRecord:
    """Immutable record of a trust-level change.

    Attributes:
        capability_name: The capability this record applies to.
        from_level: Previous trust level.
        to_level: New trust level.
        reason: Why the trust level changed.
        approver: Who or what authorized the change.
        timestamp: When the change occurred.
        evidence: Supporting evidence (e.g. test results, verification output).
    """

    capability_name: str
    from_level: TrustLevel
    to_level: TrustLevel
    reason: str = ""
    approver: str = ""
    timestamp: datetime | None = None
    evidence: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now().astimezone()
        if not is_valid_trust_transition(self.from_level, self.to_level):
            raise ValueError(
                f"Invalid trust transition: {self.from_level.value} → {self.to_level.value}"
            )

    def to_dict(self) -> dict:
        return {
            "capability_name": self.capability_name,
            "from_level": self.from_level.value,
            "to_level": self.to_level.value,
            "reason": self.reason,
            "approver": self.approver,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "evidence": dict(self.evidence),
        }
