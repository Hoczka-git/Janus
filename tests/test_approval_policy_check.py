"""Tests for the ProposalPolicyCheck implementation.

Covers:
- Valid proposal passes (low risk)
- High-risk proposal requires approval (fails policy check)
- Protocol conformance
- Determinism
- Side-effect free
- Action type and risk level mapping
"""

from __future__ import annotations

from janus.models.policy import RiskLevel
from janus.proposal import (
    ActionProposal,
    ActionType,
    PolicyCheck,
    PolicyCheckResult,
    ProposalPolicyCheck,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_proposal(
    action_type: ActionType = ActionType.CREATE_TASK,
    risk: RiskLevel = RiskLevel.LOW,
) -> ActionProposal:
    """Create a minimal ActionProposal for testing."""
    return ActionProposal(
        proposal_id="AP-test",
        action_type=action_type,
        reason="Test proposal",
        risk=risk,
    )


# ── Protocol conformance ─────────────────────────────────────────────────────


class TestPolicyCheckProtocol:
    def test_is_policy_check(self) -> None:
        checker = ProposalPolicyCheck()
        assert isinstance(checker, PolicyCheck)

    def test_has_check_method(self) -> None:
        checker = ProposalPolicyCheck()
        assert hasattr(checker, "check")
        assert callable(checker.check)

    def test_check_returns_policy_check_result(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal()
        result = checker.check(proposal)
        assert isinstance(result, PolicyCheckResult)


# ── Valid proposal passes ────────────────────────────────────────────────────


class TestValidProposal:
    def test_low_risk_create_passes(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.CREATE_TASK,
            risk=RiskLevel.LOW,
        )
        result = checker.check(proposal)
        assert result.passed is True

    def test_low_risk_update_passes(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.UPDATE_TASK,
            risk=RiskLevel.LOW,
        )
        result = checker.check(proposal)
        assert result.passed is True

    def test_low_risk_calendar_event_passes(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.CREATE_CALENDAR_EVENT,
            risk=RiskLevel.LOW,
        )
        result = checker.check(proposal)
        assert result.passed is True


# ── Risk-based verdicts ──────────────────────────────────────────────────────


class TestRiskBasedVerdicts:
    def test_high_risk_create_requires_approval(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.CREATE_TASK,
            risk=RiskLevel.HIGH,
        )
        result = checker.check(proposal)
        assert result.passed is False
        assert result.reason is not None

    def test_medium_risk_update_requires_approval(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.UPDATE_TASK,
            risk=RiskLevel.MEDIUM,
        )
        result = checker.check(proposal)
        assert result.passed is False
        assert result.reason is not None

    def test_high_risk_reschedule_requires_approval(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.RESCHEDULE_TASK,
            risk=RiskLevel.HIGH,
        )
        result = checker.check(proposal)
        assert result.passed is False
        assert result.reason is not None


# ── Determinism ──────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_proposal_same_result(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal()
        result1 = checker.check(proposal)
        result2 = checker.check(proposal)
        assert result1.passed == result2.passed
        assert result1.reason == result2.reason

    def test_multiple_calls_consistent(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal()
        results = [checker.check(proposal) for _ in range(10)]
        assert all(r.passed == results[0].passed for r in results)
        assert all(r.reason == results[0].reason for r in results)


# ── Side-effect free ─────────────────────────────────────────────────────────


class TestSideEffectFree:
    def test_proposal_not_modified(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.CREATE_TASK,
            risk=RiskLevel.LOW,
        )
        original_action_type = proposal.action_type
        original_risk = proposal.risk
        original_status = proposal.status

        checker.check(proposal)

        assert proposal.action_type == original_action_type
        assert proposal.risk == original_risk
        assert proposal.status == original_status

    def test_no_global_state_mutated(self) -> None:
        checker = ProposalPolicyCheck()
        proposal = _make_proposal()
        checker.check(proposal)
        # A second checker should behave identically
        checker2 = ProposalPolicyCheck()
        result1 = checker.check(proposal)
        result2 = checker2.check(proposal)
        assert result1.passed == result2.passed
        assert result1.reason == result2.reason
