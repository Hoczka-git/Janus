"""Tests for the ApprovalWorkflow — the wiring layer between approval gate and policy check.

Covers:
- ALLOW flow: gate not invoked, context returned
- ASK flow with no decision: gate checked, PENDING status
- ASK flow with decision: gate checked, decision included
- DENY flow: gate not invoked, context returned
- Integration with ActionProposal model
- Package-level export of ApprovalWorkflow
"""

from __future__ import annotations

from janus.models.policy import RiskLevel
from janus.models.policy_p1 import PolicyVerdict
from janus.proposal import (
    ActionProposal,
    ActionType,
    ApprovalContext,
    ApprovalDecision,
    ApprovalGate,
    ApprovalStatus,
    ApprovalWorkflow,
    InMemoryApprovalGate,
    PolicyCheck,
    ProposalPolicyCheck,
    ProposalStatus,
)
from janus.proposal.approval_contract import (
    ApprovalGate as ApprovalGateProtocol,
    PolicyCheck as PolicyCheckProtocol,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_proposal(
    proposal_id: str = "AP-001",
    action_type: ActionType = ActionType.CREATE_TASK,
    risk: RiskLevel = RiskLevel.LOW,
) -> ActionProposal:
    """Create a minimal valid ActionProposal for testing."""
    return ActionProposal(
        proposal_id=proposal_id,
        action_type=action_type,
        reason="Test proposal",
        source="test",
        risk=risk,
    )


# ── Package export ───────────────────────────────────────────────────────────


class TestApprovalWorkflowExport:
    def test_approval_workflow_exported(self) -> None:
        assert ApprovalWorkflow is not None

    def test_approval_workflow_instantiable(self) -> None:
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck()
        workflow = ApprovalWorkflow(gate, checker)
        assert workflow.approval_gate is gate
        assert workflow.policy_check is checker


# ── ALLOW flow ───────────────────────────────────────────────────────────────


class TestAllowFlow:
    def test_allow_skips_gate(self) -> None:
        """ALLOW verdict should not invoke the approval gate."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck()
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal(risk=RiskLevel.LOW)

        context = workflow.evaluate(proposal)

        assert context.policy_verdict == PolicyVerdict.ALLOW
        assert context.approval_status == ApprovalStatus.PENDING
        assert context.decision is None
        assert context.is_resolved is True
        assert context.is_approved is True

    def test_allow_does_not_record_decision(self) -> None:
        """ALLOW flow should not create any gate decisions."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck()
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal(risk=RiskLevel.LOW)

        workflow.evaluate(proposal)

        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.PENDING
        assert gate.get_decision(proposal.proposal_id) is None


# ── ASK flow ─────────────────────────────────────────────────────────────────


class TestAskFlow:
    def test_ask_with_no_decision(self) -> None:
        """ASK verdict with no recorded decision should return PENDING."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck()
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal(risk=RiskLevel.HIGH)

        context = workflow.evaluate(proposal)

        assert context.policy_verdict == PolicyVerdict.ASK
        assert context.approval_status == ApprovalStatus.PENDING
        assert context.decision is None
        assert context.is_resolved is False
        assert context.is_approved is False

    def test_ask_with_approved_decision(self) -> None:
        """ASK verdict with approved decision should return APPROVED."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck()
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal(risk=RiskLevel.HIGH)

        gate.record_decision(
            ApprovalDecision(
                proposal_id=proposal.proposal_id,
                status=ApprovalStatus.APPROVED,
                approver="user",
            )
        )

        context = workflow.evaluate(proposal)

        assert context.policy_verdict == PolicyVerdict.ASK
        assert context.approval_status == ApprovalStatus.APPROVED
        assert context.decision is not None
        assert context.decision.approver == "user"
        assert context.is_resolved is True
        assert context.is_approved is True

    def test_ask_with_rejected_decision(self) -> None:
        """ASK verdict with rejected decision should return REJECTED."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck()
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal(risk=RiskLevel.HIGH)

        gate.record_decision(
            ApprovalDecision(
                proposal_id=proposal.proposal_id,
                status=ApprovalStatus.REJECTED,
                approver="user",
            )
        )

        context = workflow.evaluate(proposal)

        assert context.policy_verdict == PolicyVerdict.ASK
        assert context.approval_status == ApprovalStatus.REJECTED
        assert context.decision is not None
        assert context.is_resolved is True
        assert context.is_approved is False

    def test_ask_with_deferred_decision(self) -> None:
        """ASK verdict with deferred decision should return DEFERRED."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck()
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal(risk=RiskLevel.HIGH)

        gate.record_decision(
            ApprovalDecision(
                proposal_id=proposal.proposal_id,
                status=ApprovalStatus.DEFERRED,
                approver="user",
            )
        )

        context = workflow.evaluate(proposal)

        assert context.policy_verdict == PolicyVerdict.ASK
        assert context.approval_status == ApprovalStatus.DEFERRED
        assert context.decision is not None
        assert context.is_resolved is True
        assert context.is_approved is False


# ── DENY flow ────────────────────────────────────────────────────────────────


class TestDenyFlow:
    def test_deny_skips_gate(self) -> None:
        """DENY verdict should not invoke the approval gate."""
        gate = InMemoryApprovalGate()
        # Use a custom policy that denies CREATE_TASK with HIGH risk
        from janus.models.policy import (
            ImpactLevel,
            Policy,
            PolicyAction,
            PolicyDecision,
            PolicyRule,
        )
        custom_policy = Policy(
            rules=[
                PolicyRule(
                    action=PolicyAction.CREATE,
                    risk=RiskLevel.HIGH,
                    impact=None,
                    decision=PolicyDecision.DENY,
                    description="High-risk creates are denied",
                    priority=10,
                ),
            ],
            default_decision=PolicyDecision.ALLOW,
            name="test_deny",
        )
        checker = ProposalPolicyCheck(policy=custom_policy)
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal(risk=RiskLevel.HIGH)

        context = workflow.evaluate(proposal)

        assert context.policy_verdict == PolicyVerdict.DENY
        assert context.approval_status == ApprovalStatus.PENDING
        assert context.decision is None
        assert context.is_resolved is True
        assert context.is_approved is False

    def test_deny_does_not_record_decision(self) -> None:
        """DENY flow should not create any gate decisions."""
        gate = InMemoryApprovalGate()
        from janus.models.policy import (
            ImpactLevel,
            Policy,
            PolicyAction,
            PolicyDecision,
            PolicyRule,
        )
        custom_policy = Policy(
            rules=[
                PolicyRule(
                    action=PolicyAction.CREATE,
                    risk=RiskLevel.HIGH,
                    impact=None,
                    decision=PolicyDecision.DENY,
                    description="High-risk creates are denied",
                    priority=10,
                ),
            ],
            default_decision=PolicyDecision.ALLOW,
            name="test_deny",
        )
        checker = ProposalPolicyCheck(policy=custom_policy)
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal(risk=RiskLevel.HIGH)

        workflow.evaluate(proposal)

        assert gate.check_approval(proposal.proposal_id) == ApprovalStatus.PENDING
        assert gate.get_decision(proposal.proposal_id) is None


# ── Integration with ActionProposal ──────────────────────────────────────────


class TestActionProposalIntegration:
    def test_proposal_passed_through(self) -> None:
        """The same ActionProposal instance should be returned in the context."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck()
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal()

        context = workflow.evaluate(proposal)

        assert context.proposal is proposal

    def test_proposal_id_used_for_gate_lookup(self) -> None:
        """The workflow should use proposal_id to look up gate decisions."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck()
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal(proposal_id="AP-unique-123", risk=RiskLevel.HIGH)

        gate.record_decision(
            ApprovalDecision(
                proposal_id="AP-unique-123",
                status=ApprovalStatus.APPROVED,
                approver="admin",
            )
        )

        context = workflow.evaluate(proposal)

        assert context.decision is not None
        assert context.decision.proposal_id == "AP-unique-123"
        assert context.decision.approver == "admin"

    def test_multiple_proposals_independent(self) -> None:
        """Different proposals should have independent gate lookups."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck()
        workflow = ApprovalWorkflow(gate, checker)

        p1 = _make_proposal(proposal_id="AP-1", risk=RiskLevel.HIGH)
        p2 = _make_proposal(proposal_id="AP-2", risk=RiskLevel.HIGH)

        gate.record_decision(
            ApprovalDecision(
                proposal_id="AP-1",
                status=ApprovalStatus.APPROVED,
                approver="user",
            )
        )

        ctx1 = workflow.evaluate(p1)
        ctx2 = workflow.evaluate(p2)

        assert ctx1.is_approved is True
        assert ctx2.is_approved is False
        assert ctx2.approval_status == ApprovalStatus.PENDING


# ── Boundary enforcement ─────────────────────────────────────────────────────


class TestBoundaryEnforcement:
    def test_workflow_does_not_mutate_proposal(self) -> None:
        """The workflow should not modify the ActionProposal."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck()
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal(risk=RiskLevel.LOW)

        original_status = proposal.status
        workflow.evaluate(proposal)

        assert proposal.status == original_status

    def test_workflow_does_not_record_decisions(self) -> None:
        """The workflow should not record decisions in the gate."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck()
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal(risk=RiskLevel.LOW)

        workflow.evaluate(proposal)

        assert len(gate) == 0

    def test_workflow_is_pure(self) -> None:
        """The workflow should be deterministic and side-effect free."""
        gate = InMemoryApprovalGate()
        checker = ProposalPolicyCheck()
        workflow = ApprovalWorkflow(gate, checker)
        proposal = _make_proposal(risk=RiskLevel.LOW)

        ctx1 = workflow.evaluate(proposal)
        ctx2 = workflow.evaluate(proposal)

        assert ctx1.policy_verdict == ctx2.policy_verdict
        assert ctx1.approval_status == ctx2.approval_status
        assert ctx1.is_approved == ctx2.is_approved
