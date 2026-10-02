"""Tests for the policy check module.

Covers:
- ProposalPolicyCheck implements PolicyCheck protocol
- ActionType → PolicyAction mapping
- Risk-based verdicts (LOW → ALLOW, MEDIUM → ASK, HIGH → ASK/DENY)
- Determinism (same input → same output)
- Side-effect free (proposal not modified)
- Integration with ApprovalContext
"""

from __future__ import annotations

from janus.models.policy import (
    ImpactLevel,
    Policy,
    PolicyAction,
    PolicyDecision,
    PolicyRule,
    RiskLevel,
    create_default_policy,
)
from janus.models.policy_p1 import PolicyVerdict
from janus.proposal import ActionProposal, ActionType, ProposalStatus
from janus.proposal.approval_contract import (
    ApprovalContext,
    ApprovalDecision,
    ApprovalGate,
    ApprovalStatus,
    PolicyCheck,
)
from janus.proposal.policy_check import ProposalPolicyCheck


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_proposal(
    action_type: ActionType = ActionType.CREATE_TASK,
    risk: RiskLevel = RiskLevel.LOW,
    **kwargs,
) -> ActionProposal:
    """Create a minimal ActionProposal for testing."""
    defaults = {
        "proposal_id": "AP-test",
        "action_type": action_type,
        "reason": "Test proposal",
        "risk": risk,
    }
    defaults.update(kwargs)
    return ActionProposal(**defaults)


# ── Protocol conformance ─────────────────────────────────────────────────────


class TestPolicyCheckProtocol:
    def test_is_policy_check(self) -> None:
        checker = ProposalPolicyCheck()
        assert isinstance(checker, PolicyCheck)

    def test_has_check_method(self) -> None:
        checker = ProposalPolicyCheck()
        assert hasattr(checker, "check")
        assert callable(checker.check)

    def test_check_returns_policy_verdict(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal()
        result = checker.check(proposal)
        assert isinstance(result, PolicyVerdict)

    def test_no_approval_recording_methods(self) -> None:
        checker = ProposalPolicyCheck()
        assert not hasattr(checker, "record_decision")
        assert not hasattr(checker, "check_approval")
        assert not hasattr(checker, "get_decision")


# ── ActionType → PolicyAction mapping ────────────────────────────────────────


class TestActionTypeMapping:
    def test_create_task_maps_to_create(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(action_type=ActionType.CREATE_TASK)
        # CREATE_TASK with LOW risk → ALLOW
        assert checker.check(proposal) == PolicyVerdict.ALLOW

    def test_update_task_maps_to_update(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(action_type=ActionType.UPDATE_TASK)
        # UPDATE_TASK with LOW risk → ALLOW
        assert checker.check(proposal) == PolicyVerdict.ALLOW

    def test_reschedule_task_maps_to_update(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(action_type=ActionType.RESCHEDULE_TASK)
        # RESCHEDULE_TASK with LOW risk → ALLOW
        assert checker.check(proposal) == PolicyVerdict.ALLOW

    def test_change_priority_maps_to_update(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(action_type=ActionType.CHANGE_PRIORITY)
        # CHANGE_PRIORITY with LOW risk → ALLOW
        assert checker.check(proposal) == PolicyVerdict.ALLOW

    def test_create_calendar_event_maps_to_create(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(action_type=ActionType.CREATE_CALENDAR_EVENT)
        # CREATE_CALENDAR_EVENT with LOW risk → ALLOW
        assert checker.check(proposal) == PolicyVerdict.ALLOW


# ── Risk-based verdicts ──────────────────────────────────────────────────────


class TestRiskBasedVerdicts:
    def test_low_risk_create_returns_allow(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.CREATE_TASK,
            risk=RiskLevel.LOW,
        )
        assert checker.check(proposal) == PolicyVerdict.ALLOW

    def test_medium_risk_create_returns_ask(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.CREATE_TASK,
            risk=RiskLevel.MEDIUM,
        )
        assert checker.check(proposal) == PolicyVerdict.ASK

    def test_high_risk_create_returns_ask(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.CREATE_TASK,
            risk=RiskLevel.HIGH,
        )
        assert checker.check(proposal) == PolicyVerdict.ASK

    def test_low_risk_update_returns_allow(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.UPDATE_TASK,
            risk=RiskLevel.LOW,
        )
        assert checker.check(proposal) == PolicyVerdict.ALLOW

    def test_medium_risk_update_returns_ask(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.UPDATE_TASK,
            risk=RiskLevel.MEDIUM,
        )
        assert checker.check(proposal) == PolicyVerdict.ASK

    def test_high_risk_update_returns_ask(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.UPDATE_TASK,
            risk=RiskLevel.HIGH,
        )
        assert checker.check(proposal) == PolicyVerdict.ASK


# ── Determinism ──────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_proposal_same_verdict(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.CREATE_TASK,
            risk=RiskLevel.MEDIUM,
        )
        result1 = checker.check(proposal)
        result2 = checker.check(proposal)
        assert result1 == result2

    def test_multiple_calls_consistent(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.UPDATE_TASK,
            risk=RiskLevel.HIGH,
        )
        results = [checker.check(proposal) for _ in range(10)]
        assert all(r == results[0] for r in results)


# ── Side-effect free ─────────────────────────────────────────────────────────


class TestSideEffectFree:
    def test_proposal_not_modified(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.CREATE_TASK,
            risk=RiskLevel.MEDIUM,
            parameters={"title": "Test"},
            metadata={"key": "value"},
        )
        original_params = dict(proposal.parameters)
        original_metadata = dict(proposal.metadata)
        original_status = proposal.status
        original_risk = proposal.risk

        checker.check(proposal)

        assert proposal.parameters == original_params
        assert proposal.metadata == original_metadata
        assert proposal.status == original_status
        assert proposal.risk == original_risk

    def test_no_global_state_mutated(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal()
        checker.check(proposal)
        # A second checker with default policy should behave identically
        checker2 = ProposalPolicyCheck()
        assert checker2.check(proposal) == checker.check(proposal)


# ── Custom policy ────────────────────────────────────────────────────────────


class TestCustomPolicy:
    def test_custom_policy_overrides_default(self) -> None:
        """A custom policy can change the verdict."""
        custom_policy = Policy(
            rules=[
                PolicyRule(
                    action=PolicyAction.CREATE,
                    risk=RiskLevel.LOW,
                    impact=None,
                    decision=PolicyDecision.DENY,
                    description="Deny all creates",
                    priority=1,
                ),
            ],
            default_decision=PolicyDecision.ALLOW,
            name="custom",
        )
        checker = ProposalPolicyCheck(policy=custom_policy)
        proposal = _make_proposal(
            action_type=ActionType.CREATE_TASK,
            risk=RiskLevel.LOW,
        )
        assert checker.check(proposal) == PolicyVerdict.DENY

    def test_custom_policy_with_no_matching_rules(self) -> None:
        """When no rules match, the default decision is used."""
        custom_policy = Policy(
            rules=[],
            default_decision=PolicyDecision.ALLOW,
            name="permissive",
        )
        checker = ProposalPolicyCheck(policy=custom_policy)
        proposal = _make_proposal(
            action_type=ActionType.CREATE_TASK,
            risk=RiskLevel.HIGH,
        )
        assert checker.check(proposal) == PolicyVerdict.ALLOW


# ── Integration with ApprovalContext ─────────────────────────────────────────


class TestApprovalContextIntegration:
    def test_allow_produces_resolved_context(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(risk=RiskLevel.LOW)
        verdict = checker.check(proposal)
        ctx = ApprovalContext(
            proposal=proposal,
            policy_verdict=verdict,
        )
        assert ctx.is_resolved is True
        assert ctx.is_approved is True

    def test_ask_produces_unresolved_context(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(risk=RiskLevel.MEDIUM)
        verdict = checker.check(proposal)
        ctx = ApprovalContext(
            proposal=proposal,
            policy_verdict=verdict,
        )
        assert ctx.is_resolved is False
        assert ctx.is_approved is False

    def test_ask_resolved_by_approval_gate(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(risk=RiskLevel.MEDIUM)
        verdict = checker.check(proposal)
        decision = ApprovalDecision(
            proposal_id=proposal.proposal_id,
            status=ApprovalStatus.APPROVED,
            approver="user",
        )
        ctx = ApprovalContext(
            proposal=proposal,
            policy_verdict=verdict,
            approval_status=ApprovalStatus.APPROVED,
            decision=decision,
        )
        assert ctx.is_resolved is True
        assert ctx.is_approved is True

    def test_deny_produces_resolved_not_approved(self) -> None:
        custom_policy = Policy(
            rules=[
                PolicyRule(
                    action=PolicyAction.CREATE,
                    risk=None,
                    impact=None,
                    decision=PolicyDecision.DENY,
                    description="Deny all",
                    priority=1,
                ),
            ],
            default_decision=PolicyDecision.ALLOW,
            name="restrictive",
        )
        checker = ProposalPolicyCheck(policy=custom_policy)
        proposal = _make_proposal(risk=RiskLevel.LOW)
        verdict = checker.check(proposal)
        ctx = ApprovalContext(
            proposal=proposal,
            policy_verdict=verdict,
        )
        assert ctx.is_resolved is True
        assert ctx.is_approved is False


# ── Edge cases ───────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_parameters(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(parameters={})
        result = checker.check(proposal)
        assert isinstance(result, PolicyVerdict)

    def test_empty_metadata(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(metadata={})
        result = checker.check(proposal)
        assert isinstance(result, PolicyVerdict)

    def test_all_action_types_produce_valid_verdicts(self) -> None:
        checker = ProposalPolicyCheck()
        for action_type in ActionType:
            proposal = _make_proposal(action_type=action_type)
            result = checker.check(proposal)
            assert isinstance(result, PolicyVerdict)
            assert result in (PolicyVerdict.ALLOW, PolicyVerdict.ASK, PolicyVerdict.DENY)

    def test_all_risk_levels_produce_valid_verdicts(self) -> None:
        checker = ProposalPolicyCheck()
        for risk in RiskLevel:
            proposal = _make_proposal(risk=risk)
            result = checker.check(proposal)
            assert isinstance(result, PolicyVerdict)
            assert result in (PolicyVerdict.ALLOW, PolicyVerdict.ASK, PolicyVerdict.DENY)
