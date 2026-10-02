"""Tests for the InMemoryApprovalGate implementation.

Covers:
- Protocol conformance (implements ApprovalGate)
- check_approval (PENDING when no decision, correct status after recording)
- record_decision (stores decision, validates input)
- get_decision (retrieves decision, None when not found)
- apply_gate (convenience method with ActionProposal)
- Integration with ActionProposal model
- Boundary: no policy evaluation methods
"""

from __future__ import annotations

from datetime import datetime

import pytest

from janus.models.policy import RiskLevel
from janus.proposal import ActionProposal, ActionType, ProposalStatus
from janus.proposal.approval_contract import (
    ApprovalDecision,
    ApprovalGate,
    ApprovalStatus,
)
from janus.proposal.approval_gate import InMemoryApprovalGate


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_proposal(proposal_id: str = "AP-test") -> ActionProposal:
    return ActionProposal(
        proposal_id=proposal_id,
        action_type=ActionType.CREATE_TASK,
        reason="Test proposal",
        risk=RiskLevel.LOW,
    )


# ── Protocol conformance ───────────────────────────────────────────────────


class TestProtocolConformance:
    def test_implements_approval_gate(self) -> None:
        gate = InMemoryApprovalGate()
        assert isinstance(gate, ApprovalGate)

    def test_is_runtime_checkable(self) -> None:
        """InMemoryApprovalGate satisfies the runtime_checkable protocol."""
        gate = InMemoryApprovalGate()
        assert hasattr(gate, "check_approval")
        assert hasattr(gate, "record_decision")
        assert hasattr(gate, "get_decision")

    def test_no_policy_evaluation_methods(self) -> None:
        """ApprovalGate must not expose policy evaluation."""
        gate = InMemoryApprovalGate()
        assert not hasattr(gate, "check")
        assert not hasattr(gate, "evaluate")
        assert not hasattr(gate, "evaluate_policy")


# ── check_approval ─────────────────────────────────────────────────────────


class TestCheckApproval:
    def test_pending_when_no_decision(self) -> None:
        gate = InMemoryApprovalGate()
        assert gate.check_approval("AP-1") == ApprovalStatus.PENDING

    def test_approved_after_recording(self) -> None:
        gate = InMemoryApprovalGate()
        gate.record_decision(ApprovalDecision(
            proposal_id="AP-1",
            status=ApprovalStatus.APPROVED,
            approver="user",
        ))
        assert gate.check_approval("AP-1") == ApprovalStatus.APPROVED

    def test_rejected_after_recording(self) -> None:
        gate = InMemoryApprovalGate()
        gate.record_decision(ApprovalDecision(
            proposal_id="AP-1",
            status=ApprovalStatus.REJECTED,
            approver="admin",
        ))
        assert gate.check_approval("AP-1") == ApprovalStatus.REJECTED

    def test_deferred_after_recording(self) -> None:
        gate = InMemoryApprovalGate()
        gate.record_decision(ApprovalDecision(
            proposal_id="AP-1",
            status=ApprovalStatus.DEFERRED,
            approver="user",
        ))
        assert gate.check_approval("AP-1") == ApprovalStatus.DEFERRED

    def test_independent_proposals(self) -> None:
        gate = InMemoryApprovalGate()
        gate.record_decision(ApprovalDecision(
            proposal_id="AP-1",
            status=ApprovalStatus.APPROVED,
            approver="user",
        ))
        assert gate.check_approval("AP-2") == ApprovalStatus.PENDING
        assert gate.check_approval("AP-1") == ApprovalStatus.APPROVED


# ── record_decision ────────────────────────────────────────────────────────


class TestRecordDecision:
    def test_stores_decision(self) -> None:
        gate = InMemoryApprovalGate()
        decision = ApprovalDecision(
            proposal_id="AP-1",
            status=ApprovalStatus.APPROVED,
            approver="user",
        )
        gate.record_decision(decision)
        assert gate.get_decision("AP-1") is decision

    def test_overwrites_existing(self) -> None:
        gate = InMemoryApprovalGate()
        gate.record_decision(ApprovalDecision(
            proposal_id="AP-1",
            status=ApprovalStatus.APPROVED,
            approver="user",
        ))
        gate.record_decision(ApprovalDecision(
            proposal_id="AP-1",
            status=ApprovalStatus.REJECTED,
            approver="admin",
        ))
        assert gate.check_approval("AP-1") == ApprovalStatus.REJECTED

    def test_empty_proposal_id_raises(self) -> None:
        gate = InMemoryApprovalGate()
        with pytest.raises(ValueError, match="proposal_id"):
            gate.record_decision(ApprovalDecision(
                proposal_id="",
                status=ApprovalStatus.APPROVED,
                approver="user",
            ))

    def test_empty_approver_raises(self) -> None:
        gate = InMemoryApprovalGate()
        with pytest.raises(ValueError, match="approver"):
            gate.record_decision(ApprovalDecision(
                proposal_id="AP-1",
                status=ApprovalStatus.APPROVED,
                approver="",
            ))

    def test_whitespace_proposal_id_raises(self) -> None:
        gate = InMemoryApprovalGate()
        with pytest.raises(ValueError, match="proposal_id"):
            gate.record_decision(ApprovalDecision(
                proposal_id="   ",
                status=ApprovalStatus.APPROVED,
                approver="user",
            ))

    def test_whitespace_approver_raises(self) -> None:
        gate = InMemoryApprovalGate()
        with pytest.raises(ValueError, match="approver"):
            gate.record_decision(ApprovalDecision(
                proposal_id="AP-1",
                status=ApprovalStatus.APPROVED,
                approver="   ",
            ))


# ── get_decision ───────────────────────────────────────────────────────────


class TestGetDecision:
    def test_returns_none_when_not_found(self) -> None:
        gate = InMemoryApprovalGate()
        assert gate.get_decision("AP-1") is None

    def test_returns_decision_when_found(self) -> None:
        gate = InMemoryApprovalGate()
        decision = ApprovalDecision(
            proposal_id="AP-1",
            status=ApprovalStatus.APPROVED,
            approver="user",
            rationale="Looks good",
        )
        gate.record_decision(decision)
        retrieved = gate.get_decision("AP-1")
        assert retrieved is not None
        assert retrieved is decision
        assert retrieved.proposal_id == "AP-1"
        assert retrieved.status == ApprovalStatus.APPROVED
        assert retrieved.approver == "user"
        assert retrieved.rationale == "Looks good"
        assert isinstance(retrieved.decided_at, datetime)


# ── apply_gate (ActionProposal integration) ────────────────────────────────


class TestApplyGate:
    def test_apply_approved(self) -> None:
        gate = InMemoryApprovalGate()
        proposal = _make_proposal("AP-1")
        decision = gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)
        assert decision.proposal_id == "AP-1"
        assert decision.status == ApprovalStatus.APPROVED
        assert decision.approver == "user"
        assert isinstance(decision.decided_at, datetime)
        assert gate.check_approval("AP-1") == ApprovalStatus.APPROVED

    def test_apply_rejected(self) -> None:
        gate = InMemoryApprovalGate()
        proposal = _make_proposal("AP-1")
        decision = gate.apply_gate(proposal, "admin", ApprovalStatus.REJECTED)
        assert decision.status == ApprovalStatus.REJECTED
        assert decision.approver == "admin"
        assert gate.check_approval("AP-1") == ApprovalStatus.REJECTED

    def test_apply_deferred(self) -> None:
        gate = InMemoryApprovalGate()
        proposal = _make_proposal("AP-1")
        decision = gate.apply_gate(proposal, "user", ApprovalStatus.DEFERRED)
        assert decision.status == ApprovalStatus.DEFERRED
        assert gate.check_approval("AP-1") == ApprovalStatus.DEFERRED

    def test_apply_with_rationale(self) -> None:
        gate = InMemoryApprovalGate()
        proposal = _make_proposal("AP-1")
        decision = gate.apply_gate(
            proposal, "user", ApprovalStatus.APPROVED, rationale="Safe to proceed"
        )
        assert decision.rationale == "Safe to proceed"

    def test_apply_empty_proposal_id_raises(self) -> None:
        gate = InMemoryApprovalGate()
        proposal = _make_proposal("")
        with pytest.raises(ValueError, match="proposal_id"):
            gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)

    def test_apply_empty_approver_raises(self) -> None:
        gate = InMemoryApprovalGate()
        proposal = _make_proposal("AP-1")
        with pytest.raises(ValueError, match="approver"):
            gate.apply_gate(proposal, "", ApprovalStatus.APPROVED)

    def test_apply_whitespace_approver_raises(self) -> None:
        gate = InMemoryApprovalGate()
        proposal = _make_proposal("AP-1")
        with pytest.raises(ValueError, match="approver"):
            gate.apply_gate(proposal, "   ", ApprovalStatus.APPROVED)

    def test_apply_overwrites_previous(self) -> None:
        gate = InMemoryApprovalGate()
        proposal = _make_proposal("AP-1")
        gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)
        gate.apply_gate(proposal, "admin", ApprovalStatus.REJECTED)
        assert gate.check_approval("AP-1") == ApprovalStatus.REJECTED


# ── Utility methods ────────────────────────────────────────────────────────


class TestUtilityMethods:
    def test_len_empty(self) -> None:
        gate = InMemoryApprovalGate()
        assert len(gate) == 0

    def test_len_after_recording(self) -> None:
        gate = InMemoryApprovalGate()
        gate.record_decision(ApprovalDecision(
            proposal_id="AP-1",
            status=ApprovalStatus.APPROVED,
            approver="user",
        ))
        assert len(gate) == 1

    def test_clear(self) -> None:
        gate = InMemoryApprovalGate()
        gate.record_decision(ApprovalDecision(
            proposal_id="AP-1",
            status=ApprovalStatus.APPROVED,
            approver="user",
        ))
        gate.clear()
        assert len(gate) == 0
        assert gate.check_approval("AP-1") == ApprovalStatus.PENDING


# ── Integration with ActionProposal ────────────────────────────────────────


class TestActionProposalIntegration:
    def test_gate_captures_proposal_id(self) -> None:
        gate = InMemoryApprovalGate()
        proposal = _make_proposal("AP-integration")
        gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)
        assert gate.check_approval("AP-integration") == ApprovalStatus.APPROVED

    def test_gate_captures_approver_identity(self) -> None:
        gate = InMemoryApprovalGate()
        proposal = _make_proposal("AP-1")
        gate.apply_gate(proposal, "admin", ApprovalStatus.APPROVED)
        decision = gate.get_decision("AP-1")
        assert decision is not None
        assert decision.approver == "admin"

    def test_gate_captures_timestamp(self) -> None:
        gate = InMemoryApprovalGate()
        proposal = _make_proposal("AP-1")
        before = datetime.now()
        gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)
        after = datetime.now()
        decision = gate.get_decision("AP-1")
        assert decision is not None
        assert before <= decision.decided_at <= after

    def test_multiple_proposals_independent(self) -> None:
        gate = InMemoryApprovalGate()
        p1 = _make_proposal("AP-1")
        p2 = _make_proposal("AP-2")
        gate.apply_gate(p1, "user", ApprovalStatus.APPROVED)
        gate.apply_gate(p2, "admin", ApprovalStatus.REJECTED)
        assert gate.check_approval("AP-1") == ApprovalStatus.APPROVED
        assert gate.check_approval("AP-2") == ApprovalStatus.REJECTED

    def test_proposal_status_not_modified(self) -> None:
        """Applying the gate must not modify the ActionProposal.status."""
        gate = InMemoryApprovalGate()
        proposal = _make_proposal("AP-1")
        original_status = proposal.status
        gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)
        assert proposal.status == original_status
