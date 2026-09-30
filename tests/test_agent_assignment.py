"""Tests for AgentAssignment dataclass.

Covers:
- Field types and defaults
- Construction with all fields
- Construction with minimal fields
"""

from janus.models.agent_assignment import AgentAssignment
from janus.models.agent_role import AgentRole
from janus.models.execution_mode import ExecutionMode
from janus.models.support_mode import SupportMode


class TestAgentAssignment:
    def test_minimal_construction(self):
        assignment = AgentAssignment(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
        )
        assert assignment.execution_mode == ExecutionMode.USER
        assert assignment.support_mode == SupportMode.EXPLAIN
        assert assignment.agent_role is None
        assert assignment.reason == ""
        assert assignment.confidence == 0.5
        assert assignment.required_capabilities is None

    def test_full_construction(self):
        assignment = AgentAssignment(
            execution_mode=ExecutionMode.JANUS,
            support_mode=SupportMode.EXECUTE,
            agent_role=AgentRole.EXECUTOR,
            reason="Task requires implementation",
            confidence=0.9,
            required_capabilities=["implement-feature", "run-tests"],
        )
        assert assignment.execution_mode == ExecutionMode.JANUS
        assert assignment.support_mode == SupportMode.EXECUTE
        assert assignment.agent_role == AgentRole.EXECUTOR
        assert assignment.reason == "Task requires implementation"
        assert assignment.confidence == 0.9
        assert assignment.required_capabilities == ["implement-feature", "run-tests"]

    def test_agent_role_optional(self):
        assignment = AgentAssignment(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.SCAFFOLD,
            agent_role=None,
        )
        assert assignment.agent_role is None

    def test_required_capabilities_default_none(self):
        assignment = AgentAssignment(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
        )
        assert assignment.required_capabilities is None

    def test_required_capabilities_can_be_set(self):
        assignment = AgentAssignment(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
            required_capabilities=["plan-roadmap"],
        )
        assert assignment.required_capabilities == ["plan-roadmap"]

    def test_confidence_default(self):
        assignment = AgentAssignment(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
        )
        assert assignment.confidence == 0.5

    def test_reason_default(self):
        assignment = AgentAssignment(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
        )
        assert assignment.reason == ""
