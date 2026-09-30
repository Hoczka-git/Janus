"""Tests for AgentRole enum.

Covers:
- Enum member count and values
- String representation
- Membership testing
"""

from janus.models.agent_role import AgentRole


class TestAgentRole:
    def test_has_five_members(self):
        assert len(AgentRole) == 5

    def test_member_values(self):
        assert AgentRole.PLANNER == "planner"
        assert AgentRole.RESEARCHER == "researcher"
        assert AgentRole.EXECUTOR == "executor"
        assert AgentRole.REVIEWER == "reviewer"
        assert AgentRole.COACH == "coach"

    def test_member_names(self):
        assert AgentRole.PLANNER.name == "PLANNER"
        assert AgentRole.RESEARCHER.name == "RESEARCHER"
        assert AgentRole.EXECUTOR.name == "EXECUTOR"
        assert AgentRole.REVIEWER.name == "REVIEWER"
        assert AgentRole.COACH.name == "COACH"

    def test_string_representation(self):
        assert str(AgentRole.PLANNER) == "planner"
        assert str(AgentRole.RESEARCHER) == "researcher"
        assert str(AgentRole.EXECUTOR) == "executor"
        assert str(AgentRole.REVIEWER) == "reviewer"
        assert str(AgentRole.COACH) == "coach"

    def test_membership(self):
        assert AgentRole.PLANNER in AgentRole
        assert AgentRole.RESEARCHER in AgentRole
        assert AgentRole.EXECUTOR in AgentRole
        assert AgentRole.REVIEWER in AgentRole
        assert AgentRole.COACH in AgentRole

    def test_from_value(self):
        assert AgentRole("planner") == AgentRole.PLANNER
        assert AgentRole("researcher") == AgentRole.RESEARCHER
        assert AgentRole("executor") == AgentRole.EXECUTOR
        assert AgentRole("reviewer") == AgentRole.REVIEWER
        assert AgentRole("coach") == AgentRole.COACH

    def test_invalid_value_raises(self):
        import pytest
        with pytest.raises(ValueError):
            AgentRole("invalid")
