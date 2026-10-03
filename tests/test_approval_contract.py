"""Tests for the approval contract layer interfaces and schema.

Covers:
- ApprovalStatus enum
- ApprovalDecision dataclass
- ApprovalGate protocol (runtime_checkable, cannot instantiate)
- PolicyCheck protocol (runtime_checkable, cannot instantiate)
- ApprovalContext dataclass and its properties
- Boundary between approval and policy check
- Integration with ActionProposal model
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from janus.models.policy import RiskLevel
from janus.models.policy_p1 import PolicyVerdict
from janus.proposal import ActionProposal, ActionType, ProposalStatus
from janus.proposal.approval_contract import (
    ApprovalContext,
    ApprovalDecision,
    ApprovalGate,
    ApprovalStatus,
    GateResult,
    PolicyCheck,
    evaluate_gate,
)


# ── ApprovalStatus enum ─────────────────────────────────────────────────────


class TestApprovalStatus:
    def test_values(self) -> None:
        assert ApprovalStatus.PENDING == "pending"
        assert ApprovalStatus.APPROVED == "approved"
        assert ApprovalStatus.REJECTED == "rejected"
        assert ApprovalStatus.DEFERRED == "deferred"

    def test_membership(self) -> None:
        assert len(ApprovalStatus) == 4

    def test_str_enum(self) -> None:
        assert isinstance(ApprovalStatus.PENDING, str)
        assert isinstance(ApprovalStatus.APPROVED, str)
        assert isinstance(ApprovalStatus.REJECTED, str)
        assert isinstance(ApprovalStatus.DEFERRED, str)

    def test_distinct_from_proposal_status(self) -> None:
        """ApprovalStatus and ProposalStatus are distinct enums."""
        approval_values = {s.value for s in ApprovalStatus}
        proposal_values = {s.value for s in ProposalStatus}
        # ApprovalStatus uses lowercase, ProposalStatus uses uppercase
        assert "pending" in approval_values
        assert "pending" not in proposal_values
        assert "deferred" in approval_values
        assert "deferred" not in proposal_values
        assert "PROPOSED" in proposal_values
        assert "PROPOSED" not in approval_values
        assert "EXECUTED" in proposal_values
        assert "EXECUTED" not in approval_values


# ── ApprovalDecision dataclass ──────────────────────────────────────────────


class TestApprovalDecision:
    def test_minimal_construct(self) -> None:
        decision = ApprovalDecision(
            proposal_id="AP-abc123",
            status=ApprovalStatus.APPROVED,
            approver="user",
        )
        assert decision.proposal_id == "AP-abc123"
        assert decision.status == ApprovalStatus.APPROVED
        assert decision.approver == "user"
        assert isinstance(decision.decided_at, datetime)
        assert decision.rationale == ""

    def test_full_construct(self) -> None:
        now = datetime.now().astimezone()
        decision = ApprovalDecision(
            proposal_id="AP-abc123",
            status=ApprovalStatus.REJECTED,
            approver="admin",
            decided_at=now,
            rationale="Too risky",
        )
        assert decision.proposal_id == "AP-abc123"
        assert decision.status == ApprovalStatus.REJECTED
        assert decision.approver == "admin"
        assert decision.decided_at == now
        assert decision.rationale == "Too risky"

    def test_decided_at_auto_set(self) -> None:
        decision = ApprovalDecision(
            proposal_id="AP-1",
            status=ApprovalStatus.APPROVED,
            approver="user",
        )
        assert decision.decided_at is not None
        assert isinstance(decision.decided_at, datetime)

    def test_all_statuses(self) -> None:
        for status in ApprovalStatus:
            decision = ApprovalDecision(
                proposal_id="AP-1",
                status=status,
                approver="user",
            )
            assert decision.status == status


# ── ApprovalGate protocol ───────────────────────────────────────────────────


class TestApprovalGateProtocol:
    def test_is_protocol(self) -> None:
        assert hasattr(ApprovalGate, "_is_protocol")
        assert getattr(ApprovalGate, "_is_protocol") is True

    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            ApprovalGate()  # type: ignore[abstract]

    def test_concrete_implementation(self) -> None:
        """A concrete class implementing the protocol can be instantiated."""

        class MockApprovalGate:
            def check_approval(self, proposal_id: str) -> ApprovalStatus:
                return ApprovalStatus.PENDING

            def record_decision(self, decision: ApprovalDecision) -> None:
                pass

            def get_decision(self, proposal_id: str) -> ApprovalDecision | None:
                return None

        gate: ApprovalGate = MockApprovalGate()  # type: ignore[assignment]
        assert gate.check_approval("AP-1") == ApprovalStatus.PENDING
        assert gate.get_decision("AP-1") is None

    def test_has_required_methods(self) -> None:
        assert hasattr(ApprovalGate, "check_approval")
        assert hasattr(ApprovalGate, "record_decision")
        assert hasattr(ApprovalGate, "get_decision")

    def test_no_policy_evaluation_methods(self) -> None:
        """ApprovalGate must NOT have policy evaluation methods."""
        assert not hasattr(ApprovalGate, "check")
        assert not hasattr(ApprovalGate, "evaluate")
        assert not hasattr(ApprovalGate, "evaluate_policy")


# ── PolicyCheck protocol ────────────────────────────────────────────────────


class TestPolicyCheckProtocol:
    def test_is_protocol(self) -> None:
        assert hasattr(PolicyCheck, "_is_protocol")
        assert getattr(PolicyCheck, "_is_protocol") is True

    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            PolicyCheck()  # type: ignore[abstract]

    def test_concrete_implementation(self) -> None:
        """A concrete class implementing the protocol can be instantiated."""

        class MockPolicyCheck:
            def check(self, proposal: ActionProposal) -> PolicyVerdict:
                return PolicyVerdict.ALLOW

        checker: PolicyCheck = MockPolicyCheck()  # type: ignore[assignment]
        proposal = ActionProposal(reason="test")
        assert checker.check(proposal) == PolicyVerdict.ALLOW

    def test_has_required_methods(self) -> None:
        assert hasattr(PolicyCheck, "check")

    def test_no_approval_recording_methods(self) -> None:
        """PolicyCheck must NOT have approval recording methods."""
        assert not hasattr(PolicyCheck, "record_decision")
        assert not hasattr(PolicyCheck, "check_approval")
        assert not hasattr(PolicyCheck, "get_decision")


# ── ApprovalContext dataclass ───────────────────────────────────────────────


class TestApprovalContext:
    def _make_proposal(self) -> ActionProposal:
        return ActionProposal(
            proposal_id="AP-test",
            action_type=ActionType.CREATE_TASK,
            reason="Test proposal",
            risk=RiskLevel.LOW,
        )

    def test_minimal_construct(self) -> None:
        proposal = self._make_proposal()
        ctx = ApprovalContext(
            proposal=proposal,
            policy_verdict=PolicyVerdict.ALLOW,
        )
        assert ctx.proposal is proposal
        assert ctx.policy_verdict == PolicyVerdict.ALLOW
        assert ctx.approval_status == ApprovalStatus.PENDING
        assert ctx.decision is None

    def test_full_construct(self) -> None:
        proposal = self._make_proposal()
        decision = ApprovalDecision(
            proposal_id="AP-test",
            status=ApprovalStatus.APPROVED,
            approver="user",
        )
        ctx = ApprovalContext(
            proposal=proposal,
            policy_verdict=PolicyVerdict.ASK,
            approval_status=ApprovalStatus.APPROVED,
            decision=decision,
        )
        assert ctx.proposal is proposal
        assert ctx.policy_verdict == PolicyVerdict.ASK
        assert ctx.approval_status == ApprovalStatus.APPROVED
        assert ctx.decision is decision

    # -- is_resolved --

    def test_resolved_when_allow(self) -> None:
        ctx = ApprovalContext(
            proposal=self._make_proposal(),
            policy_verdict=PolicyVerdict.ALLOW,
        )
        assert ctx.is_resolved is True

    def test_resolved_when_deny(self) -> None:
        ctx = ApprovalContext(
            proposal=self._make_proposal(),
            policy_verdict=PolicyVerdict.DENY,
        )
        assert ctx.is_resolved is True

    def test_not_resolved_when_ask_pending(self) -> None:
        ctx = ApprovalContext(
            proposal=self._make_proposal(),
            policy_verdict=PolicyVerdict.ASK,
            approval_status=ApprovalStatus.PENDING,
        )
        assert ctx.is_resolved is False

    def test_resolved_when_ask_approved(self) -> None:
        ctx = ApprovalContext(
            proposal=self._make_proposal(),
            policy_verdict=PolicyVerdict.ASK,
            approval_status=ApprovalStatus.APPROVED,
        )
        assert ctx.is_resolved is True

    def test_resolved_when_ask_rejected(self) -> None:
        ctx = ApprovalContext(
            proposal=self._make_proposal(),
            policy_verdict=PolicyVerdict.ASK,
            approval_status=ApprovalStatus.REJECTED,
        )
        assert ctx.is_resolved is True

    def test_resolved_when_ask_deferred(self) -> None:
        ctx = ApprovalContext(
            proposal=self._make_proposal(),
            policy_verdict=PolicyVerdict.ASK,
            approval_status=ApprovalStatus.DEFERRED,
        )
        assert ctx.is_resolved is True

    # -- is_approved --

    def test_approved_when_allow(self) -> None:
        ctx = ApprovalContext(
            proposal=self._make_proposal(),
            policy_verdict=PolicyVerdict.ALLOW,
        )
        assert ctx.is_approved is True

    def test_not_approved_when_deny(self) -> None:
        ctx = ApprovalContext(
            proposal=self._make_proposal(),
            policy_verdict=PolicyVerdict.DENY,
        )
        assert ctx.is_approved is False

    def test_not_approved_when_ask_pending(self) -> None:
        ctx = ApprovalContext(
            proposal=self._make_proposal(),
            policy_verdict=PolicyVerdict.ASK,
            approval_status=ApprovalStatus.PENDING,
        )
        assert ctx.is_approved is False

    def test_approved_when_ask_approved(self) -> None:
        ctx = ApprovalContext(
            proposal=self._make_proposal(),
            policy_verdict=PolicyVerdict.ASK,
            approval_status=ApprovalStatus.APPROVED,
        )
        assert ctx.is_approved is True

    def test_not_approved_when_ask_rejected(self) -> None:
        ctx = ApprovalContext(
            proposal=self._make_proposal(),
            policy_verdict=PolicyVerdict.ASK,
            approval_status=ApprovalStatus.REJECTED,
        )
        assert ctx.is_approved is False

    def test_not_approved_when_ask_deferred(self) -> None:
        ctx = ApprovalContext(
            proposal=self._make_proposal(),
            policy_verdict=PolicyVerdict.ASK,
            approval_status=ApprovalStatus.DEFERRED,
        )
        assert ctx.is_approved is False


# ── Boundary between ApprovalGate and PolicyCheck ──────────────────────────


class TestBoundary:
    def test_approval_gate_has_no_policy_methods(self) -> None:
        """ApprovalGate must not expose policy evaluation."""
        assert not hasattr(ApprovalGate, "check")
        assert not hasattr(ApprovalGate, "evaluate")
        assert not hasattr(ApprovalGate, "evaluate_policy")

    def test_policy_check_has_no_approval_methods(self) -> None:
        """PolicyCheck must not expose approval recording."""
        assert not hasattr(PolicyCheck, "record_decision")
        assert not hasattr(PolicyCheck, "check_approval")
        assert not hasattr(PolicyCheck, "get_decision")

    def test_approval_gate_is_not_policy_check(self) -> None:
        """The two protocols are distinct and non-overlapping."""
        gate_methods = {"check_approval", "record_decision", "get_decision"}
        policy_methods = {"check"}
        assert gate_methods.isdisjoint(policy_methods)

    def test_policy_check_returns_verdict_enum(self) -> None:
        """PolicyCheck.check returns PolicyVerdict, not ApprovalStatus."""
        # This is a type-level contract: the return type is PolicyVerdict
        # which has ALLOW/ASK/DENY, while ApprovalStatus has
        # PENDING/APPROVED/REJECTED/DEFERRED
        assert PolicyVerdict.ALLOW != ApprovalStatus.APPROVED
        assert PolicyVerdict.DENY != ApprovalStatus.REJECTED

    def test_approval_gate_returns_status_enum(self) -> None:
        """ApprovalGate.check_approval returns ApprovalStatus, not PolicyVerdict."""
        assert ApprovalStatus.PENDING != PolicyVerdict.ASK
        assert ApprovalStatus.APPROVED != PolicyVerdict.ALLOW


# ── Integration with ActionProposal ─────────────────────────────────────────


class TestActionProposalIntegration:
    def test_proposal_has_proposal_id(self) -> None:
        """ActionProposal must have proposal_id for ApprovalGate integration."""
        proposal = ActionProposal(reason="test")
        assert hasattr(proposal, "proposal_id")
        assert isinstance(proposal.proposal_id, str)

    def test_proposal_has_status(self) -> None:
        """ActionProposal must have status for tracking approval outcome."""
        proposal = ActionProposal(reason="test")
        assert hasattr(proposal, "status")
        assert isinstance(proposal.status, ProposalStatus)

    def test_proposal_has_risk(self) -> None:
        """ActionProposal must have risk for PolicyCheck evaluation."""
        proposal = ActionProposal(reason="test")
        assert hasattr(proposal, "risk")
        assert isinstance(proposal.risk, RiskLevel)

    def test_proposal_has_action_type(self) -> None:
        """ActionProposal must have action_type for PolicyCheck evaluation."""
        proposal = ActionProposal(reason="test")
        assert hasattr(proposal, "action_type")
        assert isinstance(proposal.action_type, ActionType)

    def test_proposal_has_parameters(self) -> None:
        """ActionProposal must have parameters for PolicyCheck evaluation."""
        proposal = ActionProposal(reason="test")
        assert hasattr(proposal, "parameters")
        assert isinstance(proposal.parameters, dict)

    def test_proposal_has_metadata(self) -> None:
        """ActionProposal must have metadata for PolicyCheck evaluation."""
        proposal = ActionProposal(reason="test")
        assert hasattr(proposal, "metadata")
        assert isinstance(proposal.metadata, dict)

    def test_approval_context_wraps_proposal(self) -> None:
        """ApprovalContext is the integration point that wraps ActionProposal."""
        proposal = ActionProposal(
            proposal_id="AP-integration",
            reason="Integration test",
            risk=RiskLevel.MEDIUM,
        )
        ctx = ApprovalContext(
            proposal=proposal,
            policy_verdict=PolicyVerdict.ASK,
            approval_status=ApprovalStatus.APPROVED,
            decision=ApprovalDecision(
                proposal_id="AP-integration",
                status=ApprovalStatus.APPROVED,
                approver="user",
            ),
        )
        assert ctx.proposal.proposal_id == "AP-integration"
        assert ctx.proposal.risk == RiskLevel.MEDIUM
        assert ctx.is_resolved is True
        assert ctx.is_approved is True

    def test_proposal_id_links_decision_to_proposal(self) -> None:
        """ApprovalDecision.proposal_id must match ActionProposal.proposal_id."""
        proposal = ActionProposal(
            proposal_id="AP-link-test",
            reason="Test",
        )
        decision = ApprovalDecision(
            proposal_id="AP-link-test",
            status=ApprovalStatus.APPROVED,
            approver="user",
        )
        assert decision.proposal_id == proposal.proposal_id


# ── GateResult dataclass ────────────────────────────────────────────────────


class TestGateResult:
    def test_passed_true(self) -> None:
        result = GateResult(passed=True)
        assert result.passed is True
        assert result.reason == ""

    def test_passed_false_with_reason(self) -> None:
        result = GateResult(passed=False, reason="Status is not APPROVED")
        assert result.passed is False
        assert result.reason == "Status is not APPROVED"

    def test_is_dataclass(self) -> None:
        import dataclasses

        assert dataclasses.is_dataclass(GateResult)


# ── evaluate_gate function signature ────────────────────────────────────────


class TestEvaluateGateSignature:
    def test_is_callable(self) -> None:
        assert callable(evaluate_gate)

    def test_accepts_proposal_and_decision(self) -> None:
        """evaluate_gate accepts an ActionProposal and an ApprovalDecision."""
        proposal = ActionProposal(
            proposal_id="AP-gate-test",
            reason="Test proposal",
        )
        decision = ApprovalDecision(
            proposal_id="AP-gate-test",
            status=ApprovalStatus.APPROVED,
            approver="user",
        )
        result = evaluate_gate(proposal, decision)
        assert isinstance(result, GateResult)

    def test_returns_gate_result_type(self) -> None:
        """evaluate_gate's return type annotation is GateResult."""
        import inspect

        sig = inspect.signature(evaluate_gate)
        # With `from __future__ import annotations`, annotations are strings
        assert sig.return_annotation in ("GateResult", GateResult)

    def test_parameter_types(self) -> None:
        """evaluate_gate's parameter types are ActionProposal and ApprovalDecision."""
        import inspect

        sig = inspect.signature(evaluate_gate)
        params = list(sig.parameters.values())
        assert len(params) == 2
        assert params[0].name == "proposal"
        assert params[1].name == "decision"


# ── evaluate_gate behavior ──────────────────────────────────────────────────


class TestEvaluateGateBehavior:
    def _make_proposal(self) -> ActionProposal:
        return ActionProposal(
            proposal_id="AP-gate-behavior",
            reason="Test proposal",
        )

    def test_approved_with_valid_identity_and_timestamp_passes(self) -> None:
        proposal = self._make_proposal()
        decision = ApprovalDecision(
            proposal_id="AP-gate-behavior",
            status=ApprovalStatus.APPROVED,
            approver="user",
            decided_at=datetime.now() - timedelta(minutes=1),
        )
        result = evaluate_gate(proposal, decision)
        assert result.passed is True
        assert result.reason == ""

    def test_denied_status_fails(self) -> None:
        proposal = self._make_proposal()
        decision = ApprovalDecision(
            proposal_id="AP-gate-behavior",
            status=ApprovalStatus.REJECTED,
            approver="user",
            decided_at=datetime.now() - timedelta(minutes=1),
        )
        result = evaluate_gate(proposal, decision)
        assert result.passed is False
        assert "not APPROVED" in result.reason

    def test_missing_identity_fails(self) -> None:
        proposal = self._make_proposal()
        decision = ApprovalDecision(
            proposal_id="AP-gate-behavior",
            status=ApprovalStatus.APPROVED,
            approver="",
            decided_at=datetime.now() - timedelta(minutes=1),
        )
        result = evaluate_gate(proposal, decision)
        assert result.passed is False
        assert "Approver" in result.reason

    def test_future_timestamp_fails(self) -> None:
        proposal = self._make_proposal()
        decision = ApprovalDecision(
            proposal_id="AP-gate-behavior",
            status=ApprovalStatus.APPROVED,
            approver="user",
            decided_at=datetime.now() + timedelta(hours=1),
        )
        result = evaluate_gate(proposal, decision)
        assert result.passed is False
        assert "future" in result.reason
