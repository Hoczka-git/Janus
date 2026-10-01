"""Tests for the Policy Engine service (Phase E: Policy & Approval engine).

Covers:
- PolicyEngine initialization and policy loading
- Policy evaluation with string and enum inputs
- classify() method returning ClassificationCategory
- Audit log recording
- YAML policy file parsing
- Module-level convenience functions
"""

from pathlib import Path

import pytest
import yaml

from janus.models.policy import (
    ClassificationCategory,
    ImpactLevel,
    PolicyAction,
    PolicyDecision,
    RiskLevel,
)
from janus.services.policy_engine import (
    PolicyEngine,
    check_approval,
    classify_action,
    evaluate_action,
    get_policy_engine,
)


class TestPolicyEngine:
    def test_init_with_default_path(self, tmp_path):
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=tmp_path / "audit.log",
        )
        assert engine.policy.name == "default"

    def test_init_loads_yaml_policy(self, tmp_path):
        policy_data = {
            "name": "test",
            "default_decision": "allow",
            "rules": [
                {
                    "action": "read",
                    "risk": None,
                    "impact": None,
                    "decision": "allow",
                    "description": "Allow all reads",
                    "priority": 100,
                },
                {
                    "action": "write",
                    "risk": "high",
                    "impact": None,
                    "decision": "deny",
                    "description": "Deny high-risk writes",
                    "priority": 10,
                },
            ],
        }
        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text(yaml.dump(policy_data), encoding="utf-8")

        engine = PolicyEngine(
            policy_path=policy_file,
            audit_log_path=tmp_path / "audit.log",
        )
        assert engine.policy.name == "test"
        assert engine.policy.default_decision == PolicyDecision.ALLOW
        assert len(engine.policy.rules) == 2

    def test_evaluate_with_enums(self, tmp_path):
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=tmp_path / "audit.log",
        )
        decision = engine.evaluate(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW)
        assert decision == PolicyDecision.ALLOW

    def test_evaluate_with_strings(self, tmp_path):
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=tmp_path / "audit.log",
        )
        decision = engine.evaluate("read", "low", "low")
        assert decision == PolicyDecision.ALLOW

    def test_evaluate_write_medium_risk(self, tmp_path):
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=tmp_path / "audit.log",
        )
        decision = engine.evaluate(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.LOW)
        assert decision == PolicyDecision.ASK

    def test_evaluate_delete_high_high(self, tmp_path):
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=tmp_path / "audit.log",
        )
        decision = engine.evaluate(PolicyAction.DELETE, RiskLevel.HIGH, ImpactLevel.HIGH)
        assert decision == PolicyDecision.DENY

    def test_classify_read_returns_auto_allowed(self, tmp_path):
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=tmp_path / "audit.log",
        )
        category = engine.classify(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW)
        assert category == ClassificationCategory.AUTO_ALLOWED

    def test_classify_write_medium_returns_approval_required(self, tmp_path):
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=tmp_path / "audit.log",
        )
        category = engine.classify(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.LOW)
        assert category == ClassificationCategory.APPROVAL_REQUIRED

    def test_classify_delete_high_high_returns_user_only(self, tmp_path):
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=tmp_path / "audit.log",
        )
        category = engine.classify(PolicyAction.DELETE, RiskLevel.HIGH, ImpactLevel.HIGH)
        assert category == ClassificationCategory.USER_ONLY

    def test_classify_with_strings(self, tmp_path):
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=tmp_path / "audit.log",
        )
        category = engine.classify("read", "low", "low")
        assert category == ClassificationCategory.AUTO_ALLOWED

    def test_classify_with_context(self, tmp_path):
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=tmp_path / "audit.log",
        )
        category = engine.classify(
            PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.LOW,
            context="task:Test task",
        )
        assert category == ClassificationCategory.APPROVAL_REQUIRED

    def test_classify_all_actions(self, tmp_path):
        """Test that classify() returns a valid category for all action types."""
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=tmp_path / "audit.log",
        )
        for action in PolicyAction:
            for risk in RiskLevel:
                for impact in ImpactLevel:
                    category = engine.classify(action, risk, impact)
                    assert isinstance(category, ClassificationCategory)
                    assert category in (
                        ClassificationCategory.AUTO_ALLOWED,
                        ClassificationCategory.APPROVAL_REQUIRED,
                        ClassificationCategory.USER_ONLY,
                    )

    def test_check_approval_true(self, tmp_path):
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=tmp_path / "audit.log",
        )
        assert engine.check_approval(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW) is True

    def test_check_approval_false_for_ask(self, tmp_path):
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=tmp_path / "audit.log",
        )
        assert engine.check_approval(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.LOW) is False

    def test_check_approval_false_for_deny(self, tmp_path):
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=tmp_path / "audit.log",
        )
        assert engine.check_approval(PolicyAction.DELETE, RiskLevel.HIGH, ImpactLevel.HIGH) is False

    def test_audit_log_written(self, tmp_path):
        audit_path = tmp_path / "audit.log"
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=audit_path,
        )
        engine.evaluate(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW, context="test")
        assert audit_path.exists()
        content = audit_path.read_text(encoding="utf-8")
        assert "action=read" in content
        assert "decision=allow" in content

    def test_audit_log_appends(self, tmp_path):
        audit_path = tmp_path / "audit.log"
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=audit_path,
        )
        engine.evaluate(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW)
        engine.evaluate(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.LOW)
        lines = audit_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_get_audit_log(self, tmp_path):
        audit_path = tmp_path / "audit.log"
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=audit_path,
        )
        engine.evaluate(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW)
        engine.evaluate(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.LOW)
        lines = engine.get_audit_log()
        assert len(lines) == 2

    def test_get_audit_log_with_limit(self, tmp_path):
        audit_path = tmp_path / "audit.log"
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=audit_path,
        )
        for i in range(5):
            engine.evaluate(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW)
        lines = engine.get_audit_log(limit=2)
        assert len(lines) == 2

    def test_get_audit_log_empty(self, tmp_path):
        engine = PolicyEngine(
            policy_path=tmp_path / "nonexistent.yaml",
            audit_log_path=tmp_path / "audit.log",
        )
        assert engine.get_audit_log() == []

    def test_reload(self, tmp_path):
        policy_file = tmp_path / "policy.yaml"
        policy_data = {
            "name": "test",
            "default_decision": "allow",
            "rules": [
                {
                    "action": "read",
                    "risk": None,
                    "impact": None,
                    "decision": "allow",
                    "description": "Allow all reads",
                    "priority": 100,
                },
            ],
        }
        policy_file.write_text(yaml.dump(policy_data), encoding="utf-8")

        engine = PolicyEngine(
            policy_path=policy_file,
            audit_log_path=tmp_path / "audit.log",
        )
        assert engine.policy.name == "test"

        # Modify the policy file
        policy_data["name"] = "updated"
        policy_file.write_text(yaml.dump(policy_data), encoding="utf-8")

        # Before reload, still cached
        assert engine.policy.name == "test"

        # After reload, picks up changes
        engine.reload()
        assert engine.policy.name == "updated"

    def test_invalid_yaml_falls_back_to_default(self, tmp_path):
        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text("not: valid: yaml: [", encoding="utf-8")

        engine = PolicyEngine(
            policy_path=policy_file,
            audit_log_path=tmp_path / "audit.log",
        )
        assert engine.policy.name == "default"

    def test_non_dict_yaml_falls_back_to_default(self, tmp_path):
        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text("- just\n- a\n- list\n", encoding="utf-8")

        engine = PolicyEngine(
            policy_path=policy_file,
            audit_log_path=tmp_path / "audit.log",
        )
        assert engine.policy.name == "default"

    def test_invalid_rule_skipped(self, tmp_path):
        policy_data = {
            "name": "test",
            "default_decision": "allow",
            "rules": [
                {
                    "action": "read",
                    "risk": None,
                    "impact": None,
                    "decision": "allow",
                    "description": "Allow all reads",
                    "priority": 100,
                },
                {
                    "action": "invalid_action",
                    "risk": None,
                    "impact": None,
                    "decision": "allow",
                    "description": "Invalid rule",
                    "priority": 50,
                },
            ],
        }
        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text(yaml.dump(policy_data), encoding="utf-8")

        engine = PolicyEngine(
            policy_path=policy_file,
            audit_log_path=tmp_path / "audit.log",
        )
        # Only the valid rule should be loaded
        assert len(engine.policy.rules) == 1


class TestModuleLevelFunctions:
    def test_get_policy_engine_singleton(self):
        engine1 = get_policy_engine()
        engine2 = get_policy_engine()
        assert engine1 is engine2

    def test_evaluate_action(self):
        decision = evaluate_action(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW)
        assert decision == PolicyDecision.ALLOW

    def test_classify_action(self):
        category = classify_action(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW)
        assert category == ClassificationCategory.AUTO_ALLOWED

    def test_classify_action_approval_required(self):
        category = classify_action(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.LOW)
        assert category == ClassificationCategory.APPROVAL_REQUIRED

    def test_classify_action_user_only(self):
        category = classify_action(PolicyAction.DELETE, RiskLevel.HIGH, ImpactLevel.HIGH)
        assert category == ClassificationCategory.USER_ONLY

    def test_check_approval(self):
        assert check_approval(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW) is True
        assert check_approval(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.LOW) is False
        assert check_approval(PolicyAction.DELETE, RiskLevel.HIGH, ImpactLevel.HIGH) is False
