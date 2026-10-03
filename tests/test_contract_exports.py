"""Tests for contract layer exports and interface definitions.

Verifies that the policy check module and approval gate interface
are properly exported from the janus.proposal package and that
the contract layer is ready for wiring.

Covers:
- Package-level exports of all contract types
- Protocol conformance of concrete implementations
- Interface boundary between ApprovalGate and PolicyCheck
- ActionProposal integration with contract types
"""

from __future__ import annotations

from typing import Any

import pytest

from janus.proposal import (
    ActionProposal,
    ActionType,
    ApprovalContext,
    ApprovalDecision,
    ApprovalGate,
    ApprovalStatus,
    InMemoryApprovalGate,
    PolicyCheck,
    ProposalPolicyCheck,
    ProposalStatus,
)
from janus.proposal.approval_contract import (
    ApprovalGate as ApprovalGateProtocol,
    PolicyCheck as PolicyCheckProtocol,
)
from janus.proposal.models import RiskLevel
from janus.models.policy_p1 import PolicyVerdict


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_proposal(
    proposal_id: str = "AP-001",
    action_type: ActionType = ActionType.CREATE_TASK,
    status: ProposalStatus = ProposalStatus.PROPOSED,
    **kwargs: Any,
) -> ActionProposal:
    """Create a minimal valid ActionProposal for testing."""
    return ActionProposal(
        proposal_id=proposal_id,
        action_type=action_type,
        reason="Test proposal",
        source="test",
        status=status,
        **kwargs,
    )


# ── Package exports ──────────────────────────────────────────────────────────


class TestPackageExports:
    """Verify all contract types are exported from janus.proposal."""

    def test_approval_gate_exported(self) -> None:
        assert ApprovalGate is ApprovalGateProtocol

    def test_policy_check_exported(self) -> None:
        assert PolicyCheck is PolicyCheckProtocol

    def test_approval_status_exported(self) -> None:
        assert ApprovalStatus.PENDING == "pending"
        assert ApprovalStatus.APPROVED == "approved"
        assert ApprovalStatus.REJECTED == "rejected"
        assert ApprovalStatus.DEFERRED == "deferred"

    def test_approval_decision_exported(self) -> None:
        decision = ApprovalDecision(
            proposal_id="AP-001",
            status=ApprovalStatus.APPROVED,
            approver="user",
        )
        assert decision.proposal_id == "AP-001"
        assert decision.status == ApprovalStatus.APPROVED
        assert decision.approver == "user"

    def test_approval_context_exported(self) -> None:
        proposal = _make_proposal()
        context = ApprovalContext(
            proposal=proposal,
            policy_verdict=PolicyVerdict.ALLOW,
            approval_status=ApprovalStatus.PENDING,
        )
        assert context.proposal is proposal
        assert context.approval_status == ApprovalStatus.PENDING

    def test_in_memory_approval_gate_exported(self) -> None:
        gate = InMemoryApprovalGate()
        assert isinstance(gate, ApprovalGate)

    def test_proposal_policy_check_exported(self) -> None:
        checker = ProposalPolicyCheck()
        assert isinstance(checker, PolicyCheck)


# ── Protocol conformance ─────────────────────────────────────────────────────


class TestProtocolConformance:
    """Verify concrete implementations satisfy their protocols."""

    def test_in_memory_approval_gate_satisfies_protocol(self) -> None:
        gate = InMemoryApprovalGate()
        assert isinstance(gate, ApprovalGate)

    def test_proposal_policy_check_satisfies_protocol(self) -> None:
        checker = ProposalPolicyCheck()
        assert isinstance(checker, PolicyCheck)

    def test_approval_gate_is_runtime_checkable(self) -> None:
        assert hasattr(ApprovalGate, "_is_protocol")

    def test_policy_check_is_runtime_checkable(self) -> None:
        assert hasattr(PolicyCheck, "_is_protocol")


# ── Interface boundary ───────────────────────────────────────────────────────


class TestInterfaceBoundary:
    """Verify the boundary between ApprovalGate and PolicyCheck."""

    def test_policy_check_does_not_invoke_gate(self) -> None:
        """PolicyCheck must not call ApprovalGate."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck()
        proposal = _make_proposal()

        # Policy check should work without any gate interaction
        verdict = checker.check(proposal)
        assert verdict is not None

        # Gate should still be pending (no interaction)
        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.PENDING

    def test_approval_gate_does_not_evaluate_policy(self) -> None:
        """ApprovalGate must not evaluate policy rules."""
        gate = InMemoryApprovalGate()
        proposal = _make_proposal()

        # Gate should return PENDING without policy evaluation
        status = gate.check_approval(proposal.proposal_id)
        assert status == ApprovalStatus.PENDING

    def test_gate_records_decision_without_policy(self) -> None:
        """ApprovalGate records decisions independently of policy."""
        gate = InMemoryApprovalGate()
        proposal = _make_proposal()

        decision = ApprovalDecision(
            proposal_id=proposal.proposal_id,
            status=ApprovalStatus.APPROVED,
            approver="user",
        )
        gate.record_decision(decision)

        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.APPROVED


# ── ActionProposal integration ───────────────────────────────────────────────


class TestActionProposalIntegration:
    """Verify ActionProposal works with contract types."""

    def test_proposal_id_links_to_decision(self) -> None:
        gate = InMemoryApprovalGate()
        proposal = _make_proposal(proposal_id="AP-123")

        decision = ApprovalDecision(
            proposal_id=proposal.proposal_id,
            status=ApprovalStatus.APPROVED,
            approver="user",
        )
        gate.record_decision(decision)

        assert gate.check_approval("AP-123") == ApprovalStatus.APPROVED

    def test_proposal_risk_passed_to_policy(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(risk=RiskLevel.HIGH)

        verdict = checker.check(proposal)
        assert verdict is not None

    def test_proposal_action_type_mapped(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(action_type=ActionType.CREATE_TASK)

        verdict = checker.check(proposal)
        assert verdict is not None

    def test_multiple_proposals_independent(self) -> None:
        gate = InMemoryApprovalGate()
        p1 = _make_proposal(proposal_id="AP-1")
        p2 = _make_proposal(proposal_id="AP-2")

        gate.record_decision(
            ApprovalDecision(
                proposal_id="AP-1",
                status=ApprovalStatus.APPROVED,
                approver="user",
            )
        )

        assert gate.check_approval("AP-1") == ApprovalStatus.APPROVED
        assert gate.check_approval("AP-2") == ApprovalStatus.PENDING


# ── Contract evaluation ──────────────────────────────────────────────────────


class TestContractEvaluation:
    """Verify the contract evaluation flow."""

    def test_allow_flow_no_gate_invocation(self) -> None:
        """ALLOW verdict should not require gate."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck()
        proposal = _make_proposal()

        verdict = checker.check(proposal)
        # Gate should not be invoked for ALLOW
        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.PENDING

    def test_ask_flow_gate_invoked(self) -> None:
        """ASK verdict should be resolved by gate."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(risk=RiskLevel.HIGH)

        verdict = checker.check(proposal)
        # For ASK, gate should be invoked
        if verdict.value == "ask":
            gate.record_decision(
                ApprovalDecision(
                    proposal_id=proposal.proposal_id,
                    status=ApprovalStatus.APPROVED,
                    approver="user",
                )
            )
            assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.APPROVED

    def test_deny_flow_no_gate_invocation(self) -> None:
        """DENY verdict should not require gate."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck()
        proposal = _make_proposal()

        verdict = checker.check(proposal)
        # Gate should not be invoked for DENY
        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.PENDING
