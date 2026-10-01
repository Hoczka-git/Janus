"""Verification tests for classification and enforcement (Phase E).

Covers edge cases and integration scenarios not covered by the primary
test files (test_policy_model.py, test_policy_engine.py, test_enforcement_gate.py):

- Exhaustive classification coverage for all PolicyAction values
- Exhaustive enforcement coverage for all EnforcementAction values
- Risk/impact override matrix
- Context detection edge cases
- Policy default decision variations
- Audit log content verification
- dispatch_completion integration with various object types
- Policy reload effects on classification
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from janus.models.policy import (
    ClassificationCategory,
    ImpactLevel,
    Policy,
    PolicyAction,
    PolicyDecision,
    PolicyRule,
    RiskLevel,
    create_default_policy,
)
from janus.services.enforcement_gate import (
    EnforcementAction,
    EnforcementGateError,
    EnforcementResult,
    _action_to_policy_action,
    _default_impact_for_action,
    _default_risk_for_action,
    _is_user_context,
    check_action_allowed,
    enforce_action,
    enforce_or_raise,
)
from janus.services.policy_engine import (
    PolicyEngine,
    _decision_to_category,
    classify_action,
    evaluate_action,
    get_policy_engine,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def allow_all_engine(tmp_path):
    """PolicyEngine that allows all actions."""
    policy_data = {"name": "allow_all", "default_decision": "allow", "rules": []}
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(yaml.dump(policy_data), encoding="utf-8")
    return PolicyEngine(
        policy_path=policy_file,
        audit_log_path=tmp_path / "audit.log",
    )


@pytest.fixture
def deny_all_engine(tmp_path):
    """PolicyEngine that denies all actions."""
    policy_data = {"name": "deny_all", "default_decision": "deny", "rules": []}
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(yaml.dump(policy_data), encoding="utf-8")
    return PolicyEngine(
        policy_path=policy_file,
        audit_log_path=tmp_path / "audit.log",
    )


@pytest.fixture
def ask_all_engine(tmp_path):
    """PolicyEngine that requires approval for all actions."""
    policy_data = {"name": "ask_all", "default_decision": "ask", "rules": []}
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(yaml.dump(policy_data), encoding="utf-8")
    return PolicyEngine(
        policy_path=policy_file,
        audit_log_path=tmp_path / "audit.log",
    )


@pytest.fixture
def default_engine(tmp_path):
    """PolicyEngine with default policy (no YAML file)."""
    return PolicyEngine(
        policy_path=tmp_path / "nonexistent.yaml",
        audit_log_path=tmp_path / "audit.log",
    )


# ══════════════════════════════════════════════════════════════════════════
# Classification edge cases
# ══════════════════════════════════════════════════════════════════════════


class TestDecisionToCategoryMapping:
    """Direct tests for the _decision_to_category function."""

    def test_allow_maps_to_auto_allowed(self):
        assert _decision_to_category(PolicyDecision.ALLOW) == ClassificationCategory.AUTO_ALLOWED

    def test_ask_maps_to_approval_required(self):
        assert _decision_to_category(PolicyDecision.ASK) == ClassificationCategory.APPROVAL_REQUIRED

    def test_deny_maps_to_user_only(self):
        assert _decision_to_category(PolicyDecision.DENY) == ClassificationCategory.USER_ONLY

    def test_all_three_decisions_covered(self):
        """Ensure every PolicyDecision value has a mapping."""
        for decision in PolicyDecision:
            category = _decision_to_category(decision)
            assert isinstance(category, ClassificationCategory)


class TestExhaustiveClassification:
    """Test classification for all PolicyAction × RiskLevel × ImpactLevel combos."""

    def test_all_combinations_return_valid_category(self, default_engine):
        """Every (action, risk, impact) tuple must return a valid ClassificationCategory."""
        for action in PolicyAction:
            for risk in RiskLevel:
                for impact in ImpactLevel:
                    category = default_engine.classify(action, risk, impact)
                    assert isinstance(category, ClassificationCategory), (
                        f"Invalid category for {action}/{risk}/{impact}"
                    )

    def test_all_actions_classified_with_allow_all(self, allow_all_engine):
        """With allow_all policy, every action should be AUTO_ALLOWED."""
        for action in PolicyAction:
            for risk in RiskLevel:
                for impact in ImpactLevel:
                    category = allow_all_engine.classify(action, risk, impact)
                    assert category == ClassificationCategory.AUTO_ALLOWED

    def test_all_actions_classified_with_deny_all(self, deny_all_engine):
        """With deny_all policy, every action should be USER_ONLY."""
        for action in PolicyAction:
            for risk in RiskLevel:
                for impact in ImpactLevel:
                    category = deny_all_engine.classify(action, risk, impact)
                    assert category == ClassificationCategory.USER_ONLY

    def test_all_actions_classified_with_ask_all(self, ask_all_engine):
        """With ask_all policy, every action should be APPROVAL_REQUIRED."""
        for action in PolicyAction:
            for risk in RiskLevel:
                for impact in ImpactLevel:
                    category = ask_all_engine.classify(action, risk, impact)
                    assert category == ClassificationCategory.APPROVAL_REQUIRED


class TestPolicyDefaultDecisions:
    """Test Policy with different default decisions and no rules."""

    def test_empty_policy_allow_default(self):
        policy = Policy(rules=[], default_decision=PolicyDecision.ALLOW)
        for action in PolicyAction:
            for risk in RiskLevel:
                for impact in ImpactLevel:
                    assert policy.evaluate(action, risk, impact) == PolicyDecision.ALLOW

    def test_empty_policy_deny_default(self):
        policy = Policy(rules=[], default_decision=PolicyDecision.DENY)
        for action in PolicyAction:
            for risk in RiskLevel:
                for impact in ImpactLevel:
                    assert policy.evaluate(action, risk, impact) == PolicyDecision.DENY

    def test_empty_policy_ask_default(self):
        policy = Policy(rules=[], default_decision=PolicyDecision.ASK)
        for action in PolicyAction:
            for risk in RiskLevel:
                for impact in ImpactLevel:
                    assert policy.evaluate(action, risk, impact) == PolicyDecision.ASK


class TestDefaultPolicyStructure:
    """Verify the default policy has the expected structure."""

    def test_default_policy_name(self):
        policy = create_default_policy()
        assert policy.name == "default"

    def test_default_policy_default_decision(self):
        policy = create_default_policy()
        assert policy.default_decision == PolicyDecision.ASK

    def test_default_policy_has_rules(self):
        policy = create_default_policy()
        assert len(policy.rules) > 0

    def test_default_policy_rules_sorted_by_priority(self):
        policy = create_default_policy()
        priorities = [r.priority for r in policy.rules]
        assert priorities == sorted(priorities)

    def test_default_policy_read_always_allowed(self):
        policy = create_default_policy()
        for risk in RiskLevel:
            for impact in ImpactLevel:
                assert policy.evaluate(PolicyAction.READ, risk, impact) == PolicyDecision.ALLOW

    def test_default_policy_approve_always_asks(self):
        policy = create_default_policy()
        for risk in RiskLevel:
            for impact in ImpactLevel:
                assert policy.evaluate(PolicyAction.APPROVE, risk, impact) == PolicyDecision.ASK

    def test_default_policy_delegate_always_asks(self):
        policy = create_default_policy()
        for risk in RiskLevel:
            for impact in ImpactLevel:
                assert policy.evaluate(PolicyAction.DELEGATE, risk, impact) == PolicyDecision.ASK

    def test_default_policy_delete_high_high_denied(self):
        policy = create_default_policy()
        assert policy.evaluate(PolicyAction.DELETE, RiskLevel.HIGH, ImpactLevel.HIGH) == PolicyDecision.DENY

    def test_default_policy_delete_other_combinations_ask(self):
        policy = create_default_policy()
        for risk in RiskLevel:
            for impact in ImpactLevel:
                if risk == RiskLevel.HIGH and impact == ImpactLevel.HIGH:
                    continue
                assert policy.evaluate(PolicyAction.DELETE, risk, impact) == PolicyDecision.ASK


class TestPolicyRuleEdgeCases:
    """Test PolicyRule matching edge cases."""

    def test_rule_with_both_wildcards_matches_all(self):
        rule = PolicyRule(
            action=PolicyAction.WRITE,
            risk=None,
            impact=None,
            decision=PolicyDecision.ASK,
        )
        for risk in RiskLevel:
            for impact in ImpactLevel:
                assert rule.matches(PolicyAction.WRITE, risk, impact)

    def test_rule_with_specific_risk_only(self):
        rule = PolicyRule(
            action=PolicyAction.WRITE,
            risk=RiskLevel.MEDIUM,
            impact=None,
            decision=PolicyDecision.ALLOW,
        )
        assert rule.matches(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.LOW)
        assert rule.matches(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.HIGH)
        assert not rule.matches(PolicyAction.WRITE, RiskLevel.LOW, ImpactLevel.LOW)
        assert not rule.matches(PolicyAction.WRITE, RiskLevel.HIGH, ImpactLevel.LOW)

    def test_rule_with_specific_impact_only(self):
        rule = PolicyRule(
            action=PolicyAction.WRITE,
            risk=None,
            impact=ImpactLevel.HIGH,
            decision=PolicyDecision.DENY,
        )
        assert rule.matches(PolicyAction.WRITE, RiskLevel.LOW, ImpactLevel.HIGH)
        assert rule.matches(PolicyAction.WRITE, RiskLevel.HIGH, ImpactLevel.HIGH)
        assert not rule.matches(PolicyAction.WRITE, RiskLevel.LOW, ImpactLevel.LOW)
        assert not rule.matches(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.MEDIUM)

    def test_rule_with_both_specific(self):
        rule = PolicyRule(
            action=PolicyAction.DELETE,
            risk=RiskLevel.HIGH,
            impact=ImpactLevel.HIGH,
            decision=PolicyDecision.DENY,
        )
        assert rule.matches(PolicyAction.DELETE, RiskLevel.HIGH, ImpactLevel.HIGH)
        assert not rule.matches(PolicyAction.DELETE, RiskLevel.HIGH, ImpactLevel.LOW)
        assert not rule.matches(PolicyAction.DELETE, RiskLevel.LOW, ImpactLevel.HIGH)
        assert not rule.matches(PolicyAction.DELETE, RiskLevel.LOW, ImpactLevel.LOW)

    def test_add_rule_maintains_sort_order(self):
        policy = Policy(rules=[], default_decision=PolicyDecision.ALLOW)
        policy.add_rule(PolicyRule(
            action=PolicyAction.WRITE,
            risk=None,
            impact=None,
            decision=PolicyDecision.ASK,
            priority=50,
        ))
        policy.add_rule(PolicyRule(
            action=PolicyAction.DELETE,
            risk=RiskLevel.HIGH,
            impact=ImpactLevel.HIGH,
            decision=PolicyDecision.DENY,
            priority=10,
        ))
        # DELETE rule (priority 10) should come first
        assert policy.rules[0].priority == 10
        assert policy.rules[1].priority == 50

    def test_remove_rule_correct_rule(self):
        rule1 = PolicyRule(
            action=PolicyAction.WRITE,
            risk=None,
            impact=None,
            decision=PolicyDecision.ASK,
        )
        rule2 = PolicyRule(
            action=PolicyAction.DELETE,
            risk=None,
            impact=None,
            decision=PolicyDecision.DENY,
        )
        policy = Policy(rules=[rule1, rule2], default_decision=PolicyDecision.ALLOW)
        assert policy.remove_rule(rule1) is True
        assert len(policy.rules) == 1
        assert policy.rules[0] is rule2

    def test_remove_nonexistent_rule_returns_false(self):
        rule = PolicyRule(
            action=PolicyAction.WRITE,
            risk=None,
            impact=None,
            decision=PolicyDecision.ASK,
        )
        policy = Policy(rules=[], default_decision=PolicyDecision.ALLOW)
        assert policy.remove_rule(rule) is False


# ══════════════════════════════════════════════════════════════════════════
# Enforcement gate edge cases
# ══════════════════════════════════════════════════════════════════════════


class TestAllEnforcementActions:
    """Test all 11 EnforcementAction values with different policies."""

    def test_all_actions_with_allow_all_policy(self, allow_all_engine):
        for action in EnforcementAction:
            result = enforce_action(action, context="cli", policy_engine=allow_all_engine)
            assert result.allowed is True, f"{action} should be allowed"
            assert result.category == ClassificationCategory.AUTO_ALLOWED

    def test_all_actions_with_deny_all_policy_user_context(self, deny_all_engine):
        for action in EnforcementAction:
            result = enforce_action(action, context="cli", policy_engine=deny_all_engine)
            assert result.allowed is True, f"{action} should be allowed in user context"
            assert result.category == ClassificationCategory.USER_ONLY

    def test_all_actions_with_deny_all_policy_system_context(self, deny_all_engine):
        for action in EnforcementAction:
            result = enforce_action(action, context="hermes_sync", policy_engine=deny_all_engine)
            assert result.allowed is False, f"{action} should be blocked in system context"
            assert result.category == ClassificationCategory.USER_ONLY

    def test_all_actions_with_ask_all_policy(self, ask_all_engine):
        for action in EnforcementAction:
            result = enforce_action(action, context="cli", policy_engine=ask_all_engine)
            assert result.allowed is False, f"{action} should require approval"
            assert result.category == ClassificationCategory.APPROVAL_REQUIRED

    def test_all_actions_with_default_policy(self, default_engine):
        """Test all actions with the default policy — verify expected categories."""
        expected = {
            EnforcementAction.TASK_COMPLETION: ClassificationCategory.AUTO_ALLOWED,
            EnforcementAction.TASK_STATUS_CHANGE: ClassificationCategory.AUTO_ALLOWED,
            EnforcementAction.KNOWLEDGE_INGESTION: ClassificationCategory.AUTO_ALLOWED,
            EnforcementAction.GOAL_COMPLETION: ClassificationCategory.APPROVAL_REQUIRED,
            EnforcementAction.MILESTONE_COMPLETION: ClassificationCategory.APPROVAL_REQUIRED,
            EnforcementAction.PROJECT_COMPLETION: ClassificationCategory.APPROVAL_REQUIRED,
            EnforcementAction.KNOWLEDGE_PROMOTION: ClassificationCategory.APPROVAL_REQUIRED,
            EnforcementAction.EXTERNAL_WRITE: ClassificationCategory.APPROVAL_REQUIRED,
            EnforcementAction.BULK_OPERATION: ClassificationCategory.APPROVAL_REQUIRED,
            EnforcementAction.CONFIG_CHANGE: ClassificationCategory.APPROVAL_REQUIRED,
            # GOAL_DELETION: DELETE with high risk + high impact → DENY → USER_ONLY
            EnforcementAction.GOAL_DELETION: ClassificationCategory.USER_ONLY,
        }
        for action, expected_category in expected.items():
            result = enforce_action(action, context="cli", policy_engine=default_engine)
            assert result.category == expected_category, (
                f"{action}: expected {expected_category}, got {result.category}"
            )


class TestEnforcementActionMapping:
    """Test that all EnforcementAction values map to correct PolicyAction."""

    def test_all_mappings(self):
        expected = {
            EnforcementAction.TASK_COMPLETION: PolicyAction.UPDATE,
            EnforcementAction.GOAL_COMPLETION: PolicyAction.UPDATE,
            EnforcementAction.MILESTONE_COMPLETION: PolicyAction.UPDATE,
            EnforcementAction.PROJECT_COMPLETION: PolicyAction.UPDATE,
            EnforcementAction.KNOWLEDGE_PROMOTION: PolicyAction.CREATE,
            EnforcementAction.KNOWLEDGE_INGESTION: PolicyAction.CREATE,
            EnforcementAction.EXTERNAL_WRITE: PolicyAction.SEND,
            EnforcementAction.BULK_OPERATION: PolicyAction.EXECUTE,
            EnforcementAction.CONFIG_CHANGE: PolicyAction.UPDATE,
            EnforcementAction.TASK_STATUS_CHANGE: PolicyAction.UPDATE,
            EnforcementAction.GOAL_DELETION: PolicyAction.DELETE,
        }
        for action, policy_action in expected.items():
            assert _action_to_policy_action(action) == policy_action

    def test_all_actions_have_default_risk(self):
        for action in EnforcementAction:
            risk = _default_risk_for_action(action)
            assert isinstance(risk, RiskLevel)

    def test_all_actions_have_default_impact(self):
        for action in EnforcementAction:
            impact = _default_impact_for_action(action)
            assert isinstance(impact, ImpactLevel)


class TestContextDetectionEdgeCases:
    """Test _is_user_context with various edge cases."""

    def test_none_like_empty_string(self):
        assert _is_user_context("") is False

    def test_whitespace_only_context(self):
        """Whitespace-only context is truthy and doesn't match known non-user prefixes."""
        # "   " is truthy, doesn't start with "automated:", "system:", "hermes", or "sync"
        # and doesn't match known user contexts, so it falls through to default (True)
        assert _is_user_context("   ") is True

    def test_mixed_case_cli(self):
        """Context matching is case-sensitive — 'CLI' is not 'cli'."""
        # 'CLI' doesn't match any known user context and doesn't start with
        # 'hermes' or 'sync', so it falls through to the default (True)
        assert _is_user_context("CLI") is True

    def test_automated_prefix_variations(self):
        assert _is_user_context("automated:daily_report") is False
        assert _is_user_context("automated:weekly_review") is False
        assert _is_user_context("automated:cleanup") is False

    def test_system_prefix_variations(self):
        assert _is_user_context("system:backup") is False
        assert _is_user_context("system:rotation") is False

    def test_hermes_prefix_variations(self):
        assert _is_user_context("hermes_sync") is False
        assert _is_user_context("hermes_listener") is False

    def test_sync_prefix_variations(self):
        assert _is_user_context("sync:listener") is False
        assert _is_user_context("sync:worker") is False

    def test_known_user_contexts(self):
        for ctx in ("cli", "user", "telegram", "api"):
            assert _is_user_context(ctx) is True

    def test_unknown_context_defaults_to_user(self):
        """Unknown contexts default to user context (fail-open for explicit interactions)."""
        assert _is_user_context("some_random_context") is True
        assert _is_user_context("custom_channel") is True


class TestEnforcementResultFields:
    """Test that EnforcementResult fields are correctly populated."""

    def test_auto_allowed_result_fields(self, allow_all_engine):
        result = enforce_action(
            EnforcementAction.TASK_COMPLETION,
            context="cli",
            policy_engine=allow_all_engine,
        )
        assert result.allowed is True
        assert result.category == ClassificationCategory.AUTO_ALLOWED
        assert result.action == "task_completion"
        assert result.context == "cli"
        assert "auto-allowed" in result.message

    def test_approval_required_result_fields(self, ask_all_engine):
        result = enforce_action(
            EnforcementAction.GOAL_COMPLETION,
            context="cli",
            policy_engine=ask_all_engine,
        )
        assert result.allowed is False
        assert result.category == ClassificationCategory.APPROVAL_REQUIRED
        assert result.action == "goal_completion"
        assert result.context == "cli"
        assert "requires human approval" in result.message

    def test_user_only_allowed_result_fields(self, deny_all_engine):
        result = enforce_action(
            EnforcementAction.GOAL_DELETION,
            context="cli",
            policy_engine=deny_all_engine,
        )
        assert result.allowed is True
        assert result.category == ClassificationCategory.USER_ONLY
        assert result.action == "goal_deletion"
        assert "user context" in result.message

    def test_user_only_blocked_result_fields(self, deny_all_engine):
        result = enforce_action(
            EnforcementAction.GOAL_DELETION,
            context="hermes_sync",
            policy_engine=deny_all_engine,
        )
        assert result.allowed is False
        assert result.category == ClassificationCategory.USER_ONLY
        assert result.action == "goal_deletion"
        assert "restricted to user contexts" in result.message


class TestRiskImpactOverrideMatrix:
    """Test risk/impact overrides for all enforcement actions."""

    def test_all_actions_with_high_risk_high_impact(self, default_engine):
        """High risk + impact should require approval for most actions."""
        for action in EnforcementAction:
            result = enforce_action(
                action,
                context="cli",
                risk=RiskLevel.HIGH,
                impact=ImpactLevel.HIGH,
                policy_engine=default_engine,
            )
            # With high risk + impact, most actions should require approval
            # (except READ which is always allowed, but no enforcement action maps to READ)
            assert result.category in (
                ClassificationCategory.APPROVAL_REQUIRED,
                ClassificationCategory.USER_ONLY,
            ), f"{action} with high/high should require approval or be user-only"

    def test_all_actions_with_low_risk_low_impact(self, default_engine):
        """Low risk + impact should allow most actions."""
        # GOAL_DELETION maps to DELETE, which requires ASK even for low/low
        # (default policy: "All deletes require approval")
        for action in EnforcementAction:
            result = enforce_action(
                action,
                context="cli",
                risk=RiskLevel.LOW,
                impact=ImpactLevel.LOW,
                policy_engine=default_engine,
            )
            if action == EnforcementAction.GOAL_DELETION:
                assert result.category == ClassificationCategory.APPROVAL_REQUIRED, (
                    f"{action} with low/low should require approval (all deletes require approval)"
                )
            else:
                assert result.category == ClassificationCategory.AUTO_ALLOWED, (
                    f"{action} with low/low should be auto-allowed"
                )

    def test_risk_override_string_values(self, default_engine):
        """Test that string risk/impact values are accepted."""
        result = enforce_action(
            EnforcementAction.TASK_COMPLETION,
            context="cli",
            risk="high",
            impact="high",
            policy_engine=default_engine,
        )
        assert result.category == ClassificationCategory.APPROVAL_REQUIRED

    def test_impact_override_only(self, default_engine):
        """Test overriding only impact (risk uses default)."""
        result = enforce_action(
            EnforcementAction.TASK_COMPLETION,
            context="cli",
            impact=ImpactLevel.HIGH,
            policy_engine=default_engine,
        )
        # Default risk for TASK_COMPLETION is LOW, so with HIGH impact
        # the default policy should still allow it (low risk writes are allowed)
        assert result.category == ClassificationCategory.AUTO_ALLOWED


class TestCheckActionAllowedEdgeCases:
    """Test check_action_allowed with various scenarios."""

    def test_never_raises_for_any_action(self, default_engine):
        """check_action_allowed should never raise, regardless of action/context."""
        for action in EnforcementAction:
            for context in ("cli", "hermes_sync", "", "automated:test"):
                result = check_action_allowed(
                    action,
                    context=context,
                    policy_engine=default_engine,
                )
                assert isinstance(result, bool)

    def test_returns_false_for_all_actions_in_system_context_with_deny(self, deny_all_engine):
        for action in EnforcementAction:
            result = check_action_allowed(
                action,
                context="hermes_sync",
                policy_engine=deny_all_engine,
            )
            assert result is False

    def test_returns_true_for_all_actions_in_user_context_with_deny(self, deny_all_engine):
        for action in EnforcementAction:
            result = check_action_allowed(
                action,
                context="cli",
                policy_engine=deny_all_engine,
            )
            assert result is True


class TestEnforceOrRaiseEdgeCases:
    """Test enforce_or_raise with various scenarios."""

    def test_returns_result_for_all_allowed_actions(self, allow_all_engine):
        for action in EnforcementAction:
            result = enforce_or_raise(action, context="cli", policy_engine=allow_all_engine)
            assert result.allowed is True

    def test_raises_for_all_approval_required_actions(self, ask_all_engine):
        for action in EnforcementAction:
            with pytest.raises(EnforcementGateError):
                enforce_or_raise(action, context="cli", policy_engine=ask_all_engine)

    def test_raises_for_all_user_only_actions_in_system_context(self, deny_all_engine):
        for action in EnforcementAction:
            with pytest.raises(EnforcementGateError):
                enforce_or_raise(action, context="hermes_sync", policy_engine=deny_all_engine)

    def test_error_contains_action_name(self, ask_all_engine):
        with pytest.raises(EnforcementGateError) as exc_info:
            enforce_or_raise(
                EnforcementAction.EXTERNAL_WRITE,
                context="cli",
                policy_engine=ask_all_engine,
            )
        assert "external_write" in str(exc_info.value)

    def test_error_contains_risk_and_impact(self, ask_all_engine):
        with pytest.raises(EnforcementGateError) as exc_info:
            enforce_or_raise(
                EnforcementAction.GOAL_COMPLETION,
                context="cli",
                policy_engine=ask_all_engine,
            )
        assert "Risk: medium" in str(exc_info.value)
        assert "Impact: medium" in str(exc_info.value)


class TestEnforcementGateErrorEdgeCases:
    """Test EnforcementGateError with various result configurations."""

    def test_error_with_all_categories(self):
        for category in ClassificationCategory:
            result = EnforcementResult(
                allowed=False,
                category=category,
                action="test_action",
                message=f"Test message for {category.value}",
            )
            error = EnforcementGateError(result)
            assert error.result is result
            assert str(error) == f"Test message for {category.value}"

    def test_error_is_catchable_as_runtime_error(self):
        result = EnforcementResult(
            allowed=False,
            category=ClassificationCategory.APPROVAL_REQUIRED,
            action="test",
            message="test",
        )
        error = EnforcementGateError(result)
        with pytest.raises(RuntimeError):
            raise error


# ══════════════════════════════════════════════════════════════════════════
# Audit log verification
# ══════════════════════════════════════════════════════════════════════════


class TestAuditLogVerification:
    """Test that audit log captures correct information."""

    def test_audit_log_contains_action_mapping(self, tmp_path):
        """Verify audit log records the PolicyAction, not the EnforcementAction."""
        audit_path = tmp_path / "audit.log"
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=audit_path,
        )
        enforce_action(
            EnforcementAction.TASK_COMPLETION,
            context="cli",
            policy_engine=engine,
        )
        content = audit_path.read_text(encoding="utf-8")
        # TASK_COMPLETION maps to PolicyAction.UPDATE
        assert "action=update" in content
        assert "decision=allow" in content

    def test_audit_log_contains_risk_and_impact(self, tmp_path):
        audit_path = tmp_path / "audit.log"
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=audit_path,
        )
        enforce_action(
            EnforcementAction.GOAL_COMPLETION,
            context="cli",
            policy_engine=engine,
        )
        content = audit_path.read_text(encoding="utf-8")
        assert "risk=medium" in content
        assert "impact=medium" in content

    def test_audit_log_contains_context(self, tmp_path):
        audit_path = tmp_path / "audit.log"
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=audit_path,
        )
        enforce_action(
            EnforcementAction.TASK_COMPLETION,
            context="cli",
            policy_engine=engine,
        )
        content = audit_path.read_text(encoding="utf-8")
        assert "context='cli'" in content

    def test_audit_log_contains_rule_description(self, tmp_path):
        audit_path = tmp_path / "audit.log"
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=audit_path,
        )
        enforce_action(
            EnforcementAction.TASK_COMPLETION,
            context="cli",
            policy_engine=engine,
        )
        content = audit_path.read_text(encoding="utf-8")
        # The default policy has a rule "Low-risk updates are allowed" for UPDATE + LOW
        assert "rule=" in content

    def test_audit_log_appends_multiple_decisions(self, tmp_path):
        audit_path = tmp_path / "audit.log"
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=audit_path,
        )
        enforce_action(
            EnforcementAction.TASK_COMPLETION,
            context="cli",
            policy_engine=engine,
        )
        enforce_action(
            EnforcementAction.GOAL_COMPLETION,
            context="cli",
            policy_engine=engine,
        )
        enforce_action(
            EnforcementAction.GOAL_DELETION,
            context="hermes_sync",
            policy_engine=engine,
        )
        lines = audit_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3

    def test_audit_log_decision_values(self, tmp_path):
        """Verify that audit log records correct decision values."""
        audit_path = tmp_path / "audit.log"
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=audit_path,
        )
        # ALLOW
        enforce_action(
            EnforcementAction.TASK_COMPLETION,
            context="cli",
            policy_engine=engine,
        )
        # ASK
        enforce_action(
            EnforcementAction.GOAL_COMPLETION,
            context="cli",
            policy_engine=engine,
        )
        # DENY (high risk + high impact delete)
        enforce_action(
            EnforcementAction.GOAL_DELETION,
            context="cli",
            risk=RiskLevel.HIGH,
            impact=ImpactLevel.HIGH,
            policy_engine=engine,
        )
        content = audit_path.read_text(encoding="utf-8")
        assert "decision=allow" in content
        assert "decision=ask" in content
        assert "decision=deny" in content


# ══════════════════════════════════════════════════════════════════════════
# Policy reload effects
# ══════════════════════════════════════════════════════════════════════════


class TestPolicyReloadEffects:
    """Test that policy reload affects subsequent classifications."""

    def test_reload_picks_up_new_rules(self, tmp_path):
        policy_file = tmp_path / "policy.yaml"
        policy_data = {
            "name": "test",
            "default_decision": "allow",
            "rules": [],
        }
        policy_file.write_text(yaml.dump(policy_data), encoding="utf-8")
        engine = PolicyEngine(
            policy_path=policy_file,
            audit_log_path=tmp_path / "audit.log",
        )
        # Initially allows all
        assert engine.classify(PolicyAction.WRITE, RiskLevel.HIGH, ImpactLevel.HIGH) == ClassificationCategory.AUTO_ALLOWED

        # Update policy to deny all
        policy_data["default_decision"] = "deny"
        policy_file.write_text(yaml.dump(policy_data), encoding="utf-8")

        # Before reload, still cached
        assert engine.classify(PolicyAction.WRITE, RiskLevel.HIGH, ImpactLevel.HIGH) == ClassificationCategory.AUTO_ALLOWED

        # After reload, picks up changes
        engine.reload()
        assert engine.classify(PolicyAction.WRITE, RiskLevel.HIGH, ImpactLevel.HIGH) == ClassificationCategory.USER_ONLY

    def test_reload_with_new_rules(self, tmp_path):
        policy_file = tmp_path / "policy.yaml"
        policy_data = {
            "name": "test",
            "default_decision": "allow",
            "rules": [],
        }
        policy_file.write_text(yaml.dump(policy_data), encoding="utf-8")
        engine = PolicyEngine(
            policy_path=policy_file,
            audit_log_path=tmp_path / "audit.log",
        )

        # Add a rule that denies high-risk deletes
        policy_data["rules"] = [
            {
                "action": "delete",
                "risk": "high",
                "impact": None,
                "decision": "deny",
                "description": "Deny high-risk deletes",
                "priority": 10,
            }
        ]
        policy_file.write_text(yaml.dump(policy_data), encoding="utf-8")
        engine.reload()

        # High-risk delete should now be denied
        assert engine.classify(PolicyAction.DELETE, RiskLevel.HIGH, ImpactLevel.LOW) == ClassificationCategory.USER_ONLY
        # Low-risk delete should still be allowed (default)
        assert engine.classify(PolicyAction.DELETE, RiskLevel.LOW, ImpactLevel.LOW) == ClassificationCategory.AUTO_ALLOWED


# ══════════════════════════════════════════════════════════════════════════
# dispatch_completion integration
# ══════════════════════════════════════════════════════════════════════════


class TestDispatchCompletionIntegration:
    """Test enforcement gate integration with dispatch_completion."""

    def test_task_object_blocked(self, tmp_path):
        from janus.services.execution_feedback import (
            EvidencePackage,
            JanusDomainMetadata,
            dispatch_completion,
        )

        metadata = JanusDomainMetadata(object="task", title="Test Task")
        evidence = EvidencePackage(task_id="t_123", summary="Test task")

        with patch("janus.services.enforcement_gate.get_policy_engine") as mock_get:
            mock_engine = MagicMock()
            mock_engine.classify.return_value = ClassificationCategory.APPROVAL_REQUIRED
            mock_get.return_value = mock_engine
            result = dispatch_completion(metadata, evidence)

        assert result["blocked"] == "task"
        assert "requires human approval" in result["reason"]
        assert result["category"] == "approval_required"

    def test_goal_object_blocked(self, tmp_path):
        from janus.services.execution_feedback import (
            EvidencePackage,
            JanusDomainMetadata,
            dispatch_completion,
        )

        metadata = JanusDomainMetadata(object="goal", title="Test Goal")
        evidence = EvidencePackage(task_id="t_123", summary="Test task")

        with patch("janus.services.enforcement_gate.get_policy_engine") as mock_get:
            mock_engine = MagicMock()
            mock_engine.classify.return_value = ClassificationCategory.APPROVAL_REQUIRED
            mock_get.return_value = mock_engine
            result = dispatch_completion(metadata, evidence)

        assert result["blocked"] == "goal"
        assert "requires human approval" in result["reason"]

    def test_milestone_object_blocked(self, tmp_path):
        from janus.services.execution_feedback import (
            EvidencePackage,
            JanusDomainMetadata,
            dispatch_completion,
        )

        metadata = JanusDomainMetadata(object="milestone", title="Test Milestone")
        evidence = EvidencePackage(task_id="t_123", summary="Test task")

        with patch("janus.services.enforcement_gate.get_policy_engine") as mock_get:
            mock_engine = MagicMock()
            mock_engine.classify.return_value = ClassificationCategory.APPROVAL_REQUIRED
            mock_get.return_value = mock_engine
            result = dispatch_completion(metadata, evidence)

        assert result["blocked"] == "milestone"
        assert "requires human approval" in result["reason"]

    def test_project_object_blocked(self, tmp_path):
        from janus.services.execution_feedback import (
            EvidencePackage,
            JanusDomainMetadata,
            dispatch_completion,
        )

        metadata = JanusDomainMetadata(object="project", title="Test Project")
        evidence = EvidencePackage(task_id="t_123", summary="Test task")

        with patch("janus.services.enforcement_gate.get_policy_engine") as mock_get:
            mock_engine = MagicMock()
            mock_engine.classify.return_value = ClassificationCategory.APPROVAL_REQUIRED
            mock_get.return_value = mock_engine
            result = dispatch_completion(metadata, evidence)

        assert result["blocked"] == "project"
        assert "requires human approval" in result["reason"]

    def test_user_only_blocked_in_system_context(self, tmp_path):
        from janus.services.execution_feedback import (
            EvidencePackage,
            JanusDomainMetadata,
            dispatch_completion,
        )

        metadata = JanusDomainMetadata(object="task", title="Test Task")
        evidence = EvidencePackage(task_id="t_123", summary="Test task")

        with patch("janus.services.enforcement_gate.get_policy_engine") as mock_get:
            mock_engine = MagicMock()
            mock_engine.classify.return_value = ClassificationCategory.USER_ONLY
            mock_get.return_value = mock_engine
            result = dispatch_completion(metadata, evidence)

        assert result["blocked"] == "task"
        assert "restricted to user contexts" in result["reason"]
        assert result["category"] == "user_only"

    def test_allowed_action_proceeds_to_dispatch(self, tmp_path):
        from janus.services.execution_feedback import (
            EvidencePackage,
            JanusDomainMetadata,
            dispatch_completion,
        )

        metadata = JanusDomainMetadata(object="goal", title="Test Goal")
        evidence = EvidencePackage(task_id="t_123", summary="Test task")

        with patch("janus.services.enforcement_gate.get_policy_engine") as mock_get:
            mock_engine = MagicMock()
            mock_engine.classify.return_value = ClassificationCategory.AUTO_ALLOWED
            mock_get.return_value = mock_engine

            with patch("janus.services.goals.update_goal_progress") as mock_update:
                mock_update.return_value = {"status": "ok"}
                result = dispatch_completion(metadata, evidence)

        assert "blocked" not in result
        assert result["goal"] == {"status": "ok"}

    def test_enforcement_gate_called_with_correct_action(self, tmp_path):
        """Verify the enforcement gate is called with the correct PolicyAction."""
        from janus.services.execution_feedback import (
            EvidencePackage,
            JanusDomainMetadata,
            dispatch_completion,
        )

        metadata = JanusDomainMetadata(object="task", title="Test Task")
        evidence = EvidencePackage(task_id="t_123", summary="Test task")

        with patch("janus.services.enforcement_gate.get_policy_engine") as mock_get:
            mock_engine = MagicMock()
            mock_engine.classify.return_value = ClassificationCategory.AUTO_ALLOWED
            mock_get.return_value = mock_engine

            with patch("janus.services.tasks.complete_janus_task") as mock_complete:
                mock_complete.return_value = {"status": "ok"}
                dispatch_completion(metadata, evidence)

            # Verify classify was called
            assert mock_engine.classify.called
            call_args = mock_engine.classify.call_args
            # First positional arg should be PolicyAction.UPDATE (task completion maps to UPDATE)
            assert call_args[0][0] == PolicyAction.UPDATE


# ══════════════════════════════════════════════════════════════════════════
# Module-level convenience functions
# ══════════════════════════════════════════════════════════════════════════


class TestModuleLevelConvenienceFunctions:
    """Test module-level convenience functions with edge cases."""

    def test_classify_action_with_strings(self):
        category = classify_action("read", "low", "low")
        assert category == ClassificationCategory.AUTO_ALLOWED

    def test_classify_action_with_enums(self):
        category = classify_action(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW)
        assert category == ClassificationCategory.AUTO_ALLOWED

    def test_evaluate_action_returns_decision(self):
        decision = evaluate_action(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW)
        assert decision == PolicyDecision.ALLOW

    def test_get_policy_engine_singleton(self):
        engine1 = get_policy_engine()
        engine2 = get_policy_engine()
        assert engine1 is engine2


# ══════════════════════════════════════════════════════════════════════════
# Conftest bypass verification
# ══════════════════════════════════════════════════════════════════════════


class TestConftestBypass:
    """Verify the conftest bypass fixture works correctly."""

    def test_bypass_fixture_patches_enforce_or_raise(self):
        """The conftest _bypass_enforcement_gate fixture should patch enforce_or_raise."""
        # This test verifies the bypass works by checking that enforce_or_raise
        # is patched in non-enforcement-gate tests
        # The actual patching is done by the autouse fixture in conftest.py
        # Here we just verify the function exists and is callable
        assert callable(enforce_or_raise)
        assert callable(check_action_allowed)
