"""Integration tests for the combined approval gate + policy check flow.

Exercises the full contract-layer flow through ApprovalWorkflow:
    ActionProposal -> PolicyCheck -> (failed -> ApprovalGate) -> ApprovalContext

Covers the 4 scenarios of the approval/policy matrix:
    1. Both pass:       policy passed=True  + approval APPROVED -> approved
    2. Approval fails:  policy passed=True  + approval REJECTED -> approved (policy short-circuits)
    3. Policy fails:    policy passed=False + approval APPROVED -> approved (gate resolves)
    4. Both fail:       policy passed=False + approval REJECTED -> denied

These tests verify the boundary rules: policy check runs first and may
short-circuit (passed=True), in which case the approval gate is never
consulted regardless of any recorded decision.
"""

from __future__ import annotations

from janus.models.policy import Policy, PolicyDecision, RiskLevel
from janus.proposal import (
    ActionProposal,
    ActionType,
    ApprovalStatus,
    ApprovalWorkflow,
    InMemoryApprovalGate,
    ProposalPolicyCheck,
)
from janus.proposal.approval_contract import PolicyCheckResult


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


def _make_pass_policy() -> Policy:
    """Policy that passes everything (ALLOW)."""
    return Policy(rules=[], default_decision=PolicyDecision.ALLOW, name="pass_all")


def _make_fail_policy() -> Policy:
    """Policy that fails everything (DENY)."""
    return Policy(rules=[], default_decision=PolicyDecision.DENY, name="fail_all")


# ── Scenario 1: Both pass ────────────────────────────────────────────────────


class TestBothPass:
    """Policy passed=True + approval APPROVED -> approved."""

    def test_pass_policy_with_approved_gate(self) -> None:
        """When policy passes and gate has APPROVED, result is approved."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck(policy=_make_pass_policy())
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal()

        gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)
        context = workflow.evaluate(proposal)

        assert context.policy_result.passed is True
        assert context.is_approved is True
        assert context.is_resolved is True


# ── Scenario 2: Approval fails but policy passes ─────────────────────────────


class TestApprovalFailsPolicyPasses:
    """Policy passed=True + approval REJECTED -> approved (policy short-circuits)."""

    def test_pass_policy_with_rejected_gate(self) -> None:
        """When policy passes, gate REJECTED decision is ignored."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck(policy=_make_pass_policy())
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal()

        gate.apply_gate(proposal, "user", ApprovalStatus.REJECTED)
        context = workflow.evaluate(proposal)

        # Policy passed short-circuits — gate decision is not consulted
        assert context.policy_result.passed is True
        assert context.is_approved is True
        assert context.is_resolved is True
        assert context.decision is None

    def test_pass_policy_with_deferred_gate(self) -> None:
        """When policy passes, gate DEFERRED decision is ignored."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck(policy=_make_pass_policy())
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal()

        gate.apply_gate(proposal, "user", ApprovalStatus.DEFERRED)
        context = workflow.evaluate(proposal)

        assert context.policy_result.passed is True
        assert context.is_approved is True
        assert context.is_resolved is True
        assert context.decision is None


# ── Scenario 3: Approval passes but policy fails ─────────────────────────────


class TestApprovalPassesPolicyFails:
    """Policy passed=False + approval APPROVED -> approved (gate resolves)."""

    def test_fail_policy_with_approved_gate(self) -> None:
        """When policy fails but gate has APPROVED, result is approved."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck(policy=_make_fail_policy())
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal()

        gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)
        context = workflow.evaluate(proposal)

        # Policy failed, but gate resolved with APPROVED
        assert context.policy_result.passed is False
        assert context.approval_status == ApprovalStatus.APPROVED
        assert context.is_approved is True
        assert context.is_resolved is True
        assert context.decision is not None
        assert context.decision.status == ApprovalStatus.APPROVED


# ── Scenario 4: Both fail ────────────────────────────────────────────────────


class TestBothFail:
    """Policy passed=False + approval REJECTED -> denied."""

    def test_fail_policy_with_rejected_gate(self) -> None:
        """When policy fails and gate has REJECTED, result is denied."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck(policy=_make_fail_policy())
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal()

        gate.apply_gate(proposal, "user", ApprovalStatus.REJECTED)
        context = workflow.evaluate(proposal)

        assert context.policy_result.passed is False
        assert context.approval_status == ApprovalStatus.REJECTED
        assert context.is_approved is False
        assert context.is_resolved is True
        assert context.decision is not None
        assert context.decision.status == ApprovalStatus.REJECTED


# ── ASK flow: policy requires approval, gate resolves ─────────────────────────


class TestAskFlow:
    """Policy passed=False (ASK) -> gate is consulted for human decision."""

    def test_fail_policy_with_approved_gate(self) -> None:
        """Policy failed (ASK) + gate APPROVED -> approved."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck(
            policy=Policy(rules=[], default_decision=PolicyDecision.ASK, name="ask_all")
        )
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal()

        gate.apply_gate(proposal, "user", ApprovalStatus.APPROVED)
        context = workflow.evaluate(proposal)

        assert context.policy_result.passed is False
        assert context.approval_status == ApprovalStatus.APPROVED
        assert context.is_approved is True
        assert context.is_resolved is True
        assert context.decision is not None
        assert context.decision.status == ApprovalStatus.APPROVED

    def test_fail_policy_with_rejected_gate(self) -> None:
        """Policy failed (ASK) + gate REJECTED -> denied."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck(
            policy=Policy(rules=[], default_decision=PolicyDecision.ASK, name="ask_all")
        )
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal()

        gate.apply_gate(proposal, "user", ApprovalStatus.REJECTED)
        context = workflow.evaluate(proposal)

        assert context.policy_result.passed is False
        assert context.approval_status == ApprovalStatus.REJECTED
        assert context.is_approved is False
        assert context.is_resolved is True
        assert context.decision is not None
        assert context.decision.status == ApprovalStatus.REJECTED

    def test_fail_policy_with_no_decision(self) -> None:
        """Policy failed (ASK) + no gate decision -> pending (not resolved)."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck(
            policy=Policy(rules=[], default_decision=PolicyDecision.ASK, name="ask_all")
        )
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal()

        context = workflow.evaluate(proposal)

        assert context.policy_result.passed is False
        assert context.approval_status == ApprovalStatus.PENDING
        assert context.is_approved is False
        assert context.is_resolved is False
        assert context.decision is None
