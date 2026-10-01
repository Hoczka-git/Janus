"""Tests for AgentAssignment serialization and validation.

Covers:
- __post_init__ validation (type checks, confidence bounds, capabilities)
- to_dict serialization
- from_dict deserialization
- Round-trip (to_dict → from_dict)
- Default values in from_dict
"""

import pytest

from janus.models.agent_assignment import AgentAssignment
from janus.models.agent_role import AgentRole
from janus.models.execution_mode import ExecutionMode
from janus.models.support_mode import SupportMode


class TestAgentAssignmentValidation:
    """Tests for __post_init__ validation."""

    def test_valid_construction(self):
        assignment = AgentAssignment(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
            reason="Test reason",
            confidence=0.7,
        )
        assert assignment.execution_mode == ExecutionMode.USER
        assert assignment.support_mode == SupportMode.EXPLAIN
        assert assignment.reason == "Test reason"
        assert assignment.confidence == 0.7

    def test_invalid_execution_mode_type(self):
        with pytest.raises(TypeError, match="execution_mode must be an ExecutionMode"):
            AgentAssignment(
                execution_mode="user",  # type: ignore[arg-type]
                support_mode=SupportMode.EXPLAIN,
                reason="Test",
            )

    def test_invalid_support_mode_type(self):
        with pytest.raises(TypeError, match="support_mode must be a SupportMode"):
            AgentAssignment(
                execution_mode=ExecutionMode.USER,
                support_mode="explain",  # type: ignore[arg-type]
                reason="Test",
            )

    def test_invalid_agent_role_type(self):
        with pytest.raises(TypeError, match="agent_role must be an AgentRole or None"):
            AgentAssignment(
                execution_mode=ExecutionMode.USER,
                support_mode=SupportMode.EXPLAIN,
                agent_role="executor",  # type: ignore[arg-type]
                reason="Test",
            )

    def test_invalid_reason_type(self):
        with pytest.raises(TypeError, match="reason must be a str"):
            AgentAssignment(
                execution_mode=ExecutionMode.USER,
                support_mode=SupportMode.EXPLAIN,
                reason=123,  # type: ignore[arg-type]
            )

    def test_invalid_confidence_type(self):
        with pytest.raises(TypeError, match="confidence must be a number"):
            AgentAssignment(
                execution_mode=ExecutionMode.USER,
                support_mode=SupportMode.EXPLAIN,
                reason="Test",
                confidence="high",  # type: ignore[arg-type]
            )

    def test_confidence_below_zero(self):
        with pytest.raises(ValueError, match="confidence must be between 0.0 and 1.0"):
            AgentAssignment(
                execution_mode=ExecutionMode.USER,
                support_mode=SupportMode.EXPLAIN,
                reason="Test",
                confidence=-0.1,
            )

    def test_confidence_above_one(self):
        with pytest.raises(ValueError, match="confidence must be between 0.0 and 1.0"):
            AgentAssignment(
                execution_mode=ExecutionMode.USER,
                support_mode=SupportMode.EXPLAIN,
                reason="Test",
                confidence=1.1,
            )

    def test_invalid_required_capabilities_type(self):
        with pytest.raises(TypeError, match="required_capabilities must be a list or None"):
            AgentAssignment(
                execution_mode=ExecutionMode.USER,
                support_mode=SupportMode.EXPLAIN,
                reason="Test",
                required_capabilities="implement-feature",  # type: ignore[arg-type]
            )

    def test_invalid_required_capabilities_item_type(self):
        with pytest.raises(TypeError, match="required_capabilities items must be str"):
            AgentAssignment(
                execution_mode=ExecutionMode.USER,
                support_mode=SupportMode.EXPLAIN,
                reason="Test",
                required_capabilities=[123],  # type: ignore[list-item]
            )

    def test_valid_required_capabilities(self):
        assignment = AgentAssignment(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
            reason="Test",
            required_capabilities=["implement-feature", "run-tests"],
        )
        assert assignment.required_capabilities == ["implement-feature", "run-tests"]

    def test_none_required_capabilities_valid(self):
        assignment = AgentAssignment(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
            reason="Test",
            required_capabilities=None,
        )
        assert assignment.required_capabilities is None

    def test_empty_list_required_capabilities_valid(self):
        assignment = AgentAssignment(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
            reason="Test",
            required_capabilities=[],
        )
        assert assignment.required_capabilities == []


class TestAgentAssignmentSerialization:
    """Tests for to_dict and from_dict."""

    def test_to_dict_full(self):
        assignment = AgentAssignment(
            execution_mode=ExecutionMode.JANUS,
            support_mode=SupportMode.EXECUTE,
            agent_role=AgentRole.EXECUTOR,
            reason="Admin task",
            confidence=0.8,
            required_capabilities=["implement-feature"],
        )
        d = assignment.to_dict()
        assert d == {
            "execution_mode": "janus",
            "support_mode": "execute",
            "agent_role": "executor",
            "reason": "Admin task",
            "confidence": 0.8,
            "required_capabilities": ["implement-feature"],
        }

    def test_to_dict_minimal(self):
        assignment = AgentAssignment(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
        )
        d = assignment.to_dict()
        assert d == {
            "execution_mode": "user",
            "support_mode": "explain",
            "agent_role": None,
            "reason": "",
            "confidence": 0.5,
            "required_capabilities": None,
        }

    def test_from_dict_full(self):
        data = {
            "execution_mode": "collaborative",
            "support_mode": "scaffold",
            "agent_role": "planner",
            "reason": "Complex task",
            "confidence": 0.6,
            "required_capabilities": ["plan-roadmap"],
        }
        assignment = AgentAssignment.from_dict(data)
        assert assignment.execution_mode == ExecutionMode.COLLABORATIVE
        assert assignment.support_mode == SupportMode.SCAFFOLD
        assert assignment.agent_role == AgentRole.PLANNER
        assert assignment.reason == "Complex task"
        assert assignment.confidence == 0.6
        assert assignment.required_capabilities == ["plan-roadmap"]

    def test_from_dict_defaults(self):
        assignment = AgentAssignment.from_dict({})
        assert assignment.execution_mode == ExecutionMode.USER
        assert assignment.support_mode == SupportMode.EXPLAIN
        assert assignment.agent_role is None
        assert assignment.reason == ""
        assert assignment.confidence == 0.5
        assert assignment.required_capabilities is None

    def test_from_dict_partial(self):
        assignment = AgentAssignment.from_dict({"execution_mode": "janus"})
        assert assignment.execution_mode == ExecutionMode.JANUS
        assert assignment.support_mode == SupportMode.EXPLAIN  # default
        assert assignment.agent_role is None  # default
        assert assignment.reason == ""  # default
        assert assignment.confidence == 0.5  # default
        assert assignment.required_capabilities is None  # default

    def test_from_dict_with_agent_role(self):
        assignment = AgentAssignment.from_dict({"agent_role": "reviewer"})
        assert assignment.agent_role == AgentRole.REVIEWER

    def test_from_dict_without_agent_role(self):
        assignment = AgentAssignment.from_dict({"agent_role": None})
        assert assignment.agent_role is None

    def test_round_trip(self):
        original = AgentAssignment(
            execution_mode=ExecutionMode.COLLABORATIVE,
            support_mode=SupportMode.COACH,
            agent_role=AgentRole.COACH,
            reason="Stalled goal",
            confidence=0.7,
            required_capabilities=["skill-development"],
        )
        d = original.to_dict()
        restored = AgentAssignment.from_dict(d)
        assert restored.execution_mode == original.execution_mode
        assert restored.support_mode == original.support_mode
        assert restored.agent_role == original.agent_role
        assert restored.reason == original.reason
        assert restored.confidence == original.confidence
        assert restored.required_capabilities == original.required_capabilities

    def test_to_dict_returns_dict(self):
        assignment = AgentAssignment(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
        )
        d = assignment.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_values_are_strings(self):
        assignment = AgentAssignment(
            execution_mode=ExecutionMode.JANUS,
            support_mode=SupportMode.EXECUTE,
            agent_role=AgentRole.EXECUTOR,
            reason="Test",
        )
        d = assignment.to_dict()
        assert isinstance(d["execution_mode"], str)
        assert isinstance(d["support_mode"], str)
        assert isinstance(d["agent_role"], str)
        assert isinstance(d["reason"], str)
        assert isinstance(d["confidence"], float)

    def test_from_dict_invalid_execution_mode(self):
        with pytest.raises(ValueError):
            AgentAssignment.from_dict({"execution_mode": "invalid"})

    def test_from_dict_invalid_support_mode(self):
        with pytest.raises(ValueError):
            AgentAssignment.from_dict({"support_mode": "invalid"})

    def test_from_dict_invalid_agent_role(self):
        with pytest.raises(ValueError):
            AgentAssignment.from_dict({"agent_role": "invalid"})
