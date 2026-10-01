"""EvidenceType enum for Janus — Phase B (Evidence & Audit).

The 4-stage evidence distinction (Planned/Claimed/Verified/Outcome)
models the lifecycle of evidence in the Janus system. Each stage
represents a different level of confidence and verification.

Spec: ``docs/janus-agency-first-development-phase.md`` §8.1.
"""

from enum import StrEnum


class EvidenceType(StrEnum):
    """The 4-stage evidence distinction.

    Evidence progresses through these stages:
    - PLANNED: Evidence that is expected to be produced (a plan).
    - CLAIMED: Evidence that has been claimed to exist (unverified).
    - VERIFIED: Evidence that has been verified to exist.
    - OUTCOME: Evidence that represents the final outcome of work.
    """

    PLANNED = "planned"
    """Evidence that is expected to be produced (a plan)."""

    CLAIMED = "claimed"
    """Evidence that has been claimed to exist (unverified)."""

    VERIFIED = "verified"
    """Evidence that has been verified to exist."""

    OUTCOME = "outcome"
    """Evidence that represents the final outcome of work."""


#: Valid evidence type transitions.
#: planned → claimed, planned → verified, claimed → verified,
#: verified → outcome, claimed → outcome
EVIDENCE_TYPE_TRANSITIONS: dict[str, set[str]] = {
    "planned": {"claimed", "verified"},
    "claimed": {"verified", "outcome"},
    "verified": {"outcome"},
    "outcome": set(),
}


def is_valid_evidence_transition(from_type: str, to_type: str) -> bool:
    """Return True if the evidence type transition is valid."""
    return to_type in EVIDENCE_TYPE_TRANSITIONS.get(from_type, set())
