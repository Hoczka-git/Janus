"""Tests for the Policy model (Phase E: Policy & Approval engine).

Covers:
- PolicyAction, RiskLevel, ImpactLevel, PolicyDecision, ClassificationCategory enums
- PolicyRule matching logic
- Policy evaluation with rules and defaults
- Policy rule ordering (priority + specificity)
- create_default_policy factory
- ClassificationCategory mapping from PolicyDecision
"""

import pytest

from janus.models.policy_agency import (
    ClassificationCategory,
    ImpactLevel,
    Policy,
    PolicyAction,
    PolicyDecision,
    PolicyRule,
    RiskLevel,
    create_default_policy,
)


class TestPolicyAction:
    def test_has_nine_members(self):
        assert len(PolicyAction) == 9

    def test_member_values(self):
        assert PolicyAction.READ == "read"
        assert PolicyAction.WRITE == "write"
        assert PolicyAction.DELETE == "delete"
        assert PolicyAction.EXECUTE == "execute"
        assert PolicyAction.SEND == "send"
        assert PolicyAction.CREATE == "create"
        assert PolicyAction.UPDATE == "update"
        assert PolicyAction.APPROVE == "approve"
        assert PolicyAction.DELEGATE == "delegate"

    def test_from_value(self):
        assert PolicyAction("read") == PolicyAction.READ
        assert PolicyAction("write") == PolicyAction.WRITE
        assert PolicyAction("delete") == PolicyAction.DELETE

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            PolicyAction("invalid")


class TestRiskLevel:
    def test_has_three_members(self):
        assert len(RiskLevel) == 3

    def test_member_values(self):
        assert RiskLevel.LOW == "low"
        assert RiskLevel.MEDIUM == "medium"
        assert RiskLevel.HIGH == "high"


class TestImpactLevel:
    def test_has_three_members(self):
        assert len(ImpactLevel) == 3

    def test_member_values(self):
        assert ImpactLevel.LOW == "low"
        assert ImpactLevel.MEDIUM == "medium"
        assert ImpactLevel.HIGH == "high"


class TestPolicyDecision:
    def test_has_three_members(self):
        assert len(PolicyDecision) == 3

    def test_member_values(self):
        assert PolicyDecision.ALLOW == "allow"
        assert PolicyDecision.ASK == "ask"
        assert PolicyDecision.DENY == "deny"


class TestClassificationCategory:
    def test_has_three_members(self):
        assert len(ClassificationCategory) == 3

    def test_member_values(self):
        assert ClassificationCategory.AUTO_ALLOWED == "auto_allowed"
        assert ClassificationCategory.APPROVAL_REQUIRED == "approval_required"
        assert ClassificationCategory.USER_ONLY == "user_only"

    def test_from_value(self):
        assert ClassificationCategory("auto_allowed") == ClassificationCategory.AUTO_ALLOWED
        assert ClassificationCategory("approval_required") == ClassificationCategory.APPROVAL_REQUIRED
        assert ClassificationCategory("user_only") == ClassificationCategory.USER_ONLY

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            ClassificationCategory("invalid")


class TestPolicyRule:
    def test_matches_exact(self):
        rule = PolicyRule(
            action=PolicyAction.WRITE,
            risk=RiskLevel.LOW,
            impact=ImpactLevel.LOW,
            decision=PolicyDecision.ALLOW,
        )
        assert rule.matches(PolicyAction.WRITE, RiskLevel.LOW, ImpactLevel.LOW)

    def test_matches_wildcard_risk(self):
        rule = PolicyRule(
            action=PolicyAction.WRITE,
            risk=None,
            impact=None,
            decision=PolicyDecision.ASK,
        )
        assert rule.matches(PolicyAction.WRITE, RiskLevel.LOW, ImpactLevel.LOW)
        assert rule.matches(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.HIGH)

    def test_no_match_different_action(self):
        rule = PolicyRule(
            action=PolicyAction.WRITE,
            risk=None,
            impact=None,
            decision=PolicyDecision.ALLOW,
        )
        assert not rule.matches(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW)

    def test_no_match_different_risk(self):
        rule = PolicyRule(
            action=PolicyAction.WRITE,
            risk=RiskLevel.LOW,
            impact=None,
            decision=PolicyDecision.ALLOW,
        )
        assert not rule.matches(PolicyAction.WRITE, RiskLevel.HIGH, ImpactLevel.LOW)

    def test_no_match_different_impact(self):
        rule = PolicyRule(
            action=PolicyAction.WRITE,
            risk=None,
            impact=ImpactLevel.LOW,
            decision=PolicyDecision.ALLOW,
        )
        assert not rule.matches(PolicyAction.WRITE, RiskLevel.LOW, ImpactLevel.HIGH)


class TestPolicy:
    def test_empty_policy_returns_default(self):
        policy = Policy(rules=[], default_decision=PolicyDecision.ASK)
        assert policy.evaluate(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW) == PolicyDecision.ASK

    def test_first_matching_rule_wins(self):
        policy = Policy(
            rules=[
                PolicyRule(
                    action=PolicyAction.WRITE,
                    risk=RiskLevel.LOW,
                    impact=None,
                    decision=PolicyDecision.ALLOW,
                    priority=10,
                ),
                PolicyRule(
                    action=PolicyAction.WRITE,
                    risk=None,
                    impact=None,
                    decision=PolicyDecision.ASK,
                    priority=20,
                ),
            ],
            default_decision=PolicyDecision.DENY,
        )
        # Low-risk write matches first rule → ALLOW
        assert policy.evaluate(PolicyAction.WRITE, RiskLevel.LOW, ImpactLevel.LOW) == PolicyDecision.ALLOW
        # Medium-risk write doesn't match first rule, matches second → ASK
        assert policy.evaluate(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.LOW) == PolicyDecision.ASK

    def test_priority_ordering(self):
        policy = Policy(
            rules=[
                PolicyRule(
                    action=PolicyAction.DELETE,
                    risk=RiskLevel.HIGH,
                    impact=ImpactLevel.HIGH,
                    decision=PolicyDecision.DENY,
                    priority=10,
                ),
                PolicyRule(
                    action=PolicyAction.DELETE,
                    risk=None,
                    impact=None,
                    decision=PolicyDecision.ASK,
                    priority=60,
                ),
            ],
            default_decision=PolicyDecision.ALLOW,
        )
        # High+high delete matches first rule (priority 10) → DENY
        assert policy.evaluate(PolicyAction.DELETE, RiskLevel.HIGH, ImpactLevel.HIGH) == PolicyDecision.DENY
        # Low delete doesn't match first rule, matches second → ASK
        assert policy.evaluate(PolicyAction.DELETE, RiskLevel.LOW, ImpactLevel.LOW) == PolicyDecision.ASK

    def test_specificity_tiebreak(self):
        policy = Policy(
            rules=[
                PolicyRule(
                    action=PolicyAction.WRITE,
                    risk=None,
                    impact=None,
                    decision=PolicyDecision.ASK,
                    priority=50,
                ),
                PolicyRule(
                    action=PolicyAction.WRITE,
                    risk=RiskLevel.LOW,
                    impact=None,
                    decision=PolicyDecision.ALLOW,
                    priority=50,
                ),
            ],
            default_decision=PolicyDecision.DENY,
        )
        # Low-risk write: both rules match, but the more specific one (risk=LOW) wins
        assert policy.evaluate(PolicyAction.WRITE, RiskLevel.LOW, ImpactLevel.LOW) == PolicyDecision.ALLOW
        # Medium-risk write: only the wildcard rule matches → ASK
        assert policy.evaluate(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.LOW) == PolicyDecision.ASK

    def test_is_allowed(self):
        policy = create_default_policy()
        assert policy.is_allowed(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW)
        assert not policy.is_allowed(PolicyAction.WRITE, RiskLevel.HIGH, ImpactLevel.LOW)

    def test_is_denied(self):
        policy = create_default_policy()
        assert policy.is_denied(PolicyAction.DELETE, RiskLevel.HIGH, ImpactLevel.HIGH)
        assert not policy.is_denied(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW)

    def test_requires_approval(self):
        policy = create_default_policy()
        assert policy.requires_approval(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.LOW)
        assert not policy.requires_approval(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW)

    def test_add_rule(self):
        policy = Policy(rules=[], default_decision=PolicyDecision.ALLOW)
        policy.add_rule(PolicyRule(
            action=PolicyAction.WRITE,
            risk=None,
            impact=None,
            decision=PolicyDecision.ASK,
        ))
        assert policy.evaluate(PolicyAction.WRITE, RiskLevel.LOW, ImpactLevel.LOW) == PolicyDecision.ASK

    def test_remove_rule(self):
        rule = PolicyRule(
            action=PolicyAction.WRITE,
            risk=None,
            impact=None,
            decision=PolicyDecision.ASK,
        )
        policy = Policy(rules=[rule], default_decision=PolicyDecision.ALLOW)
        assert policy.remove_rule(rule) is True
        assert policy.evaluate(PolicyAction.WRITE, RiskLevel.LOW, ImpactLevel.LOW) == PolicyDecision.ALLOW

    def test_remove_nonexistent_rule(self):
        policy = Policy(rules=[], default_decision=PolicyDecision.ALLOW)
        rule = PolicyRule(
            action=PolicyAction.WRITE,
            risk=None,
            impact=None,
            decision=PolicyDecision.ASK,
        )
        assert policy.remove_rule(rule) is False


class TestCreateDefaultPolicy:
    def test_name(self):
        policy = create_default_policy()
        assert policy.name == "default"

    def test_default_decision(self):
        policy = create_default_policy()
        assert policy.default_decision == PolicyDecision.ASK

    def test_read_always_allowed(self):
        policy = create_default_policy()
        for risk in RiskLevel:
            for impact in ImpactLevel:
                assert policy.evaluate(PolicyAction.READ, risk, impact) == PolicyDecision.ALLOW

    def test_write_low_risk_allowed(self):
        policy = create_default_policy()
        assert policy.evaluate(PolicyAction.WRITE, RiskLevel.LOW, ImpactLevel.LOW) == PolicyDecision.ALLOW
        assert policy.evaluate(PolicyAction.WRITE, RiskLevel.LOW, ImpactLevel.HIGH) == PolicyDecision.ALLOW

    def test_write_medium_risk_asks(self):
        policy = create_default_policy()
        assert policy.evaluate(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.LOW) == PolicyDecision.ASK
        assert policy.evaluate(PolicyAction.WRITE, RiskLevel.HIGH, ImpactLevel.LOW) == PolicyDecision.ASK

    def test_delete_high_high_denied(self):
        policy = create_default_policy()
        assert policy.evaluate(PolicyAction.DELETE, RiskLevel.HIGH, ImpactLevel.HIGH) == PolicyDecision.DENY

    def test_delete_other_asks(self):
        policy = create_default_policy()
        assert policy.evaluate(PolicyAction.DELETE, RiskLevel.LOW, ImpactLevel.LOW) == PolicyDecision.ASK
        assert policy.evaluate(PolicyAction.DELETE, RiskLevel.MEDIUM, ImpactLevel.MEDIUM) == PolicyDecision.ASK
        assert policy.evaluate(PolicyAction.DELETE, RiskLevel.HIGH, ImpactLevel.LOW) == PolicyDecision.ASK

    def test_approve_always_asks(self):
        policy = create_default_policy()
        for risk in RiskLevel:
            for impact in ImpactLevel:
                assert policy.evaluate(PolicyAction.APPROVE, risk, impact) == PolicyDecision.ASK

    def test_delegate_always_asks(self):
        policy = create_default_policy()
        for risk in RiskLevel:
            for impact in ImpactLevel:
                assert policy.evaluate(PolicyAction.DELEGATE, risk, impact) == PolicyDecision.ASK


class TestDecisionToCategoryMapping:
    """Test the mapping from PolicyDecision to ClassificationCategory."""

    def test_allow_maps_to_auto_allowed(self):
        policy = create_default_policy()
        decision = policy.evaluate(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW)
        assert decision == PolicyDecision.ALLOW
        # The mapping is tested via the engine's classify() method,
        # but we can verify the enum values here
        assert ClassificationCategory.AUTO_ALLOWED == "auto_allowed"

    def test_ask_maps_to_approval_required(self):
        policy = create_default_policy()
        decision = policy.evaluate(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.LOW)
        assert decision == PolicyDecision.ASK
        assert ClassificationCategory.APPROVAL_REQUIRED == "approval_required"

    def test_deny_maps_to_user_only(self):
        policy = create_default_policy()
        decision = policy.evaluate(PolicyAction.DELETE, RiskLevel.HIGH, ImpactLevel.HIGH)
        assert decision == PolicyDecision.DENY
        assert ClassificationCategory.USER_ONLY == "user_only"
