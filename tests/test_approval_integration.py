"""Integration tests for the approval contract layer with ActionProposal.

Covers the end-to-end contract flow:
1. ActionProposal → PolicyCheck → PolicyVerdict
2. PolicyVerdict → ApprovalGate (if ASK) → ApprovalStatus
3. ApprovalContext captures the full state
4. Approval state transitions (PENDING → APPROVED/REJECTED/DEFERRED)
5. Policy check invocation rules (ALLOW short-circuits, DENY blocks)
"""

from __future__ import annotations

from datetime import datetime

import pytest

from janus.models.policy import ImpactLevel, Policy, PolicyAction, PolicyDecision, RiskLevel
from janus.models.policy_p1 import PolicyVerdict
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


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_proposal(
    proposal_id: str = "AP-test-001",
    action_type: ActionType = ActionType.CREATE_TASK,
    risk: RiskLevel = RiskLevel.LOW,
    status: ProposalStatus = ProposalStatus.PROPOSED,
) -> ActionProposal:
    """Create a minimal ActionProposal for testing."""
    return ActionProposal(
        proposal_id=proposal_id,
        action_type=action_type,
        target_id="task-1",
        parameters={"title": "Test task"},
        reason="Test proposal",
        source="test",
        risk=risk,
        status=status,
    )


def _make_allow_all_policy() -> Policy:
    """Create a policy that allows everything."""
    return Policy(
        rules=[],
        default_decision=PolicyDecision.ALLOW,
    )


def _make_deny_all_policy() -> Policy:
    """Create a policy that denies everything."""
    return Policy(
        rules=[],
        default_decision=PolicyDecision.DENY,
    )


def _make_ask_all_policy() -> Policy:
    """Create a policy that asks for approval on everything."""
    return Policy(
        rules=[],
        default_decision=PolicyDecision.ASK,
    )


# ── End-to-end contract flow ─────────────────────────────────────────────────


class TestEndToEndContractFlow:
    """Test the full contract flow: ActionProposal → PolicyCheck → ApprovalGate."""

    def test_allow_flow_no_gate_invocation(self) -> None:
        """When policy returns ALLOW, the approval gate is NOT invoked."""
        proposal = _make_proposal(risk=RiskLevel.LOW)
        policy_check = ProposalPolicyCheck(policy=_make_allow_all_policy())
        gate = InMemoryApprovalGate()

        # Policy check returns ALLOW
        verdict = policy_check.check(proposal)
        assert verdict == PolicyVerdict.ALLOW

        # Gate is NOT invoked — no decision recorded
        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.PENDING

        # Build context
        context = ApprovalContext(
            proposal=proposal,
            policy_verdict=verdict,
            approval_status=gate.check_approval(proposal.proposal_id),
        )
        assert context.is_resolved is True
        assert context.is_approved is True
        assert context.decision is None

    def test_deny_flow_no_gate_invocation(self) -> None:
        """When policy returns DENY, the approval gate is NOT invoked."""
        proposal = _make_proposal(risk=RiskLevel.HIGH)
        policy_check = ProposalPolicyCheck(policy=_make_deny_all_policy())
        gate = InMemoryApprovalGate()

        # Policy check returns DENY
        verdict = policy_check.check(proposal)
        assert verdict == PolicyVerdict.DENY

        # Gate is NOT invoked
        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.PENDING

        # Build context
        context = ApprovalContext(
            proposal=proposal,
            policy_verdict=verdict,
            approval_status=gate.check_approval(proposal.proposal_id),
        )
        assert context.is_resolved is True
        assert context.is_approved is False
        assert context.decision is None

    def test_ask_flow_gate_invoked_and_approved(self) -> None:
        """When policy returns ASK, the gate is invoked and human approves."""
        proposal = _make_proposal(risk=RiskLevel.MEDIUM)
        policy_check = ProposalPolicyCheck(policy=_make_ask_all_policy())
        gate = InMemoryApprovalGate()

        # Policy check returns ASK
        verdict = policy_check.check(proposal)
        assert verdict == PolicyVerdict.ASK

        # Gate is invoked — human approves
        decision = gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)
        assert decision.status == ApprovalStatus.APPROVED
        assert decision.approver == "user"

        # Build context
        context = ApprovalContext(
            proposal=proposal,
            policy_verdict=verdict,
            approval_status=gate.check_approval(proposal.proposal_id),
            decision=decision,
        )
        assert context.is_resolved is True
        assert context.is_approved is True
        assert context.decision is not None
        assert context.decision.status == ApprovalStatus.APPROVED

    def test_ask_flow_gate_invoked_and_rejected(self) -> None:
        """When policy returns ASK, the gate is invoked and human rejects."""
        proposal = _make_proposal(risk=RiskLevel.MEDIUM)
        policy_check = ProposalPolicyCheck(policy=_make_ask_all_policy())
        gate = InMemoryApprovalGate()

        # Policy check returns ASK
        verdict = policy_check.check(proposal)
        assert verdict == PolicyVerdict.ASK

        # Gate is invoked — human rejects
        decision = gate.apply_gate(proposal, "user", ApprovalStatus.REJECTED)
        assert decision.status == ApprovalStatus.REJECTED

        # Build context
        context = ApprovalContext(
            proposal=proposal,
            policy_verdict=verdict,
            approval_status=gate.check_approval(proposal.proposal_id),
            decision=decision,
        )
        assert context.is_resolved is True
        assert context.is_approved is False
        assert context.decision is not None
        assert context.decision.status == ApprovalStatus.REJECTED

    def test_ask_flow_gate_invoked_and_deferred(self) -> None:
        """When policy returns ASK, the gate is invoked and human defers."""
        proposal = _make_proposal(risk=RiskLevel.MEDIUM)
        policy_check = ProposalPolicyCheck(policy=_make_ask_all_policy())
        gate = InMemoryApprovalGate()

        # Policy check returns ASK
        verdict = policy_check.check(proposal)
        assert verdict == PolicyVerdict.ASK

        # Gate is invoked — human defers
        decision = gate.apply_gate(proposal, "user", ApprovalStatus.DEFERRED)
        assert decision.status == ApprovalStatus.DEFERRED

        # Build context
        context = ApprovalContext(
            proposal=proposal,
            policy_verdict=verdict,
            approval_status=gate.check_approval(proposal.proposal_id),
            decision=decision,
        )
        assert context.is_resolved is True
        assert context.is_approved is False
        assert context.decision is not None
        assert context.decision.status == ApprovalStatus.DEFERRED


# ── Approval state transitions ───────────────────────────────────────────────


class TestApprovalStateTransitions:
    """Test approval state transitions through the gate."""

    def test_pending_to_approved(self) -> None:
        gate = InMemoryApprovalGate()
        proposal = _make_proposal(proposal_id="AP-transition-1")

        # Initial state: PENDING
        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.PENDING

        # Transition to APPROVED
        gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)
        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.APPROVED

    def test_pending_to_rejected(self) -> None:
        gate = InMemoryApprovalGate()
        proposal = _make_proposal(proposal_id="AP-transition-2")

        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.PENDING
        gate.apply_gate(proposal, "user", ApprovalStatus.REJECTED)
        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.REJECTED

    def test_pending_to_deferred(self) -> None:
        gate = InMemoryApprovalGate()
        proposal = _make_proposal(proposal_id="AP-transition-3")

        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.PENDING
        gate.apply_gate(proposal, "user", ApprovalStatus.DEFERRED)
        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.DEFERRED

    def test_overwrite_decision(self) -> None:
        """A new decision overwrites the previous one."""
        gate = InMemoryApprovalGate()
        proposal = _make_proposal(proposal_id="AP-transition-4")

        gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)
        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.APPROVED

        # Overwrite with REJECTED
        gate.apply_gate(proposal, "admin", ApprovalStatus.REJECTED)
        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.REJECTED

    def test_get_decision_returns_recorded_decision(self) -> None:
        gate = InMemoryApprovalGate()
        proposal = _make_proposal(proposal_id="AP-transition-5")

        # No decision recorded yet
        assert gate.get_decision(proposal.proposal_id) is None

        # Record a decision
        gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED, rationale="Looks good")
        decision = gate.get_decision(proposal.proposal_id)
        assert decision is not None
        assert decision.proposal_id == "AP-transition-5"
        assert decision.status == ApprovalStatus.APPROVED
        assert decision.approver == "user"
        assert decision.rationale == "Looks good"

    def test_clear_resets_all_decisions(self) -> None:
        gate = InMemoryApprovalGate()
        proposal = _make_proposal(proposal_id="AP-transition-6")

        gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)
        assert len(gate) == 1

        gate.clear()
        assert len(gate) == 0
        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.PENDING


# ── Policy check invocation rules ────────────────────────────────────────────


class TestPolicyCheckInvocation:
    """Test that policy check is invoked correctly in the contract flow."""

    def test_policy_check_called_with_action_proposal(self) -> None:
        """PolicyCheck.check receives the ActionProposal."""
        proposal = _make_proposal(
            action_type=ActionType.CREATE_TASK,
            risk=RiskLevel.LOW,
        )
        policy_check = ProposalPolicyCheck(policy=_make_allow_all_policy())

        verdict = policy_check.check(proposal)
        assert verdict == PolicyVerdict.ALLOW

    def test_policy_check_maps_action_type_correctly(self) -> None:
        """Different action types map to different policy actions."""
        # CREATE_TASK → CREATE policy action
        proposal_create = _make_proposal(action_type=ActionType.CREATE_TASK)
        policy_check = ProposalPolicyCheck(policy=_make_allow_all_policy())
        assert policy_check.check(proposal_create) == PolicyVerdict.ALLOW

        # UPDATE_TASK → UPDATE policy action
        proposal_update = _make_proposal(action_type=ActionType.UPDATE_TASK)
        assert policy_check.check(proposal_update) == PolicyVerdict.ALLOW

    def test_policy_check_uses_risk_level(self) -> None:
        """Risk level affects the policy verdict."""
        # LOW risk with allow-all policy → ALLOW
        proposal_low = _make_proposal(risk=RiskLevel.LOW)
        policy_check = ProposalPolicyCheck(policy=_make_allow_all_policy())
        assert policy_check.check(proposal_low) == PolicyVerdict.ALLOW

        # HIGH risk with deny-all policy → DENY
        proposal_high = _make_proposal(risk=RiskLevel.HIGH)
        policy_check_deny = ProposalPolicyCheck(policy=_make_deny_all_policy())
        assert policy_check_deny.check(proposal_high) == PolicyVerdict.DENY

    def test_policy_check_deterministic(self) -> None:
        """Same proposal + same policy → same verdict."""
        proposal = _make_proposal()
        policy_check = ProposalPolicyCheck()

        verdict1 = policy_check.check(proposal)
        verdict2 = policy_check.check(proposal)
        assert verdict1 == verdict2

    def test_policy_check_side_effect_free(self) -> None:
        """PolicyCheck does not modify the proposal."""
        proposal = _make_proposal()
        original_status = proposal.status
        original_updated_at = proposal.updated_at

        policy_check = ProposalPolicyCheck()
        policy_check.check(proposal)

        assert proposal.status == original_status
        assert proposal.updated_at == original_updated_at


# ── ApprovalContext properties ───────────────────────────────────────────────


class TestApprovalContext:
    """Test ApprovalContext properties and state tracking."""

    def test_context_with_allow_verdict(self) -> None:
        proposal = _make_proposal()
        context = ApprovalContext(
            proposal=proposal,
            policy_verdict=PolicyVerdict.ALLOW,
        )
        assert context.is_resolved is True
        assert context.is_approved is True
        assert context.approval_status == ApprovalStatus.PENDING
        assert context.decision is None

    def test_context_with_deny_verdict(self) -> None:
        proposal = _make_proposal()
        context = ApprovalContext(
            proposal=proposal,
            policy_verdict=PolicyVerdict.DENY,
        )
        assert context.is_resolved is True
        assert context.is_approved is False

    def test_context_with_ask_verdict_and_approved(self) -> None:
        proposal = _make_proposal()
        decision = ApprovalDecision(
            proposal_id=proposal.proposal_id,
            status=ApprovalStatus.APPROVED,
            approver="user",
        )
        context = ApprovalContext(
            proposal=proposal,
            policy_verdict=PolicyVerdict.ASK,
            approval_status=ApprovalStatus.APPROVED,
            decision=decision,
        )
        assert context.is_resolved is True
        assert context.is_approved is True

    def test_context_with_ask_verdict_and_rejected(self) -> None:
        proposal = _make_proposal()
        decision = ApprovalDecision(
            proposal_id=proposal.proposal_id,
            status=ApprovalStatus.REJECTED,
            approver="user",
        )
        context = ApprovalContext(
            proposal=proposal,
            policy_verdict=PolicyVerdict.ASK,
            approval_status=ApprovalStatus.REJECTED,
            decision=decision,
        )
        assert context.is_resolved is True
        assert context.is_approved is False

    def test_context_with_ask_verdict_and_pending(self) -> None:
        """ASK verdict with PENDING approval status is not yet resolved."""
        proposal = _make_proposal()
        context = ApprovalContext(
            proposal=proposal,
            policy_verdict=PolicyVerdict.ASK,
            approval_status=ApprovalStatus.PENDING,
        )
        assert context.is_resolved is False
        assert context.is_approved is False

    def test_context_with_ask_verdict_and_deferred(self) -> None:
        proposal = _make_proposal()
        decision = ApprovalDecision(
            proposal_id=proposal.proposal_id,
            status=ApprovalStatus.DEFERRED,
            approver="user",
        )
        context = ApprovalContext(
            proposal=proposal,
            policy_verdict=PolicyVerdict.ASK,
            approval_status=ApprovalStatus.DEFERRED,
            decision=decision,
        )
        assert context.is_resolved is True
        assert context.is_approved is False


# ── Protocol conformance ─────────────────────────────────────────────────────


class TestProtocolConformance:
    """Test that concrete implementations satisfy their protocols."""

    def test_in_memory_approval_gate_satisfies_protocol(self) -> None:
        gate = InMemoryApprovalGate()
        assert isinstance(gate, ApprovalGate)

    def test_proposal_policy_check_satisfies_protocol(self) -> None:
        checker = ProposalPolicyCheck()
        assert isinstance(checker, PolicyCheck)

    def test_in_memory_approval_gate_is_stateless_for_policy(self) -> None:
        """ApprovalGate does not evaluate policy rules."""
        gate = InMemoryApprovalGate()
        proposal = _make_proposal()

        # Gate only records and retrieves decisions
        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.PENDING
        gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)
        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.APPROVED

    def test_policy_check_does_not_invoke_gate(self) -> None:
        """PolicyCheck does not write to ApprovalGate."""
        gate = InMemoryApprovalGate()
        proposal = _make_proposal()
        policy_check = ProposalPolicyCheck()

        # Policy check runs
        verdict = policy_check.check(proposal)

        # Gate is unaffected
        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.PENDING


# ── Integration with ActionProposal model ────────────────────────────────────


class TestActionProposalIntegration:
    """Test that ActionProposal integrates correctly with the contract layer."""

    def test_proposal_id_links_decision(self) -> None:
        """ApprovalDecision is linked to ActionProposal via proposal_id."""
        proposal = _make_proposal(proposal_id="AP-link-test")
        gate = InMemoryApprovalGate()

        gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)
        decision = gate.get_decision("AP-link-test")
        assert decision is not None
        assert decision.proposal_id == "AP-link-test"

    def test_multiple_proposals_independent(self) -> None:
        """Decisions for different proposals are independent."""
        gate = InMemoryApprovalGate()
        proposal1 = _make_proposal(proposal_id="AP-multi-1")
        proposal2 = _make_proposal(proposal_id="AP-multi-2")

        gate.apply_gate(proposal1, "user", ApprovalStatus.APPROVED)
        gate.apply_gate(proposal2, "user", ApprovalStatus.REJECTED)

        assert gate.check_approval("AP-multi-1") == ApprovalStatus.APPROVED
        assert gate.check_approval("AP-multi-2") == ApprovalStatus.REJECTED

    def test_proposal_status_not_modified_by_gate(self) -> None:
        """ApprovalGate does not modify ActionProposal.status."""
        proposal = _make_proposal(status=ProposalStatus.PROPOSED)
        gate = InMemoryApprovalGate()

        gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)
        assert proposal.status == ProposalStatus.PROPOSED

    def test_proposal_risk_passed_to_policy(self) -> None:
        """ActionProposal.risk is used by PolicyCheck."""
        proposal_low = _make_proposal(risk=RiskLevel.LOW)
        proposal_high = _make_proposal(risk=RiskLevel.HIGH)

        # With a policy that allows LOW but denies HIGH
        policy = Policy(
            rules=[],
            default_decision=PolicyDecision.DENY,
        )
        # Add a rule for LOW risk → ALLOW
        from janus.models.policy import PolicyRule
        policy.add_rule(PolicyRule(
            priority=1,
            action=PolicyAction.CREATE,
            risk=RiskLevel.LOW,
            impact=ImpactLevel.LOW,
            decision=PolicyDecision.ALLOW,
        ))

        checker = ProposalPolicyCheck(policy=policy)
        assert checker.check(proposal_low) == PolicyVerdict.ALLOW
        assert checker.check(proposal_high) == PolicyVerdict.DENY
