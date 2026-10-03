"""Integration tests for the combined approval gate + policy check flow.

Exercises the full contract-layer flow through ApprovalWorkflow:
    ActionProposal -> PolicyCheck -> (ASK -> ApprovalGate) -> ApprovalContext

Covers the 4 scenarios of the approval/policy matrix:
    1. Both pass:       policy ALLOW  + approval APPROVED -> approved
    2. Approval fails:  policy ALLOW  + approval REJECTED -> approved (policy wins)
    3. Policy fails:    policy DENY   + approval APPROVED -> denied  (policy wins)
    4. Both fail:       policy DENY   + approval REJECTED -> denied

These tests verify the boundary rules: policy check runs first and may
short-circuit (ALLOW/DENY), in which case the approval gate is never
consulted regardless of any recorded decision.
"""

from __future__ import annotations

from janus.models.policy import Policy, PolicyDecision, RiskLevel
from janus.models.policy_p1 import PolicyVerdict
from janus.proposal import (
    ActionProposal,
    ActionType,
    ApprovalStatus,
    ApprovalWorkflow,
    InMemoryApprovalGate,
    ProposalPolicyCheck,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_proposal(
    proposal_id: str = "AP-int-001",
    risk: RiskLevel = RiskLevel.LOW,
) -> ActionProposal:
    """Create a minimal valid ActionProposal for testing."""
    return ActionProposal(
        proposal_id=proposal_id,
        action_type=ActionType.CREATE_TASK,
        reason="Integration test proposal",
        source="test",
        risk=risk,
    )


def _make_allow_policy() -> Policy:
    """Policy that allows everything."""
    return Policy(rules=[], default_decision=PolicyDecision.ALLOW, name="allow_all")


def _make_deny_policy() -> Policy:
    """Policy that denies everything."""
    return Policy(rules=[], default_decision=PolicyDecision.DENY, name="deny_all")


# ── Scenario 1: Both pass ────────────────────────────────────────────────────


class TestBothPass:
    """Policy ALLOW + approval APPROVED -> approved."""

    def test_allow_policy_with_approved_gate(self) -> None:
        """When policy returns ALLOW and gate has APPROVED, result is approved."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck(policy=_make_allow_policy())
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal()

        gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)
        context = workflow.evaluate(proposal)

        assert context.policy_verdict == PolicyVerdict.ALLOW
        assert context.is_approved is True
        assert context.is_resolved is True


# ── Scenario 2: Approval fails but policy passes ─────────────────────────────


class TestApprovalFailsPolicyPasses:
    """Policy ALLOW + approval REJECTED -> approved (policy short-circuits)."""

    def test_allow_policy_with_rejected_gate(self) -> None:
        """When policy returns ALLOW, gate REJECTED decision is ignored."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck(policy=_make_allow_policy())
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal()

        gate.apply_gate(proposal, "user", ApprovalStatus.REJECTED)
        context = workflow.evaluate(proposal)

        # Policy ALLOW short-circuits — gate decision is not consulted
        assert context.policy_verdict == PolicyVerdict.ALLOW
        assert context.is_approved is True
        assert context.is_resolved is True
        assert context.decision is None

    def test_allow_policy_with_deferred_gate(self) -> None:
        """When policy returns ALLOW, gate DEFERRED decision is ignored."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck(policy=_make_allow_policy())
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal()

        gate.apply_gate(proposal, "user", ApprovalStatus.DEFERRED)
        context = workflow.evaluate(proposal)

        assert context.policy_verdict == PolicyVerdict.ALLOW
        assert context.is_approved is True
        assert context.is_resolved is True
        assert context.decision is None


# ── Scenario 3: Approval passes but policy fails ─────────────────────────────


class TestApprovalPassesPolicyFails:
    """Policy DENY + approval APPROVED -> denied (policy short-circuits)."""

    def test_deny_policy_with_approved_gate(self) -> None:
        """When policy returns DENY, gate APPROVED decision is ignored."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck(policy=_make_deny_policy())
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal()

        gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)
        context = workflow.evaluate(proposal)

        # Policy DENY short-circuits — gate decision is not consulted
        assert context.policy_verdict == PolicyVerdict.DENY
        assert context.is_approved is False
        assert context.is_resolved is True
        assert context.decision is None


# ── Scenario 4: Both fail ────────────────────────────────────────────────────


class TestBothFail:
    """Policy DENY + approval REJECTED -> denied."""

    def test_deny_policy_with_rejected_gate(self) -> None:
        """When policy returns DENY and gate has REJECTED, result is denied."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck(policy=_make_deny_policy())
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal()

        gate.apply_gate(proposal, "user", ApprovalStatus.REJECTED)
        context = workflow.evaluate(proposal)

        assert context.policy_verdict == PolicyVerdict.DENY
        assert context.is_approved is False
        assert context.is_resolved is True
        assert context.decision is None


# ── ASK flow: policy requires approval, gate resolves ─────────────────────────


class TestAskFlow:
    """Policy ASK -> gate is consulted for human decision."""

    def test_ask_policy_with_approved_gate(self) -> None:
        """Policy ASK + gate APPROVED -> approved."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck(
            policy=Policy(rules=[], default_decision=PolicyDecision.ASK, name="ask_all")
        )
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal()

        gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)
        context = workflow.evaluate(proposal)

        assert context.policy_verdict == PolicyVerdict.ASK
        assert context.approval_status == ApprovalStatus.APPROVED
        assert context.is_approved is True
        assert context.is_resolved is True
        assert context.decision is not None
        assert context.decision.status == ApprovalStatus.APPROVED

    def test_ask_policy_with_rejected_gate(self) -> None:
        """Policy ASK + gate REJECTED -> denied."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck(
            policy=Policy(rules=[], default_decision=PolicyDecision.ASK, name="ask_all")
        )
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal()

        gate.apply_gate(proposal, "user", ApprovalStatus.REJECTED)
        context = workflow.evaluate(proposal)

        assert context.policy_verdict == PolicyVerdict.ASK
        assert context.approval_status == ApprovalStatus.REJECTED
        assert context.is_approved is False
        assert context.is_resolved is True
        assert context.decision is not None
        assert context.decision.status == ApprovalStatus.REJECTED

    def test_ask_policy_with_no_decision(self) -> None:
        """Policy ASK + no gate decision -> pending (not resolved)."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck(
            policy=Policy(rules=[], default_decision=PolicyDecision.ASK, name="ask_all")
        )
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal()

        context = workflow.evaluate(proposal)

        assert context.policy_verdict == PolicyVerdict.ASK
        assert context.approval_status == ApprovalStatus.PENDING
        assert context.is_approved is False
        assert context.is_resolved is False
        assert context.decision is None
