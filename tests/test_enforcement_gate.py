"""Tests for the pre-execution enforcement gate (Phase E: Policy & Approval engine).

Covers:
- EnforcementAction enum
- EnforcementResult dataclass
- enforce_action() with all three classification categories
- USER_ONLY context detection
- check_action_allowed() convenience function
- enforce_or_raise() convenience function
- Integration with dispatch_completion
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from janus.models.policy import (
    ClassificationCategory,
    ImpactLevel,
    PolicyAction,
    PolicyDecision,
    RiskLevel,
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
from janus.services.policy_engine import PolicyEngine


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def engine(tmp_path):
    """Create a PolicyEngine with a nonexistent policy file (uses default)."""
    return PolicyEngine(
        policy_path=tmp_path / "nonexistent.yaml",
        audit_log_path=tmp_path / "audit.log",
    )


@pytest.fixture
def allow_all_engine(tmp_path):
    """Create a PolicyEngine that allows all actions."""
    policy_data = {
        "name": "allow_all",
        "default_decision": "allow",
        "rules": [],
    }
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(yaml.dump(policy_data), encoding="utf-8")
    return PolicyEngine(
        policy_path=policy_file,
        audit_log_path=tmp_path / "audit.log",
    )


@pytest.fixture
def deny_all_engine(tmp_path):
    """Create a PolicyEngine that denies all actions."""
    policy_data = {
        "name": "deny_all",
        "default_decision": "deny",
        "rules": [],
    }
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(yaml.dump(policy_data), encoding="utf-8")
    return PolicyEngine(
        policy_path=policy_file,
        audit_log_path=tmp_path / "audit.log",
    )


@pytest.fixture
def ask_all_engine(tmp_path):
    """Create a PolicyEngine that requires approval for all actions."""
    policy_data = {
        "name": "ask_all",
        "default_decision": "ask",
        "rules": [],
    }
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(yaml.dump(policy_data), encoding="utf-8")
    return PolicyEngine(
        policy_path=policy_file,
        audit_log_path=tmp_path / "audit.log",
    )


# ── EnforcementAction enum ──────────────────────────────────────────────────


class TestEnforcementAction:
    def test_has_eleven_members(self):
        assert len(EnforcementAction) == 11

    def test_member_values(self):
        assert EnforcementAction.TASK_COMPLETION == "task_completion"
        assert EnforcementAction.GOAL_COMPLETION == "goal_completion"
        assert EnforcementAction.MILESTONE_COMPLETION == "milestone_completion"
        assert EnforcementAction.PROJECT_COMPLETION == "project_completion"
        assert EnforcementAction.KNOWLEDGE_PROMOTION == "knowledge_promotion"
        assert EnforcementAction.KNOWLEDGE_INGESTION == "knowledge_ingestion"
        assert EnforcementAction.EXTERNAL_WRITE == "external_write"
        assert EnforcementAction.BULK_OPERATION == "bulk_operation"
        assert EnforcementAction.CONFIG_CHANGE == "config_change"
        assert EnforcementAction.TASK_STATUS_CHANGE == "task_status_change"
        assert EnforcementAction.GOAL_DELETION == "goal_deletion"

    def test_from_value(self):
        assert EnforcementAction("task_completion") == EnforcementAction.TASK_COMPLETION
        assert EnforcementAction("goal_deletion") == EnforcementAction.GOAL_DELETION

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            EnforcementAction("invalid")


# ── Action → Policy mapping ─────────────────────────────────────────────────


class TestActionToPolicyMapping:
    def test_task_completion_maps_to_update(self):
        assert _action_to_policy_action(EnforcementAction.TASK_COMPLETION) == PolicyAction.UPDATE

    def test_goal_completion_maps_to_update(self):
        assert _action_to_policy_action(EnforcementAction.GOAL_COMPLETION) == PolicyAction.UPDATE

    def test_knowledge_promotion_maps_to_create(self):
        assert _action_to_policy_action(EnforcementAction.KNOWLEDGE_PROMOTION) == PolicyAction.CREATE

    def test_external_write_maps_to_send(self):
        assert _action_to_policy_action(EnforcementAction.EXTERNAL_WRITE) == PolicyAction.SEND

    def test_bulk_operation_maps_to_execute(self):
        assert _action_to_policy_action(EnforcementAction.BULK_OPERATION) == PolicyAction.EXECUTE

    def test_goal_deletion_maps_to_delete(self):
        assert _action_to_policy_action(EnforcementAction.GOAL_DELETION) == PolicyAction.DELETE


# ── Default risk/impact ─────────────────────────────────────────────────────


class TestDefaultRiskImpact:
    def test_task_completion_default_risk(self):
        assert _default_risk_for_action(EnforcementAction.TASK_COMPLETION) == RiskLevel.LOW

    def test_goal_completion_default_risk(self):
        assert _default_risk_for_action(EnforcementAction.GOAL_COMPLETION) == RiskLevel.MEDIUM

    def test_external_write_default_risk(self):
        assert _default_risk_for_action(EnforcementAction.EXTERNAL_WRITE) == RiskLevel.HIGH

    def test_goal_deletion_default_risk(self):
        assert _default_risk_for_action(EnforcementAction.GOAL_DELETION) == RiskLevel.HIGH

    def test_task_completion_default_impact(self):
        assert _default_impact_for_action(EnforcementAction.TASK_COMPLETION) == ImpactLevel.LOW

    def test_goal_completion_default_impact(self):
        assert _default_impact_for_action(EnforcementAction.GOAL_COMPLETION) == ImpactLevel.MEDIUM

    def test_external_write_default_impact(self):
        assert _default_impact_for_action(EnforcementAction.EXTERNAL_WRITE) == ImpactLevel.HIGH


# ── Context detection ───────────────────────────────────────────────────────


class TestIsUserContext:
    def test_cli_is_user_context(self):
        assert _is_user_context("cli") is True

    def test_user_is_user_context(self):
        assert _is_user_context("user") is True

    def test_telegram_is_user_context(self):
        assert _is_user_context("telegram") is True

    def test_api_is_user_context(self):
        assert _is_user_context("api") is True

    def test_empty_context_is_not_user_context(self):
        assert _is_user_context("") is False

    def test_automated_context_is_not_user_context(self):
        assert _is_user_context("automated:daily") is False

    def test_system_context_is_not_user_context(self):
        assert _is_user_context("system:cleanup") is False

    def test_hermes_context_is_not_user_context(self):
        assert _is_user_context("hermes_sync") is False

    def test_sync_context_is_not_user_context(self):
        assert _is_user_context("sync:listener") is False


# ── enforce_action: AUTO_ALLOWED ────────────────────────────────────────────


class TestEnforceActionAutoAllowed:
    def test_auto_allowed_permits_execution(self, allow_all_engine):
        result = enforce_action(
            EnforcementAction.TASK_COMPLETION,
            context="cli",
            policy_engine=allow_all_engine,
        )
        assert result.allowed is True
        assert result.category == ClassificationCategory.AUTO_ALLOWED
        assert result.action == "task_completion"

    def test_auto_allowed_with_string_action(self, allow_all_engine):
        result = enforce_action(
            "task_completion",
            context="cli",
            policy_engine=allow_all_engine,
        )
        assert result.allowed is True

    def test_auto_allowed_with_default_engine(self):
        """Test with the default policy engine (no mock)."""
        result = enforce_action(
            EnforcementAction.TASK_COMPLETION,
            context="cli",
        )
        assert result.allowed is True
        assert result.category == ClassificationCategory.AUTO_ALLOWED


# ── enforce_action: APPROVAL_REQUIRED ───────────────────────────────────────


class TestEnforceActionApprovalRequired:
    def test_approval_required_blocks_execution(self, ask_all_engine):
        result = enforce_action(
            EnforcementAction.TASK_COMPLETION,
            context="cli",
            policy_engine=ask_all_engine,
        )
        assert result.allowed is False
        assert result.category == ClassificationCategory.APPROVAL_REQUIRED
        assert "requires human approval" in result.message

    def test_approval_required_message_is_actionable(self, ask_all_engine):
        result = enforce_action(
            EnforcementAction.GOAL_COMPLETION,
            context="cli",
            policy_engine=ask_all_engine,
        )
        assert result.allowed is False
        assert "goal_completion" in result.message
        assert "Risk: medium" in result.message
        assert "Impact: medium" in result.message

    def test_approval_required_with_default_engine(self):
        """Test with the default policy engine — goal completion requires approval."""
        result = enforce_action(
            EnforcementAction.GOAL_COMPLETION,
            context="cli",
        )
        assert result.allowed is False
        assert result.category == ClassificationCategory.APPROVAL_REQUIRED


# ── enforce_action: USER_ONLY ───────────────────────────────────────────────


class TestEnforceActionUserOnly:
    def test_user_only_in_user_context_allows(self, deny_all_engine):
        result = enforce_action(
            EnforcementAction.GOAL_DELETION,
            context="cli",
            policy_engine=deny_all_engine,
        )
        assert result.allowed is True
        assert result.category == ClassificationCategory.USER_ONLY

    def test_user_only_in_system_context_blocks(self, deny_all_engine):
        result = enforce_action(
            EnforcementAction.GOAL_DELETION,
            context="hermes_sync",
            policy_engine=deny_all_engine,
        )
        assert result.allowed is False
        assert result.category == ClassificationCategory.USER_ONLY
        assert "restricted to user contexts" in result.message

    def test_user_only_in_empty_context_blocks(self, deny_all_engine):
        result = enforce_action(
            EnforcementAction.GOAL_DELETION,
            context="",
            policy_engine=deny_all_engine,
        )
        assert result.allowed is False
        assert "restricted to user contexts" in result.message

    def test_user_only_message_is_actionable(self, deny_all_engine):
        result = enforce_action(
            EnforcementAction.GOAL_DELETION,
            context="automated:cleanup",
            policy_engine=deny_all_engine,
        )
        assert result.allowed is False
        assert "must be initiated by the user directly" in result.message


# ── enforce_action: risk/impact overrides ───────────────────────────────────


class TestEnforceActionRiskImpactOverrides:
    def test_risk_override(self, allow_all_engine):
        """Even with allow_all policy, explicit risk/impact can be passed."""
        result = enforce_action(
            EnforcementAction.TASK_COMPLETION,
            context="cli",
            risk=RiskLevel.HIGH,
            impact=ImpactLevel.HIGH,
            policy_engine=allow_all_engine,
        )
        # allow_all policy allows everything
        assert result.allowed is True

    def test_risk_override_with_default_engine(self):
        """With default policy, high-risk task completion requires approval."""
        result = enforce_action(
            EnforcementAction.TASK_COMPLETION,
            context="cli",
            risk=RiskLevel.HIGH,
            impact=ImpactLevel.HIGH,
        )
        assert result.allowed is False
        assert result.category == ClassificationCategory.APPROVAL_REQUIRED


# ── check_action_allowed ────────────────────────────────────────────────────


class TestCheckActionAllowed:
    def test_returns_true_for_auto_allowed(self, allow_all_engine):
        assert check_action_allowed(
            EnforcementAction.TASK_COMPLETION,
            context="cli",
            policy_engine=allow_all_engine,
        ) is True

    def test_returns_false_for_approval_required(self, ask_all_engine):
        assert check_action_allowed(
            EnforcementAction.TASK_COMPLETION,
            context="cli",
            policy_engine=ask_all_engine,
        ) is False

    def test_returns_false_for_user_only_in_system_context(self, deny_all_engine):
        assert check_action_allowed(
            EnforcementAction.GOAL_DELETION,
            context="hermes_sync",
            policy_engine=deny_all_engine,
        ) is False

    def test_returns_true_for_user_only_in_user_context(self, deny_all_engine):
        assert check_action_allowed(
            EnforcementAction.GOAL_DELETION,
            context="cli",
            policy_engine=deny_all_engine,
        ) is True


# ── enforce_or_raise ────────────────────────────────────────────────────────


class TestEnforceOrRaise:
    def test_returns_result_for_auto_allowed(self, allow_all_engine):
        result = enforce_or_raise(
            EnforcementAction.TASK_COMPLETION,
            context="cli",
            policy_engine=allow_all_engine,
        )
        assert result.allowed is True

    def test_raises_for_approval_required(self, ask_all_engine):
        with pytest.raises(EnforcementGateError) as exc_info:
            enforce_or_raise(
                EnforcementAction.TASK_COMPLETION,
                context="cli",
                policy_engine=ask_all_engine,
            )
        assert exc_info.value.result.allowed is False
        assert exc_info.value.result.category == ClassificationCategory.APPROVAL_REQUIRED

    def test_raises_for_user_only_in_system_context(self, deny_all_engine):
        with pytest.raises(EnforcementGateError) as exc_info:
            enforce_or_raise(
                EnforcementAction.GOAL_DELETION,
                context="hermes_sync",
                policy_engine=deny_all_engine,
            )
        assert exc_info.value.result.allowed is False
        assert exc_info.value.result.category == ClassificationCategory.USER_ONLY

    def test_error_message_is_actionable(self, ask_all_engine):
        with pytest.raises(EnforcementGateError) as exc_info:
            enforce_or_raise(
                EnforcementAction.GOAL_COMPLETION,
                context="cli",
                policy_engine=ask_all_engine,
            )
        assert "goal_completion" in str(exc_info.value)
        assert "requires human approval" in str(exc_info.value)


# ── EnforcementGateError ────────────────────────────────────────────────────


class TestEnforcementGateError:
    def test_carries_result(self):
        result = EnforcementResult(
            allowed=False,
            category=ClassificationCategory.APPROVAL_REQUIRED,
            action="test_action",
            message="Test message",
        )
        error = EnforcementGateError(result)
        assert error.result is result
        assert str(error) == "Test message"

    def test_is_runtime_error(self):
        result = EnforcementResult(
            allowed=False,
            category=ClassificationCategory.USER_ONLY,
            action="test_action",
            message="Test message",
        )
        error = EnforcementGateError(result)
        assert isinstance(error, RuntimeError)


# ── Integration with dispatch_completion ────────────────────────────────────


class TestDispatchCompletionIntegration:
    """Test that dispatch_completion applies the enforcement gate."""

    def test_blocked_action_returns_reason(self, tmp_path):
        """Test that a blocked action returns a clear reason."""
        from janus.services.execution_feedback import (
            EvidencePackage,
            JanusDomainMetadata,
            dispatch_completion,
        )

        metadata = JanusDomainMetadata(
            object="goal",
            title="Test Goal",
        )
        evidence = EvidencePackage(
            task_id="t_123",
            summary="Test task",
        )

        # Patch the policy engine to require approval for all actions
        with patch("janus.services.enforcement_gate.get_policy_engine") as mock_get:
            mock_engine = MagicMock()
            mock_engine.classify.return_value = ClassificationCategory.APPROVAL_REQUIRED
            mock_get.return_value = mock_engine

            result = dispatch_completion(metadata, evidence)

        assert result["blocked"] == "goal"
        assert "requires human approval" in result["reason"]
        assert result["category"] == "approval_required"

    def test_allowed_action_proceeds(self, tmp_path):
        """Test that an allowed action proceeds to dispatch."""
        from janus.services.execution_feedback import (
            EvidencePackage,
            JanusDomainMetadata,
            dispatch_completion,
        )

        metadata = JanusDomainMetadata(
            object="goal",
            title="Test Goal",
        )
        evidence = EvidencePackage(
            task_id="t_123",
            summary="Test task",
        )

        # Patch the policy engine to allow all actions
        with patch("janus.services.enforcement_gate.get_policy_engine") as mock_get:
            mock_engine = MagicMock()
            mock_engine.classify.return_value = ClassificationCategory.AUTO_ALLOWED
            mock_get.return_value = mock_engine

            # Patch the actual service function to avoid side effects
            with patch("janus.services.goals.update_goal_progress") as mock_update:
                mock_update.return_value = {"status": "ok"}
                result = dispatch_completion(metadata, evidence)

        assert "blocked" not in result
        assert result["goal"] == {"status": "ok"}

    def test_user_only_blocked_in_hermes_context(self, tmp_path):
        """Test that USER_ONLY actions are blocked in hermes_sync context."""
        from janus.services.execution_feedback import (
            EvidencePackage,
            JanusDomainMetadata,
            dispatch_completion,
        )

        metadata = JanusDomainMetadata(
            object="task",
            title="Test Task",
        )
        evidence = EvidencePackage(
            task_id="t_123",
            summary="Test task",
        )

        # Patch the policy engine to deny all actions (USER_ONLY)
        with patch("janus.services.enforcement_gate.get_policy_engine") as mock_get:
            mock_engine = MagicMock()
            mock_engine.classify.return_value = ClassificationCategory.USER_ONLY
            mock_get.return_value = mock_engine

            result = dispatch_completion(metadata, evidence)

        assert result["blocked"] == "task"
        assert "restricted to user contexts" in result["reason"]
        assert result["category"] == "user_only"


# ── Audit log integration ───────────────────────────────────────────────────


class TestAuditLogIntegration:
    def test_enforcement_decision_is_logged(self, allow_all_engine, tmp_path):
        """Test that enforcement decisions are written to the audit log."""
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

        assert audit_path.exists()
        content = audit_path.read_text(encoding="utf-8")
        assert "action=update" in content
        assert "decision=allow" in content
