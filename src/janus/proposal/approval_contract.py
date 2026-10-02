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
   :class:`ActionProposal` and returns a :class:`PolicyVerdict` (ALLOW, ASK,
   DENY). No human involvement.

3. **Boundary** — the policy check runs first and may short-circuit (DENY).
   If the policy check returns ASK, the approval gate is invoked to obtain a
   human decision. The approval gate never overrides a DENY verdict; it only
   resolves ASK into APPROVED or REJECTED.

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

from janus.models.policy_p1 import PolicyVerdict
from janus.proposal.models import ActionProposal


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
    returns a verdict. It does NOT involve humans and does NOT record
    decisions. It is a pure function of the proposal content and the current
    policy rule set.

    The policy check runs BEFORE the approval gate in the approval workflow:
    1. Policy check evaluates the proposal → ALLOW, ASK, or DENY.
    2. If ALLOW: the proposal may proceed without human approval.
    3. If ASK: the approval gate is invoked to obtain a human decision.
    4. If DENY: the proposal is blocked; the approval gate is NOT invoked.

    Implementations must be deterministic and side-effect free.
    """

    def check(self, proposal: ActionProposal) -> PolicyVerdict:
        """Evaluate a proposal against policy rules.

        Args:
            proposal: The ActionProposal to evaluate. The implementation
                should inspect the proposal's ``action_type``, ``risk``,
                ``parameters``, and ``metadata`` to make its determination.

        Returns:
            A :class:`PolicyVerdict`:
            - ``ALLOW`` — the proposal may proceed without human approval.
            - ``ASK`` — the proposal requires human approval via the
              :class:`ApprovalGate`.
            - ``DENY`` — the proposal is blocked; cannot proceed even with
              human approval.
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
        policy_verdict: The verdict returned by the :class:`PolicyCheck`.
        approval_status: The current :class:`ApprovalStatus` from the
            :class:`ApprovalGate`. ``PENDING`` if the policy check returned
            ALLOW (no approval needed).
        decision: The recorded :class:`ApprovalDecision`, if the approval
            gate was invoked (i.e., policy check returned ASK).
    """

    proposal: ActionProposal
    policy_verdict: PolicyVerdict
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    decision: ApprovalDecision | None = None

    @property
    def is_resolved(self) -> bool:
        """True if the approval workflow has reached a terminal state.

        A proposal is resolved when:
        - The policy check returned ALLOW or DENY (no human decision needed), OR
        - The approval gate has recorded a decision (APPROVED, REJECTED, or DEFERRED).
        """
        if self.policy_verdict in (PolicyVerdict.ALLOW, PolicyVerdict.DENY):
            return True
        return self.approval_status != ApprovalStatus.PENDING

    @property
    def is_approved(self) -> bool:
        """True if the proposal is approved and may proceed.

        Requires both:
        - Policy check did not return DENY.
        - Approval gate recorded APPROVED (or policy check returned ALLOW).
        """
        if self.policy_verdict == PolicyVerdict.DENY:
            return False
        if self.policy_verdict == PolicyVerdict.ALLOW:
            return True
        return self.approval_status == ApprovalStatus.APPROVED


# ── Boundary definition ──────────────────────────────────────────────────────

"""
Boundary between ApprovalGate and PolicyCheck
=============================================

+------------------------------------------------------------------+
|                    Approval Workflow Orchestrator                  |
|                    (not in this contract layer)                    |
+------------------------------------------------------------------+
         |                                    |
         v                                    v
+------------------+              +------------------+
|   PolicyCheck    |              |  ApprovalGate    |
|                  |              |                  |
| check(proposal)  |              | check_approval() |
|   -> ALLOW       |              | record_decision()|
|   -> ASK         |              | get_decision()   |
|   -> DENY        |              |                  |
+------------------+              +------------------+
         |                                    |
         | ALLOW  -> proceed                   |
         | DENY   -> block                    |
         | ASK    -> invoke ApprovalGate       |
         |                                    |
         +------------------------------------+
                      |
                      v
            +------------------+
            | ActionProposal   |
            | (models.py)      |
            |                  |
            | proposal_id      |
            | status           |
            | action_type      |
            | risk             |
            | parameters       |
            +------------------+

Rules of engagement:
1. PolicyCheck is stateless and side-effect free. It does not write to the
   ApprovalGate or modify the ActionProposal.
2. ApprovalGate does not evaluate policy rules. It only records and retrieves
   human decisions.
3. The orchestrator (not defined here) is responsible for:
   a. Calling PolicyCheck.check(proposal) first.
   b. If ALLOW: proceeding without invoking ApprovalGate.
   c. If ASK: invoking ApprovalGate to obtain a human decision.
   d. If DENY: blocking the proposal without invoking ApprovalGate.
4. The ApprovalGate never overrides a DENY verdict. It only resolves ASK.
5. The ActionProposal.status field is updated by the orchestrator based on
   the combined outcome of PolicyCheck and ApprovalGate.
"""
