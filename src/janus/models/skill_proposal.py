"""Skill proposal model for Phase G — Self-Extending Skills.

A :class:`SkillProposal` tracks a generated capability through its full
lifecycle: gap detection → proposal → generation → tests → sandbox →
verification → approval → install.

Generated capabilities start UNTRUSTED and must earn trust through
verification and explicit approval before installation.

Design reference: docs/janus-agency-first-development-phase.md §Phase G
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SkillStage(Enum):
    """Lifecycle stages for a self-extended skill.

    The pipeline is linear; each stage must complete before the next
    begins. REJECTED is a terminal stage that can be reached from
    any non-terminal stage.
    """

    DETECTED = "detected"           # G1: gap detected
    PROPOSED = "proposed"           # G2: capability proposed
    GENERATED = "generated"         # G3: code generated
    TESTED = "tested"               # G4: tests generated and passing
    SANDBOXED = "sandboxed"         # G5: ran in sandbox
    VERIFIED = "verified"           # G6: meets specification
    APPROVED = "approved"           # G7: human/trust-model approved
    INSTALLED = "installed"         # G8: installed into runtime
    REJECTED = "rejected"           # terminal: rejected at any stage

    @property
    def is_terminal(self) -> bool:
        return self is SkillStage.REJECTED

    @property
    def is_operational(self) -> bool:
        """True when the capability is installed and usable."""
        return self is SkillStage.INSTALLED


#: Valid stage transitions. Each stage maps to the set of stages it can
#: advance to. REJECTED is reachable from any non-terminal stage.
STAGE_TRANSITIONS: dict[SkillStage, frozenset[SkillStage]] = {
    SkillStage.DETECTED: frozenset({SkillStage.PROPOSED, SkillStage.REJECTED}),
    SkillStage.PROPOSED: frozenset({SkillStage.GENERATED, SkillStage.REJECTED}),
    SkillStage.GENERATED: frozenset({SkillStage.TESTED, SkillStage.REJECTED}),
    SkillStage.TESTED: frozenset({SkillStage.SANDBOXED, SkillStage.REJECTED}),
    SkillStage.SANDBOXED: frozenset({SkillStage.VERIFIED, SkillStage.REJECTED}),
    SkillStage.VERIFIED: frozenset({SkillStage.APPROVED, SkillStage.REJECTED}),
    SkillStage.APPROVED: frozenset({SkillStage.INSTALLED, SkillStage.REJECTED}),
    SkillStage.INSTALLED: frozenset(),  # Terminal
    SkillStage.REJECTED: frozenset(),   # Terminal
}


def is_valid_transition(from_stage: SkillStage, to_stage: SkillStage) -> bool:
    """Check if a stage transition is valid."""
    return to_stage in STAGE_TRANSITIONS.get(from_stage, frozenset())


class SkillProposalError(RuntimeError):
    """Raised when a skill proposal operation is invalid."""


@dataclass
class SkillProposal:
    """A capability proposal tracked through the self-extending skills pipeline.

    Attributes:
        proposal_id: Stable identity (``sp-<8-hex>``).
        capability_name: Short name for the capability (e.g. "fetch-weather").
        description: What the capability does.
        reason: Why this capability is needed (gap analysis result).
        required_capabilities: Capability strings this proposal addresses.
        stage: Current lifecycle stage.
        generated_code: Python source code for the capability (after G3).
        test_code: Python test source code (after G4).
        sandbox_result: Sandbox execution result summary (after G5).
        verification_result: Verification result summary (after G6).
        trust_level: Trust level assigned after approval (G7).
        approver: Who approved the proposal (G7).
        install_path: Filesystem path where installed (G8).
        rejection_reason: Why rejected (if rejected).
        created_at: When the proposal was created.
        updated_at: When the proposal last changed stage.
        metadata: Additional structured data.
    """

    proposal_id: str = ""
    capability_name: str = ""
    description: str = ""
    reason: str = ""
    required_capabilities: list[str] = field(default_factory=list)
    stage: SkillStage = SkillStage.DETECTED
    generated_code: str = ""
    test_code: str = ""
    sandbox_result: str = ""
    verification_result: str = ""
    trust_level: str = "untrusted"
    approver: str = ""
    install_path: str = ""
    rejection_reason: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.proposal_id and not self.proposal_id.strip():
            raise ValueError("SkillProposal.proposal_id must not be empty")
        if self.capability_name and not self.capability_name.strip():
            raise ValueError("SkillProposal.capability_name must not be empty")
        if self.created_at is None:
            self.created_at = datetime.now().astimezone()
        if self.updated_at is None:
            self.updated_at = self.created_at

    @property
    def content_hash(self) -> str:
        """SHA-256 fingerprint of the generated code + tests.

        Used for audit integrity and change detection.
        """
        payload = f"{self.capability_name}|{self.generated_code}|{self.test_code}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def is_terminal(self) -> bool:
        return self.stage.is_terminal

    @property
    def is_operational(self) -> bool:
        return self.stage.is_operational

    def can_transition_to(self, target: SkillStage) -> bool:
        """Check if transitioning to *target* is valid from the current stage."""
        return is_valid_transition(self.stage, target)

    def transition_to(self, target: SkillStage) -> None:
        """Transition to *target* stage in-place.

        Raises:
            SkillProposalError: if the transition is invalid.
        """
        if not self.can_transition_to(target):
            raise SkillProposalError(
                f"Cannot transition from {self.stage.value!r} to {target.value!r}"
            )
        self.stage = target
        self.updated_at = datetime.now().astimezone()

    def reject(self, reason: str) -> None:
        """Reject the proposal with a reason."""
        self.rejection_reason = reason
        self.transition_to(SkillStage.REJECTED)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "proposal_id": self.proposal_id,
            "capability_name": self.capability_name,
            "description": self.description,
            "reason": self.reason,
            "required_capabilities": list(self.required_capabilities),
            "stage": self.stage.value,
            "generated_code": self.generated_code,
            "test_code": self.test_code,
            "sandbox_result": self.sandbox_result,
            "verification_result": self.verification_result,
            "trust_level": self.trust_level,
            "approver": self.approver,
            "install_path": self.install_path,
            "rejection_reason": self.rejection_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillProposal:
        """Deserialize from a plain dict."""
        return cls(
            proposal_id=data.get("proposal_id", ""),
            capability_name=data.get("capability_name", ""),
            description=data.get("description", ""),
            reason=data.get("reason", ""),
            required_capabilities=data.get("required_capabilities") or [],
            stage=SkillStage(data.get("stage", "detected")),
            generated_code=data.get("generated_code", ""),
            test_code=data.get("test_code", ""),
            sandbox_result=data.get("sandbox_result", ""),
            verification_result=data.get("verification_result", ""),
            trust_level=data.get("trust_level", "untrusted"),
            approver=data.get("approver", ""),
            install_path=data.get("install_path", ""),
            rejection_reason=data.get("rejection_reason", ""),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
            metadata=data.get("metadata") or {},
        )
