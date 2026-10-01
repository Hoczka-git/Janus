"""Tests for policy data models.

Design reference: docs/design/policy_approval_p1_design.md §11.1
"""

from __future__ import annotations

from datetime import datetime

import pytest

from janus.models.policy import (
    ApprovalRecord,
    ApprovalRequest,
    ApprovalResponse,
    PolicyDecision,
    PolicyRule,
    PolicyVerdict,
    RiskLevel,
)


class TestPolicyVerdict:
    def test_members(self):
        assert PolicyVerdict.ALLOW == "allow"
        assert PolicyVerdict.ASK == "ask"
        assert PolicyVerdict.DENY == "deny"

    def test_str_enum(self):
        assert isinstance(PolicyVerdict.ALLOW, str)
        assert isinstance(PolicyVerdict.ASK, str)
        assert isinstance(PolicyVerdict.DENY, str)


class TestRiskLevel:
    def test_members(self):
        assert RiskLevel.LOW == "low"
        assert RiskLevel.MEDIUM == "medium"
        assert RiskLevel.HIGH == "high"

    def test_str_enum(self):
        assert isinstance(RiskLevel.LOW, str)
        assert isinstance(RiskLevel.MEDIUM, str)
        assert isinstance(RiskLevel.HIGH, str)


class TestPolicyRule:
    def test_construction(self):
        rule = PolicyRule(
            rule_id="R1",
            action="task_execution",
            context="execution_mode=USER",
            risk_level=RiskLevel.LOW,
            verdict=PolicyVerdict.ALLOW,
            rationale="Test rule",
            enforcement_point="test",
        )
        assert rule.rule_id == "R1"
        assert rule.action == "task_execution"
        assert rule.context == "execution_mode=USER"
        assert rule.risk_level == RiskLevel.LOW
        assert rule.verdict == PolicyVerdict.ALLOW
        assert rule.rationale == "Test rule"
        assert rule.enforcement_point == "test"
        assert rule.gate_id is None

    def test_frozen(self):
        rule = PolicyRule(
            rule_id="R1",
            action="task_execution",
            context="",
            risk_level=RiskLevel.LOW,
            verdict=PolicyVerdict.ALLOW,
            rationale="Test",
            enforcement_point="test",
        )
        with pytest.raises(AttributeError):
            rule.rule_id = "R2"

    def test_gate_id_optional(self):
        rule = PolicyRule(
            rule_id="R6",
            action="goal_completion",
            context="",
            risk_level=RiskLevel.MEDIUM,
            verdict=PolicyVerdict.ASK,
            rationale="Test",
            enforcement_point="test",
            gate_id="G-2",
        )
        assert rule.gate_id == "G-2"


class TestPolicyDecision:
    def test_construction(self):
        decision = PolicyDecision(
            rule_id="R1",
            verdict=PolicyVerdict.ALLOW,
            risk_level=RiskLevel.LOW,
            rationale="Test",
        )
        assert decision.rule_id == "R1"
        assert decision.verdict == PolicyVerdict.ALLOW
        assert decision.risk_level == RiskLevel.LOW
        assert decision.rationale == "Test"
        assert decision.gate_id is None
        assert decision.enforcement_point == ""

    def test_with_gate_id(self):
        decision = PolicyDecision(
            rule_id="R6",
            verdict=PolicyVerdict.ASK,
            risk_level=RiskLevel.MEDIUM,
            rationale="Test",
            gate_id="G-2",
            enforcement_point="test",
        )
        assert decision.gate_id == "G-2"
        assert decision.enforcement_point == "test"


class TestApprovalRequest:
    def test_construction(self):
        request = ApprovalRequest(
            action="goal_completion",
            context="goal_title=Test",
            risk_level=RiskLevel.MEDIUM,
            policy_rule="R6",
            rationale="Test",
            what_approval_entails="Proceed",
            alternative="Block",
        )
        assert request.action == "goal_completion"
        assert request.context == "goal_title=Test"
        assert request.risk_level == RiskLevel.MEDIUM
        assert request.policy_rule == "R6"
        assert request.rationale == "Test"
        assert request.what_approval_entails == "Proceed"
        assert request.alternative == "Block"
        assert request.gate_id is None


class TestApprovalResponse:
    def test_members(self):
        assert ApprovalResponse.APPROVE == "approve"
        assert ApprovalResponse.DENY == "deny"
        assert ApprovalResponse.DEFER == "defer"

    def test_str_enum(self):
        assert isinstance(ApprovalResponse.APPROVE, str)


class TestApprovalRecord:
    def test_construction(self):
        request = ApprovalRequest(
            action="test",
            context="test",
            risk_level=RiskLevel.LOW,
            policy_rule="R1",
            rationale="Test",
            what_approval_entails="Proceed",
            alternative="Block",
        )
        record = ApprovalRecord(
            request=request,
            response=ApprovalResponse.APPROVE,
        )
        assert record.request is request
        assert record.response == ApprovalResponse.APPROVE
        assert record.decided_by == "user"
        assert isinstance(record.decided_at, datetime)

    def test_custom_decided_by(self):
        request = ApprovalRequest(
            action="test",
            context="test",
            risk_level=RiskLevel.LOW,
            policy_rule="R1",
            rationale="Test",
            what_approval_entails="Proceed",
            alternative="Block",
        )
        record = ApprovalRecord(
            request=request,
            response=ApprovalResponse.DENY,
            decided_by="admin",
        )
        assert record.decided_by == "admin"
