"""Tests for the ApprovalPolicyCheck implementation.

Covers:
- Valid proposal passes
- Empty action type fails
- Empty target fails
- Protocol conformance
- Determinism
- Side-effect free
"""

from __future__ import annotations

from janus.proposal import ActionProposal, ActionType
from janus.proposal.approval import (
    ApprovalPolicyCheck,
    PolicyCheck,
    PolicyCheckResult,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_proposal(
    action_type: ActionType | str | None = ActionType.CREATE_TASK,
    target_id: str | None = "task-123",
) -> ActionProposal:
    """Create a minimal ActionProposal for testing."""
    return ActionProposal(
        proposal_id="AP-test",
        action_type=action_type,  # type: ignore[arg-type]
        target_id=target_id,
        reason="Test proposal",
    )


# ── Protocol conformance ─────────────────────────────────────────────────────


class TestPolicyCheckProtocol:
    def test_is_policy_check(self) -> None:
        checker = ApprovalPolicyCheck()
        assert isinstance(checker, PolicyCheck)

    def test_has_check_method(self) -> None:
        checker = ApprovalPolicyCheck()
        assert hasattr(checker, "check")
        assert callable(checker.check)

    def test_check_returns_policy_check_result(self) -> None:
        checker = ApprovalPolicyCheck()
        proposal = _make_proposal()
        result = checker.check(proposal)
        assert isinstance(result, PolicyCheckResult)


# ── Valid proposal passes ────────────────────────────────────────────────────


class TestValidProposal:
    def test_valid_proposal_passes(self) -> None:
        checker = ApprovalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.CREATE_TASK,
            target_id="task-123",
        )
        result = checker.check(proposal)
        assert result.allowed is True
        assert result.reason != ""
        assert result.rule_id == "basic_policy"

    def test_valid_proposal_with_different_action_type(self) -> None:
        checker = ApprovalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.UPDATE_TASK,
            target_id="task-456",
        )
        result = checker.check(proposal)
        assert result.allowed is True

    def test_valid_proposal_with_calendar_event(self) -> None:
        checker = ApprovalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.CREATE_CALENDAR_EVENT,
            target_id="event-789",
        )
        result = checker.check(proposal)
        assert result.allowed is True


# ── Empty action type fails ─────────────────────────────────────────────────


class TestEmptyActionType:
    def test_none_action_type_fails(self) -> None:
        checker = ApprovalPolicyCheck()
        proposal = _make_proposal(action_type=None)  # type: ignore[arg-type]
        result = checker.check(proposal)
        assert result.allowed is False
        assert "action type" in result.reason.lower()
        assert result.rule_id == "action_type_required"

    def test_empty_string_action_type_fails(self) -> None:
        checker = ApprovalPolicyCheck()
        proposal = _make_proposal(action_type="")  # type: ignore[arg-type]
        result = checker.check(proposal)
        assert result.allowed is False
        assert "action type" in result.reason.lower()

    def test_whitespace_action_type_fails(self) -> None:
        checker = ApprovalPolicyCheck()
        proposal = _make_proposal(action_type="   ")  # type: ignore[arg-type]
        result = checker.check(proposal)
        assert result.allowed is False
        assert "action type" in result.reason.lower()


# ── Empty target fails ──────────────────────────────────────────────────────


class TestEmptyTarget:
    def test_none_target_fails(self) -> None:
        checker = ApprovalPolicyCheck()
        proposal = _make_proposal(target_id=None)
        result = checker.check(proposal)
        assert result.allowed is False
        assert "target" in result.reason.lower()
        assert result.rule_id == "target_required"

    def test_empty_string_target_fails(self) -> None:
        checker = ApprovalPolicyCheck()
        proposal = _make_proposal(target_id="")
        result = checker.check(proposal)
        assert result.allowed is False
        assert "target" in result.reason.lower()

    def test_whitespace_target_fails(self) -> None:
        checker = ApprovalPolicyCheck()
        proposal = _make_proposal(target_id="   ")
        result = checker.check(proposal)
        assert result.allowed is False
        assert "target" in result.reason.lower()


# ── Determinism ──────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_proposal_same_result(self) -> None:
        checker = ApprovalPolicyCheck()
        proposal = _make_proposal()
        result1 = checker.check(proposal)
        result2 = checker.check(proposal)
        assert result1.allowed == result2.allowed
        assert result1.reason == result2.reason
        assert result1.rule_id == result2.rule_id

    def test_multiple_calls_consistent(self) -> None:
        checker = ApprovalPolicyCheck()
        proposal = _make_proposal()
        results = [checker.check(proposal) for _ in range(10)]
        assert all(r.allowed == results[0].allowed for r in results)
        assert all(r.reason == results[0].reason for r in results)


# ── Side-effect free ─────────────────────────────────────────────────────────


class TestSideEffectFree:
    def test_proposal_not_modified(self) -> None:
        checker = ApprovalPolicyCheck()
        proposal = _make_proposal(
            action_type=ActionType.CREATE_TASK,
            target_id="task-123",
        )
        original_action_type = proposal.action_type
        original_target_id = proposal.target_id
        original_status = proposal.status

        checker.check(proposal)

        assert proposal.action_type == original_action_type
        assert proposal.target_id == original_target_id
        assert proposal.status == original_status

    def test_no_global_state_mutated(self) -> None:
        checker = ApprovalPolicyCheck()
        proposal = _make_proposal()
        checker.check(proposal)
        # A second checker should behave identically
        checker2 = ApprovalPolicyCheck()
        result1 = checker.check(proposal)
        result2 = checker2.check(proposal)
        assert result1.allowed == result2.allowed
        assert result1.reason == result2.reason


# ── PolicyCheckResult properties ────────────────────────────────────────────


class TestPolicyCheckResult:
    def test_denied_property(self) -> None:
        result = PolicyCheckResult(allowed=False, reason="test")
        assert result.denied is True

    def test_allowed_property(self) -> None:
        result = PolicyCheckResult(allowed=True, reason="test")
        assert result.denied is False

    def test_to_dict(self) -> None:
        result = PolicyCheckResult(
            allowed=True,
            reason="test",
            rule_id="test_rule",
        )
        d = result.to_dict()
        assert d["allowed"] is True
        assert d["reason"] == "test"
        assert d["rule_id"] == "test_rule"
        assert "timestamp" in d
