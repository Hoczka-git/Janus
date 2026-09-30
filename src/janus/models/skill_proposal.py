"""Skill proposal model for Janus — Phase G (Self-Extending Skills).

A ``SkillProposal`` represents a proposal to create a new capability
to address a detected gap. This is the second stage of the
self-extending skills lifecycle.

Spec: ``docs/janus-agency-first-development-phase.md`` §13 Phase G.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ProposalStatus(StrEnum):
    """Status of a skill proposal."""

    PROPOSED = "proposed"
    """The proposal has been made but not yet approved."""

    APPROVED = "approved"
    """The proposal has been approved."""

    REJECTED = "rejected"
    """The proposal has been rejected."""

    GENERATING = "generating"
    """The capability is being generated."""

    COMPLETED = "completed"
    """The capability has been generated and installed."""


@dataclass
class SkillProposal:
    """A proposal to create a new capability.

    Attributes:
        id: Stable identity for the proposal.
        title: Human-readable title of the proposal.
        description: Detailed description of the proposed capability.
        status: Current status of the proposal.
        proposed_at: When the proposal was made.
        approved_at: When the proposal was approved (if applicable).
        gap_id: The gap detection this proposal addresses.
        proposed_code: The proposed code for the capability.
        proposed_tests: The proposed tests for the capability.
        estimated_effort: Estimated effort to implement (low, medium, high).
        notes: Additional notes about the proposal.
    """

    id: str
    title: str
    description: str = ""
    status: ProposalStatus = ProposalStatus.PROPOSED
    proposed_at: datetime | None = None
    approved_at: datetime | None = None
    gap_id: str = ""
    proposed_code: str = ""
    proposed_tests: str = ""
    estimated_effort: str = "medium"  # low | medium | high
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("SkillProposal.id must not be empty")
        if not self.title or not self.title.strip():
            raise ValueError("SkillProposal.title must not be empty")
        if not isinstance(self.status, ProposalStatus):
            raise ValueError(
                f"Invalid status: {self.status!r}. "
                f"Allowed: {', '.join(s.value for s in ProposalStatus)}"
            )
        if self.estimated_effort not in ("low", "medium", "high"):
            raise ValueError(
                f"Invalid estimated_effort: {self.estimated_effort!r}. "
                f"Allowed: low, medium, high"
            )
        if self.proposed_at is None:
            self.proposed_at = datetime.now()

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        from dataclasses import asdict

        raw = asdict(self)
        raw["status"] = self.status.value
        if self.proposed_at and hasattr(self.proposed_at, "isoformat"):
            raw["proposed_at"] = self.proposed_at.isoformat()
        if self.approved_at and hasattr(self.approved_at, "isoformat"):
            raw["approved_at"] = self.approved_at.isoformat()
        return raw
