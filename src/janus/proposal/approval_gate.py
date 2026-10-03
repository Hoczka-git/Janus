"""Concrete implementation of the ApprovalGate protocol.

This module provides a concrete, in-memory implementation of the
:class:`ApprovalGate` interface defined in ``approval_contract.py``.
It records approval decisions (status, approver identity, timestamp)
and retrieves them by ``proposal_id``.

This module operates ONLY on the contract layer — it does not
evaluate policy rules. Policy evaluation is the responsibility of
the :class:`PolicyCheck` interface.

Design reference: docs/design/policy_approval_p1_design.md §3, §5
"""

from __future__ import annotations

from datetime import datetime

from janus.proposal.approval_contract import (
    ApprovalDecision,
    ApprovalGate,
    ApprovalStatus,
)
from janus.proposal.models import ActionProposal


class InMemoryApprovalGate:
    """In-memory implementation of the :class:`ApprovalGate` protocol.

    Stores approval decisions in a dict keyed by ``proposal_id``.
    At P1, this is ephemeral (lost on restart). Persistent recording
    is P2.

    This implementation does NOT evaluate policy rules. It only
    records and retrieves human decisions.

    Usage::

        gate = InMemoryApprovalGate()
        proposal = ActionProposal(proposal_id="AP-1", reason="test")
        decision = gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)
        assert gate.check_approval("AP-1") == ApprovalStatus.APPROVED
    """

    def __init__(self) -> None:
        self._decisions: dict[str, ApprovalDecision] = {}

    # ── ApprovalGate protocol implementation ──────────────────────────────

    def check_approval(self, proposal_id: str) -> ApprovalStatus:
        """Check the current approval status of a proposal.

        Args:
            proposal_id: The ActionProposal's unique identifier.

        Returns:
            The current :class:`ApprovalStatus`. Returns ``PENDING`` if no
            decision has been recorded.
        """
        decision = self._decisions.get(proposal_id)
        if decision is None:
            return ApprovalStatus.PENDING
        return decision.status

    def record_decision(self, decision: ApprovalDecision) -> None:
        """Record an approval decision.

        Args:
            decision: The approval decision to record. Must include the
                proposal_id, status, approver, and decided_at timestamp.

        Raises:
            ValueError: If the decision is invalid (e.g., empty proposal_id
                or empty approver).
        """
        if not decision.proposal_id or not decision.proposal_id.strip():
            raise ValueError("ApprovalDecision.proposal_id must not be empty")
        if not decision.approver or not decision.approver.strip():
            raise ValueError("ApprovalDecision.approver must not be empty")
        self._decisions[decision.proposal_id] = decision

    def get_decision(self, proposal_id: str) -> ApprovalDecision | None:
        """Retrieve the approval decision for a proposal.

        Args:
            proposal_id: The ActionProposal's unique identifier.

        Returns:
            The recorded :class:`ApprovalDecision`, or ``None`` if no
            decision has been recorded for this proposal.
        """
        return self._decisions.get(proposal_id)

    # ── Convenience method for ActionProposal integration ─────────────────

    def apply_gate(
        self,
        proposal: ActionProposal,
        approver: str,
        status: ApprovalStatus,
        rationale: str = "",
    ) -> ApprovalDecision:
        """Apply the approval gate to an ActionProposal.

        This is a convenience method that creates an :class:`ApprovalDecision`
        from the given parameters and records it. The decision is linked to
        the proposal via ``proposal.proposal_id``.

        Args:
            proposal: The ActionProposal to apply the gate to.
            approver: Identity of the approver (e.g., ``"user"``, ``"admin"``).
            status: The approval outcome (APPROVED, REJECTED, or DEFERRED).
            rationale: Optional human-readable reason for the decision.

        Returns:
            The recorded :class:`ApprovalDecision`.

        Raises:
            ValueError: If the proposal has no proposal_id or the approver
                is empty.
        """
        if not proposal.proposal_id or not proposal.proposal_id.strip():
            raise ValueError("ActionProposal.proposal_id must not be empty")
        if not approver or not approver.strip():
            raise ValueError("approver must not be empty")

        decision = ApprovalDecision(
            proposal_id=proposal.proposal_id,
            status=status,
            approver=approver,
            decided_at=datetime.now(),
            rationale=rationale,
        )
        self.record_decision(decision)
        return decision

    # ── Utility methods ──────────────────────────────────────────────────

    def clear(self) -> None:
        """Clear all recorded decisions. Useful for testing."""
        self._decisions.clear()

    def __len__(self) -> int:
        """Return the number of recorded decisions."""
        return len(self._decisions)
