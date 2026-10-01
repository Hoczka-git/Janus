"""Tests for the policy evaluation engine.

Design reference: docs/design/policy_approval_p1_design.md §11.1
"""

from __future__ import annotations

import pytest

from janus.models.policy import (
    PolicyVerdict,
    RiskLevel,
)
from janus.models.task_agency import TaskAgency
from janus.models.execution_mode import ExecutionMode
from janus.models.support_mode import SupportMode
from janus.services.policy import (
    POLICY_RULES,
    evaluate_policy,
    build_approval_request,
)


class TestPolicyRuleTable:
    def test_16_rules(self):
        assert len(POLICY_RULES) == 16

    def test_rule_ids_unique(self):
        rule_ids = [r.rule_id for r in POLICY_RULES]
        assert len(rule_ids) == len(set(rule_ids))

    def test_all_rules_have_required_fields(self):
        for rule in POLICY_RULES:
            assert rule.rule_id
            assert rule.action
            assert rule.risk_level in RiskLevel
            assert rule.verdict in PolicyVerdict
            assert rule.rationale
            assert rule.enforcement_point


class TestEvaluatePolicy:
    def test_r1_user_mode_allow(self):
        decision = evaluate_policy(
            action="task_execution",
            context="execution_mode=USER",
        )
        assert decision.verdict == PolicyVerdict.ALLOW
        assert decision.rule_id == "R1"

    def test_r2_janus_mode_allow(self):
        decision = evaluate_policy(
            action="task_execution",
            context="execution_mode=JANUS,support_mode=EXECUTE",
        )
        assert decision.verdict == PolicyVerdict.ALLOW
        assert decision.rule_id == "R2"

    def test_r3_collaborative_ask(self):
        decision = evaluate_policy(
            action="task_execution",
            context="execution_mode=COLLABORATIVE",
        )
        assert decision.verdict == PolicyVerdict.ASK
        assert decision.rule_id == "R3"

    def test_r4_assistive_allow(self):
        decision = evaluate_policy(
            action="task_execution",
            context="support_mode=EXPLAIN",
        )
        assert decision.verdict == PolicyVerdict.ALLOW
        assert decision.rule_id == "R4"

    def test_r5_review_ask(self):
        decision = evaluate_policy(
            action="task_execution",
            context="support_mode=REVIEW",
        )
        assert decision.verdict == PolicyVerdict.ASK
        assert decision.rule_id == "R5"

    def test_r6_goal_completion_ask(self):
        decision = evaluate_policy(action="goal_completion")
        assert decision.verdict == PolicyVerdict.ASK
        assert decision.rule_id == "R6"
        assert decision.gate_id == "G-2"

    def test_r7_knowledge_promotion_ask(self):
        decision = evaluate_policy(action="knowledge_promotion")
        assert decision.verdict == PolicyVerdict.ASK
        assert decision.rule_id == "R7"
        assert decision.gate_id == "G-3"

    def test_r8_external_read_allow(self):
        decision = evaluate_policy(action="external_read")
        assert decision.verdict == PolicyVerdict.ALLOW
        assert decision.rule_id == "R8"

    def test_r9_external_write_ask(self):
        decision = evaluate_policy(action="external_write")
        assert decision.verdict == PolicyVerdict.ASK
        assert decision.rule_id == "R9"
        assert decision.gate_id == "G-4"

    def test_r10_goal_deletion_deny(self):
        decision = evaluate_policy(action="goal_deletion")
        assert decision.verdict == PolicyVerdict.DENY
        assert decision.rule_id == "R10"
        assert decision.gate_id == "G-5"

    def test_r11_bulk_state_change_ask(self):
        decision = evaluate_policy(action="bulk_state_change")
        assert decision.verdict == PolicyVerdict.ASK
        assert decision.rule_id == "R11"
        assert decision.gate_id == "G-6"

    def test_r12_config_change_ask(self):
        decision = evaluate_policy(action="config_change")
        assert decision.verdict == PolicyVerdict.ASK
        assert decision.rule_id == "R12"
        assert decision.gate_id == "G-7"

    def test_r13_task_status_change_allow(self):
        decision = evaluate_policy(action="task_status_change")
        assert decision.verdict == PolicyVerdict.ALLOW
        assert decision.rule_id == "R13"

    def test_r14_task_completion_git_ask(self):
        decision = evaluate_policy(action="task_completion", context="git_repo")
        assert decision.verdict == PolicyVerdict.ASK
        assert decision.rule_id == "R14"
        assert decision.gate_id == "G-1"

    def test_r15_task_completion_non_git_allow(self):
        decision = evaluate_policy(action="task_completion", context="non_git")
        assert decision.verdict == PolicyVerdict.ALLOW
        assert decision.rule_id == "R15"

    def test_r16_evidence_less_goal_completion_deny(self):
        decision = evaluate_policy(action="goal_completion", context="no_evidence")
        assert decision.verdict == PolicyVerdict.DENY
        assert decision.rule_id == "R16"
        assert decision.gate_id == "G-2"


class TestEvaluatePolicyPrecedence:
    def test_most_restrictive_wins_deny_over_ask(self):
        # R10 (DENY) should win over R6 (ASK) for goal_deletion
        decision = evaluate_policy(action="goal_deletion")
        assert decision.verdict == PolicyVerdict.DENY

    def test_most_restrictive_wins_ask_over_allow(self):
        # R3 (ASK) should win over R1 (ALLOW) for collaborative task execution
        decision = evaluate_policy(
            action="task_execution",
            context="execution_mode=COLLABORATIVE",
        )
        assert decision.verdict == PolicyVerdict.ASK

    def test_no_matching_rules_defaults_to_deny(self):
        decision = evaluate_policy(action="unknown_action")
        assert decision.verdict == PolicyVerdict.DENY
        assert decision.rule_id == "DEFAULT"


class TestEvaluatePolicyWithTaskAgency:
    def test_task_agency_none_upgrades_allow_to_ask(self):
        # When task_agency is None and no context is provided for task_execution,
        # ALLOW is upgraded to ASK (conservative default)
        decision = evaluate_policy(
            action="task_execution",
            context=None,
            task_agency=None,
        )
        assert decision.verdict == PolicyVerdict.ASK

    def test_task_agency_provided_uses_agency_context(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
            reason="Test",
            confidence=0.9,
        )
        decision = evaluate_policy(
            action="task_execution",
            context="execution_mode=USER,support_mode=EXPLAIN",
            task_agency=agency,
        )
        assert decision.verdict == PolicyVerdict.ALLOW

    def test_task_agency_collaborative_triggers_ask(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.COLLABORATIVE,
            support_mode=SupportMode.EXECUTE,
            reason="Test",
            confidence=0.9,
        )
        decision = evaluate_policy(
            action="task_execution",
            context="execution_mode=COLLABORATIVE,support_mode=EXECUTE",
            task_agency=agency,
        )
        assert decision.verdict == PolicyVerdict.ASK


class TestBuildApprovalRequest:
    def test_builds_request_from_decision(self):
        from janus.services.policy import evaluate_policy

        decision = evaluate_policy(action="goal_completion")
        request = build_approval_request(
            decision=decision,
            action="goal_completion",
            context="goal_title=Test",
        )
        assert request.action == "goal_completion"
        assert request.context == "goal_title=Test"
        assert request.risk_level == RiskLevel.MEDIUM
        assert request.policy_rule == "R6"
        assert request.gate_id == "G-2"
        assert request.rationale
        assert request.what_approval_entails
        assert request.alternative
