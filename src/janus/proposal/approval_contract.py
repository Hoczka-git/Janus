"""Approval contract layer — interfaces and schema for the approval gate and policy check.

This module defines the contract-layer interfaces that bridge the ActionProposal
model with the approval workflow and policy enforcement. It specifies data types
and method signatures only — no implementation logic.

Contract summary
----------------
1. **ApprovalGate** — the human-decision layer. Records who approved/rejected
   a proposal and when. Consumes an ActionProposal's ``proposal_id`` and
   returns an :class:`ApprovalStatus`.

2. **PolicyCheck** — the automated rule-evaluation layer. Accepts an
   :class:`ActionProposal` and returns a :class:`PolicyCheckResult` (pass/fail
   with optional reason). No human involvement.

3. **Boundary** — the policy check runs first and may short-circuit (fail).
   If the policy check fails, the approval gate is invoked to obtain a
   human decision. The approval gate never overrides a failed policy check;
   it only resolves the failure into APPROVED or REJECTED.

Integration with ActionProposal
------------------------------
The :class:`ActionProposal` model (``models.py``) is the shared data structure
that flows through both interfaces:

- ``ActionProposal.proposal_id`` — the key used by :class:`ApprovalGate` to
  look up and record decisions.
- ``ActionProposal.status`` — the :class:`ProposalStatus` field that reflects
  the outcome of the approval workflow (PROPOSED → APPROVED/REJECTED).
- ``ActionProposal`` is the input to :class:`PolicyCheck.check`.

Design reference: docs/design/policy_approval_p1_design.md §3, §5
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from janus.proposal.models import ActionProposal


# ── Policy check result ──────────────────────────────────────────────────────


@dataclass
class PolicyCheckResult:
    """Result of a policy check evaluation.

    This is the return type for :class:`PolicyCheck.check`. It provides a
    simple pass/fail verdict with an optional human-readable reason.

    Attributes:
        passed: True if the action is allowed without human approval,
            False if the action is denied or requires approval.
        reason: Optional human-readable explanation for the verdict.
            May be None when the check passes without additional context.
    """

    passed: bool
    reason: str | None = None


# ── Approval status ──────────────────────────────────────────────────────────


class ApprovalStatus(StrEnum):
    """Status of an approval decision for a proposal.

    This is distinct from :class:`ProposalStatus` (which tracks the overall
    proposal lifecycle). ``ApprovalStatus`` represents the human-decision
    outcome within the approval gate.

    Members:
        PENDING  — no human decision recorded yet.
        APPROVED — human approved the proposal.
        REJECTED — human rejected the proposal.
        DEFERRED — human deferred (P1: cancel for now).
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"


# ── Approval decision record ─────────────────────────────────────────────────


@dataclass
class ApprovalDecision:
    """A recorded approval decision with approver identity and timestamp.

    Produced by the approval gate when a human responds to an ASK verdict.
    At P1 this is ephemeral (returned to caller, logged). Persistent recording
    is P2.

    Attributes:
        proposal_id: The ActionProposal this decision applies to.
        status: The approval outcome (APPROVED, REJECTED, or DEFERRED).
        approver: Identity of the approver (e.g., ``"user"``, ``"admin"``).
        decided_at: When the decision was made.
        rationale: Optional human-readable reason for the decision.
    """

    proposal_id: str
    status: ApprovalStatus
    approver: str
    decided_at: datetime = field(default_factory=datetime.now)
    rationale: str = ""


# ── Approval gate interface ─────────────────────────────────────────────────


@runtime_checkable
class ApprovalGate(Protocol):
    """Interface for the approval gate — the human-decision layer.

    The approval gate is responsible for:
    - Looking up the current approval status of a proposal.
    - Recording human approval decisions (who, when, what outcome).
    - Retrieving past decisions for audit or display.

    The approval gate does NOT evaluate policy rules. It only records and
    returns human decisions. Policy evaluation is the responsibility of
    :class:`PolicyCheck`.

    Implementations must be stateless with respect to policy rules — they
    store and retrieve decisions, nothing more.
    """

    def check_approval(self, proposal_id: str) -> ApprovalStatus:
        """Check the current approval status of a proposal.

        Args:
            proposal_id: The ActionProposal's unique identifier.

        Returns:
            The current :class:`ApprovalStatus`. Returns ``PENDING`` if no
            decision has been recorded.
        """
        ...

    def record_decision(self, decision: ApprovalDecision) -> None:
        """Record an approval decision.

        Args:
            decision: The approval decision to record. Must include the
                proposal_id, status, approver, and decided_at timestamp.

        Raises:
            ValueError: If the decision is invalid (e.g., empty proposal_id).
        """
        ...

    def get_decision(self, proposal_id: str) -> ApprovalDecision | None:
        """Retrieve the approval decision for a proposal.

        Args:
            proposal_id: The ActionProposal's unique identifier.

        Returns:
            The recorded :class:`ApprovalDecision`, or ``None`` if no
            decision has been recorded for this proposal.
        """
        ...


# ── Policy check interface ──────────────────────────────────────────────────


@runtime_checkable
class PolicyCheck(Protocol):
    """Interface for the policy check — the automated rule-evaluation layer.

    The policy check evaluates an ActionProposal against policy rules and
    returns a :class:`PolicyCheckResult`. It does NOT involve humans and does
    NOT record decisions. It is a pure function of the proposal content and
    the current policy rule set.

    The policy check runs BEFORE the approval gate in the approval workflow:
    1. Policy check evaluates the proposal → pass or fail.
    2. If pass: the proposal may proceed without human approval.
    3. If fail: the approval gate is invoked to obtain a human decision.

    Implementations must be deterministic and side-effect free.
    """

    def check(self, proposal: ActionProposal) -> PolicyCheckResult:
        """Evaluate a proposal against policy rules.

        Args:
            proposal: The ActionProposal to evaluate. The implementation
                should inspect the proposal's ``action_type``, ``risk``,
                ``parameters``, and ``metadata`` to make its determination.

        Returns:
            A :class:`PolicyCheckResult`:
            - ``passed=True`` — the proposal may proceed without human approval.
            - ``passed=False`` — the proposal requires human approval via the
              :class:`ApprovalGate` or is blocked.
        """
        ...


# ── Integration points with ActionProposal ───────────────────────────────────


@dataclass
class ApprovalContext:
    """The full context required to process a proposal through the approval workflow.

    This is the integration point that ties together the ActionProposal model,
    the policy check, and the approval gate. It is the input to the approval
    workflow orchestrator (which is NOT defined in this contract layer).

    Attributes:
        proposal: The ActionProposal being evaluated.
        policy_result: The result returned by the :class:`PolicyCheck`.
        approval_status: The current :class:`ApprovalStatus` from the
            :class:`ApprovalGate`. ``PENDING`` if the policy check passed
            (no approval needed).
        decision: The recorded :class:`ApprovalDecision`, if the approval
            gate was invoked (i.e., policy check did not pass).
    """

    proposal: ActionProposal
    policy_result: PolicyCheckResult
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    decision: ApprovalDecision | None = None

    @property
    def is_resolved(self) -> bool:
        """True if the approval workflow has reached a terminal state.

        A proposal is resolved when:
        - The policy check passed (no human decision needed), OR
        - The approval gate has recorded a decision (APPROVED, REJECTED, or DEFERRED).
        """
        if self.policy_result.passed:
            return True
        return self.approval_status != ApprovalStatus.PENDING

    @property
    def is_approved(self) -> bool:
        """True if the proposal is approved and may proceed.

        Requires both:
        - Policy check passed.
        - Approval gate recorded APPROVED (or policy check passed).
        """
        if self.policy_result.passed:
            return True
        return self.approval_status == ApprovalStatus.APPROVED


# ── Gate evaluation result ───────────────────────────────────────────────────


@dataclass
class GateResult:
    """The result of evaluating whether an approval gate passes.

    Produced by :func:`evaluate_gate` when checking whether a proposal's
    approval record satisfies the gate conditions.

    Attributes:
        passed: True if the gate conditions are met (status is APPROVED,
            approver is non-empty, timestamp is present and not in the future).
        reason: Human-readable explanation of the outcome. Empty when
            ``passed`` is True.
    """

    passed: bool
    reason: str = ""


# ── Gate evaluation function signature ───────────────────────────────────────


def evaluate_gate(proposal: ActionProposal, decision: ApprovalDecision) -> GateResult:
    """Evaluate whether an approval gate passes for a given proposal.

    This is the contract-layer function signature for gate evaluation.
    It accepts an :class:`ActionProposal` and an :class:`ApprovalDecision`
    record and returns a :class:`GateResult` indicating whether the gate
    passes.

    The gate checks:
    1. The approval status is ``APPROVED``.
    2. The approver identity is present and non-empty.
    3. The timestamp is present and not in the future.

    Args:
        proposal: The ActionProposal being evaluated.
        decision: The approval decision record to check against the gate.

    Returns:
        A :class:`GateResult` with ``passed`` set to True if all conditions
        are met, or False with a descriptive ``reason`` otherwise.

    Note:
        This is the contract-layer implementation of the gate evaluation.
        It is the canonical gate logic used by the approval workflow.
    """
    if decision.status != ApprovalStatus.APPROVED:
        return GateResult(
            passed=False,
            reason=f"Status is {decision.status}, not APPROVED",
        )

    if not decision.approver or not decision.approver.strip():
        return GateResult(
            passed=False,
            reason="Approver identity is missing or empty",
        )

    if decision.decided_at is None:
        return GateResult(
            passed=False,
            reason="Timestamp is missing",
        )

    if decision.decided_at > datetime.now():
        return GateResult(
            passed=False,
            reason="Timestamp is in the future",
        )

    return GateResult(passed=True)


# ── Boundary definition ──────────────────────────────────────────────────────

"""
Boundary between ApprovalGate and PolicyCheck
=============================================

+------------------------------------------------------------------+
|                    Approval Workflow Orchestrator                  |
|                    (not in this contract layer)                    |
+------------------------------------------------------------------+
|         |                                    |
|         v                                    v
+------------------+              +------------------+
|   PolicyCheck    |              |  ApprovalGate    |
|                  |              |                  |
| check(proposal)  |              | check_approval() |
|   -> passed=True |              | record_decision()|
|   -> passed=False|              | get_decision()   |
+------------------+              +------------------+
|         |                                    |
|         | passed=True  -> proceed            |
|         | passed=False -> invoke ApprovalGate|
|         |                                    |
|         +------------------------------------+
|                      |
|                      v
|            +------------------+
|            | ActionProposal   |
|            | (models.py)      |
|            |                  |
|            | proposal_id      |
|            | status           |
|            | action_type      |
|            | risk             |
|            | parameters       |
|            +------------------+

Rules of engagement:
1. PolicyCheck is stateless and side-effect free. It does not write to the
   ApprovalGate or modify the ActionProposal.
2. ApprovalGate does not evaluate policy rules. It only records and retrieves
   human decisions.
3. The orchestrator (not defined here) is responsible for:
   a. Calling PolicyCheck.check(proposal) first.
   b. If passed=True: proceeding without invoking ApprovalGate.
   c. If passed=False: invoking ApprovalGate to obtain a human decision.
4. The ApprovalGate never overrides a failed policy check. It only resolves
   the case where the policy check did not pass.
5. The ActionProposal.status field is updated by the orchestrator based on
   the combined outcome of PolicyCheck and ApprovalGate.
"""
