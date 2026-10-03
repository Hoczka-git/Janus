"""Human Approval and Policy Check contract for the Action Proposal pipeline.

This module defines the contract layer between proposal generation and
execution. It provides:

- ``ApprovalDecision`` — the human decision on a proposal (APPROVE, REJECT, EDIT).
- ``ApprovalRecord`` — a persistent record of an approval decision, including
  approver identity, timestamp, and the resulting proposal (for EDIT).
- ``PolicyCheckResult`` — the outcome of a policy check against proposal content.
- ``ApprovalGate`` — protocol for checking whether a proposal has a valid approval.
- ``PolicyCheck`` — protocol for checking whether proposal content passes policy.
- ``ApprovalPolicyContract`` — orchestrates the approval gate and policy check.

The contract is pure logic: it performs no I/O and does not mutate state.
Persistence and execution are handled by downstream layers.

Pipeline::

    ActionProposal → ApprovalGate → PolicyCheck → Execution

Design reference: docs/design/action_proposal_engine_v1.md §6.2
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from janus.proposal.models import ActionProposal


# ── Approval decision ────────────────────────────────────────────────────────


class ApprovalDecision(StrEnum):
    """Human decision on an action proposal.

    Members:
        APPROVE — the proposal may proceed to policy check and execution.
        REJECT  — the proposal is blocked; it cannot execute.
        EDIT    — the proposal is modified; the resulting proposal must be
            explicitly represented (the original is not mutated).
    """

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    EDIT = "EDIT"


# ── Approval record ──────────────────────────────────────────────────────────


@dataclass
class ApprovalRecord:
    """A persistent record of a human approval decision.

    Attributes:
        proposal_id: The ID of the proposal this decision applies to.
        decision: The human decision (APPROVE, REJECT, EDIT).
        approver: Identity of the human who made the decision.
        decided_at: When the decision was made.
        reason: Optional human-readable justification.
        resulting_proposal: For EDIT decisions, the modified proposal.
            For APPROVE/REJECT, this is None (the original is unchanged).
        source: Origin of the approval (e.g., "cli", "telegram", "api").
    """

    proposal_id: str
    decision: ApprovalDecision
    approver: str
    decided_at: datetime = field(default_factory=lambda: datetime.now().astimezone())
    reason: str = ""
    resulting_proposal: ActionProposal | None = None
    source: str = ""

    def __post_init__(self) -> None:
        if not self.proposal_id or not self.proposal_id.strip():
            raise ValueError("ApprovalRecord.proposal_id must not be empty")
        if not self.approver or not self.approver.strip():
            raise ValueError("ApprovalRecord.approver must not be empty")
        if self.decision == ApprovalDecision.EDIT and self.resulting_proposal is None:
            raise ValueError(
                "ApprovalRecord with EDIT decision must have a resulting_proposal"
            )

    @property
    def is_approved(self) -> bool:
        """True if the decision is APPROVE."""
        return self.decision == ApprovalDecision.APPROVE

    @property
    def is_rejected(self) -> bool:
        """True if the decision is REJECT."""
        return self.decision == ApprovalDecision.REJECT

    @property
    def is_edit(self) -> bool:
        """True if the decision is EDIT."""
        return self.decision == ApprovalDecision.EDIT

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict."""
        return {
            "proposal_id": self.proposal_id,
            "decision": self.decision.value,
            "approver": self.approver,
            "decided_at": self.decided_at.isoformat(),
            "reason": self.reason,
            "resulting_proposal": (
                self.resulting_proposal.to_dict() if self.resulting_proposal else None
            ),
            "source": self.source,
        }


# ── Policy check result ──────────────────────────────────────────────────────


@dataclass
class PolicyCheckResult:
    """The outcome of a policy check against proposal content.

    Attributes:
        allowed: True if the proposal passes the policy check.
        reason: Human-readable explanation of the decision.
        timestamp: When the check was performed.
        rule_id: Optional identifier of the policy rule that was evaluated.
    """

    allowed: bool
    reason: str
    timestamp: datetime = field(default_factory=lambda: datetime.now().astimezone())
    rule_id: str = ""

    def __post_init__(self) -> None:
        if not self.reason or not self.reason.strip():
            raise ValueError("PolicyCheckResult.reason must not be empty")

    @property
    def denied(self) -> bool:
        """True if the policy check denied the proposal."""
        return not self.allowed

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict."""
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
            "rule_id": self.rule_id,
        }


# ── Approval gate protocol ───────────────────────────────────────────────────


@runtime_checkable
class ApprovalGate(Protocol):
    """Protocol for checking whether a proposal has a valid human approval.

    Implementations must verify:
    - The proposal has an associated ApprovalRecord.
    - The decision is APPROVE.
    - The approver identity is present.
    - The timestamp is present.

    The gate does NOT check proposal content — that is the PolicyCheck's job.
    """

    def check(self, proposal: ActionProposal) -> ApprovalRecord | None:
        """Check if the proposal has a valid approval.

        Args:
            proposal: The proposal to check.

        Returns:
            The ApprovalRecord if the proposal is approved, None otherwise.
        """
        ...


# ── Policy check protocol ────────────────────────────────────────────────────


@runtime_checkable
class PolicyCheck(Protocol):
    """Protocol for checking whether proposal content passes policy.

    Implementations must verify:
    - The proposal exists and is structurally valid.
    - The action type is supported.
    - Required parameters are present.
    - The target exists where required.

    The policy check does NOT verify approval — that is the ApprovalGate's job.
    """

    def check(self, proposal: ActionProposal) -> PolicyCheckResult:
        """Check if the proposal content passes policy.

        Args:
            proposal: The proposal to check.

        Returns:
            A PolicyCheckResult indicating whether the proposal is allowed.
        """
        ...


class ApprovalPolicyCheck:
    """Concrete implementation of the PolicyCheck protocol.

    Evaluates an ActionProposal against basic policy rules:
    - The proposal must have a non-empty action type.
    - The proposal must have a non-empty target.

    This is a pure, deterministic function of the proposal content.
    No I/O, no side effects.
    """

    def check(self, proposal: ActionProposal) -> PolicyCheckResult:
        """Check if the proposal content passes policy.

        Args:
            proposal: The proposal to check.

        Returns:
            A PolicyCheckResult indicating whether the proposal is allowed.
        """
        if proposal.action_type is None or not str(proposal.action_type).strip():
            return PolicyCheckResult(
                allowed=False,
                reason="Action type is empty or invalid",
                rule_id="action_type_required",
            )

        if proposal.target_id is None or not proposal.target_id.strip():
            return PolicyCheckResult(
                allowed=False,
                reason="Target is empty or missing",
                rule_id="target_required",
            )

        return PolicyCheckResult(
            allowed=True,
            reason="Proposal passes basic policy check",
            rule_id="basic_policy",
        )


# ── Approval + Policy contract ───────────────────────────────────────────────


class ApprovalPolicyContract:
    """Orchestrates the approval gate and policy check for a proposal.

    This is the contract layer that downstream execution code uses to
    determine whether a proposal is ready for execution.

    The contract enforces the invariant:
        No proposal may execute without passing BOTH the approval gate
        AND the policy check.

    Usage::

        contract = ApprovalPolicyContract(approval_gate, policy_check)
        result = contract.evaluate(proposal)
        if result.approved and result.policy_allowed:
            # safe to execute
            ...

    Attributes:
        approval_gate: The gate that checks for valid human approval.
        policy_check: The check that validates proposal content.
    """

    def __init__(
        self,
        approval_gate: ApprovalGate,
        policy_check: PolicyCheck,
    ) -> None:
        self._approval_gate = approval_gate
        self._policy_check = policy_check

    @property
    def approval_gate(self) -> ApprovalGate:
        """The approval gate used by this contract."""
        return self._approval_gate

    @property
    def policy_check(self) -> PolicyCheck:
        """The policy check used by this contract."""
        return self._policy_check

    def evaluate(self, proposal: ActionProposal) -> ContractEvaluation:
        """Evaluate a proposal against both the approval gate and policy check.

        The approval gate is checked first. If the proposal is not approved,
        the policy check is skipped (short-circuit).

        Args:
            proposal: The proposal to evaluate.

        Returns:
            A ContractEvaluation with the full result.
        """
        approval_record = self._approval_gate.check(proposal)

        if approval_record is None:
            return ContractEvaluation(
                proposal=proposal,
                approved=False,
                approval_record=None,
                policy_result=None,
                ready=False,
            )

        policy_result = self._policy_check.check(proposal)

        return ContractEvaluation(
            proposal=proposal,
            approved=True,
            approval_record=approval_record,
            policy_result=policy_result,
            ready=policy_result.allowed,
        )


@dataclass
class ContractEvaluation:
    """The full result of evaluating a proposal through the contract.

    Attributes:
        proposal: The proposal that was evaluated.
        approved: True if the approval gate passed.
        approval_record: The ApprovalRecord if approved, None otherwise.
        policy_result: The PolicyCheckResult if the policy check was run,
            None if the approval gate short-circuited.
        ready: True if the proposal is ready for execution (both gates passed).
    """

    proposal: ActionProposal
    approved: bool
    approval_record: ApprovalRecord | None
    policy_result: PolicyCheckResult | None
    ready: bool = False

    def __post_init__(self) -> None:
        # ready can only be True if both gates passed
        if self.ready and (not self.approved or self.policy_result is None):
            raise ValueError(
                "ContractEvaluation.ready=True requires approved=True and policy_result"
            )
        if self.ready and self.policy_result and not self.policy_result.allowed:
            raise ValueError(
                "ContractEvaluation.ready=True requires policy_result.allowed=True"
            )

    @property
    def blocked_reason(self) -> str | None:
        """Human-readable reason why the proposal is not ready, or None if ready."""
        if self.ready:
            return None
        if not self.approved:
            return "Proposal has no valid human approval"
        if self.policy_result and not self.policy_result.allowed:
            return f"Policy check denied: {self.policy_result.reason}"
        return "Proposal is not ready for execution"

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict."""
        return {
            "proposal_id": self.proposal.proposal_id,
            "approved": self.approved,
            "approval_record": (
                self.approval_record.to_dict() if self.approval_record else None
            ),
            "policy_result": (
                self.policy_result.to_dict() if self.policy_result else None
            ),
            "ready": self.ready,
            "blocked_reason": self.blocked_reason,
        }
