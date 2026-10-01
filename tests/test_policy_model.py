"""Tests for the Policy model (Phase E: Policy & Approval engine).

Covers:
- PolicyAction, RiskLevel, ImpactLevel, PolicyDecision enums
- PolicyRule matching logic
- Policy evaluation with rules and defaults
- Policy rule ordering (priority + specificity)
- create_default_policy factory
"""

import pytest

from janus.models.policy import (
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


class TestPolicyRule:
    def test_matches_exact(self):
        rule = PolicyRule(
            action=PolicyAction.WRITE,
            risk=RiskLevel.MEDIUM,
            impact=ImpactLevel.LOW,
            decision=PolicyDecision.ASK,
        )
        assert rule.matches(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.LOW)

    def test_no_match_different_action(self):
        rule = PolicyRule(
            action=PolicyAction.WRITE,
            risk=RiskLevel.MEDIUM,
            impact=ImpactLevel.LOW,
            decision=PolicyDecision.ASK,
        )
        assert not rule.matches(PolicyAction.READ, RiskLevel.MEDIUM, ImpactLevel.LOW)

    def test_no_match_different_risk(self):
        rule = PolicyRule(
            action=PolicyAction.WRITE,
            risk=RiskLevel.MEDIUM,
            impact=ImpactLevel.LOW,
            decision=PolicyDecision.ASK,
        )
        assert not rule.matches(PolicyAction.WRITE, RiskLevel.HIGH, ImpactLevel.LOW)

    def test_wildcard_risk_matches_any(self):
        rule = PolicyRule(
            action=PolicyAction.WRITE,
            risk=None,
            impact=ImpactLevel.LOW,
            decision=PolicyDecision.ASK,
        )
        assert rule.matches(PolicyAction.WRITE, RiskLevel.LOW, ImpactLevel.LOW)
        assert rule.matches(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.LOW)
        assert rule.matches(PolicyAction.WRITE, RiskLevel.HIGH, ImpactLevel.LOW)

    def test_wildcard_impact_matches_any(self):
        rule = PolicyRule(
            action=PolicyAction.WRITE,
            risk=RiskLevel.MEDIUM,
            impact=None,
            decision=PolicyDecision.ASK,
        )
        assert rule.matches(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.LOW)
        assert rule.matches(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.MEDIUM)
        assert rule.matches(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.HIGH)

    def test_both_wildcards_match_any_risk_impact(self):
        rule = PolicyRule(
            action=PolicyAction.WRITE,
            risk=None,
            impact=None,
            decision=PolicyDecision.ALLOW,
        )
        assert rule.matches(PolicyAction.WRITE, RiskLevel.LOW, ImpactLevel.LOW)
        assert rule.matches(PolicyAction.WRITE, RiskLevel.HIGH, ImpactLevel.HIGH)


class TestPolicy:
    def test_empty_policy_returns_default(self):
        policy = Policy(rules=[], default_decision=PolicyDecision.ASK)
        assert policy.evaluate(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW) == PolicyDecision.ASK

    def test_single_rule_match(self):
        rule = PolicyRule(
            action=PolicyAction.READ,
            risk=None,
            impact=None,
            decision=PolicyDecision.ALLOW,
        )
        policy = Policy(rules=[rule], default_decision=PolicyDecision.ASK)
        assert policy.evaluate(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW) == PolicyDecision.ALLOW

    def test_no_matching_rule_returns_default(self):
        rule = PolicyRule(
            action=PolicyAction.READ,
            risk=None,
            impact=None,
            decision=PolicyDecision.ALLOW,
        )
        policy = Policy(rules=[rule], default_decision=PolicyDecision.DENY)
        assert policy.evaluate(PolicyAction.WRITE, RiskLevel.LOW, ImpactLevel.LOW) == PolicyDecision.DENY

    def test_first_matching_rule_wins(self):
        rule1 = PolicyRule(
            action=PolicyAction.WRITE,
            risk=RiskLevel.HIGH,
            impact=None,
            decision=PolicyDecision.DENY,
            priority=10,
        )
        rule2 = PolicyRule(
            action=PolicyAction.WRITE,
            risk=None,
            impact=None,
            decision=PolicyDecision.ALLOW,
            priority=50,
        )
        policy = Policy(rules=[rule2, rule1], default_decision=PolicyDecision.ASK)
        # rule1 has higher priority (lower number), so it should win
        assert policy.evaluate(PolicyAction.WRITE, RiskLevel.HIGH, ImpactLevel.LOW) == PolicyDecision.DENY

    def test_specificity_breaks_ties(self):
        # Same priority, but rule1 is more specific (has risk set)
        rule1 = PolicyRule(
            action=PolicyAction.WRITE,
            risk=RiskLevel.HIGH,
            impact=None,
            decision=PolicyDecision.DENY,
            priority=50,
        )
        rule2 = PolicyRule(
            action=PolicyAction.WRITE,
            risk=None,
            impact=None,
            decision=PolicyDecision.ALLOW,
            priority=50,
        )
        policy = Policy(rules=[rule2, rule1], default_decision=PolicyDecision.ASK)
        # rule1 is more specific, so it should win for HIGH risk
        assert policy.evaluate(PolicyAction.WRITE, RiskLevel.HIGH, ImpactLevel.LOW) == PolicyDecision.DENY
        # rule2 is the only match for LOW risk
        assert policy.evaluate(PolicyAction.WRITE, RiskLevel.LOW, ImpactLevel.LOW) == PolicyDecision.ALLOW

    def test_add_rule(self):
        policy = Policy(rules=[], default_decision=PolicyDecision.ASK)
        rule = PolicyRule(
            action=PolicyAction.READ,
            risk=None,
            impact=None,
            decision=PolicyDecision.ALLOW,
        )
        policy.add_rule(rule)
        assert policy.evaluate(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW) == PolicyDecision.ALLOW

    def test_remove_rule(self):
        rule = PolicyRule(
            action=PolicyAction.READ,
            risk=None,
            impact=None,
            decision=PolicyDecision.ALLOW,
        )
        policy = Policy(rules=[rule], default_decision=PolicyDecision.ASK)
        assert policy.remove_rule(rule) is True
        assert policy.evaluate(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW) == PolicyDecision.ASK

    def test_remove_nonexistent_rule(self):
        rule = PolicyRule(
            action=PolicyAction.READ,
            risk=None,
            impact=None,
            decision=PolicyDecision.ALLOW,
        )
        policy = Policy(rules=[], default_decision=PolicyDecision.ASK)
        assert policy.remove_rule(rule) is False

    def test_is_allowed(self):
        rule = PolicyRule(
            action=PolicyAction.READ,
            risk=None,
            impact=None,
            decision=PolicyDecision.ALLOW,
        )
        policy = Policy(rules=[rule], default_decision=PolicyDecision.ASK)
        assert policy.is_allowed(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW) is True
        assert policy.is_allowed(PolicyAction.WRITE, RiskLevel.LOW, ImpactLevel.LOW) is False

    def test_is_denied(self):
        rule = PolicyRule(
            action=PolicyAction.DELETE,
            risk=RiskLevel.HIGH,
            impact=ImpactLevel.HIGH,
            decision=PolicyDecision.DENY,
        )
        policy = Policy(rules=[rule], default_decision=PolicyDecision.ALLOW)
        assert policy.is_denied(PolicyAction.DELETE, RiskLevel.HIGH, ImpactLevel.HIGH) is True
        assert policy.is_denied(PolicyAction.DELETE, RiskLevel.LOW, ImpactLevel.LOW) is False

    def test_requires_approval(self):
        rule = PolicyRule(
            action=PolicyAction.WRITE,
            risk=RiskLevel.MEDIUM,
            impact=None,
            decision=PolicyDecision.ASK,
        )
        policy = Policy(rules=[rule], default_decision=PolicyDecision.ALLOW)
        assert policy.requires_approval(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.LOW) is True
        assert policy.requires_approval(PolicyAction.WRITE, RiskLevel.LOW, ImpactLevel.LOW) is False


class TestDefaultPolicy:
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

    def test_delete_high_risk_high_impact_denied(self):
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

    def test_send_low_risk_allowed(self):
        policy = create_default_policy()
        assert policy.evaluate(PolicyAction.SEND, RiskLevel.LOW, ImpactLevel.LOW) == PolicyDecision.ALLOW

    def test_send_medium_risk_asks(self):
        policy = create_default_policy()
        assert policy.evaluate(PolicyAction.SEND, RiskLevel.MEDIUM, ImpactLevel.LOW) == PolicyDecision.ASK

    def test_execute_low_risk_allowed(self):
        policy = create_default_policy()
        assert policy.evaluate(PolicyAction.EXECUTE, RiskLevel.LOW, ImpactLevel.LOW) == PolicyDecision.ALLOW

    def test_execute_medium_risk_asks(self):
        policy = create_default_policy()
        assert policy.evaluate(PolicyAction.EXECUTE, RiskLevel.MEDIUM, ImpactLevel.LOW) == PolicyDecision.ASK

    def test_create_low_risk_allowed(self):
        policy = create_default_policy()
        assert policy.evaluate(PolicyAction.CREATE, RiskLevel.LOW, ImpactLevel.LOW) == PolicyDecision.ALLOW

    def test_create_medium_risk_asks(self):
        policy = create_default_policy()
        assert policy.evaluate(PolicyAction.CREATE, RiskLevel.MEDIUM, ImpactLevel.LOW) == PolicyDecision.ASK

    def test_update_low_risk_allowed(self):
        policy = create_default_policy()
        assert policy.evaluate(PolicyAction.UPDATE, RiskLevel.LOW, ImpactLevel.LOW) == PolicyDecision.ALLOW

    def test_update_medium_risk_asks(self):
        policy = create_default_policy()
        assert policy.evaluate(PolicyAction.UPDATE, RiskLevel.MEDIUM, ImpactLevel.LOW) == PolicyDecision.ASK

    def test_default_decision_is_ask(self):
        policy = create_default_policy()
        assert policy.default_decision == PolicyDecision.ASK

    def test_name_is_default(self):
        policy = create_default_policy()
        assert policy.name == "default"
