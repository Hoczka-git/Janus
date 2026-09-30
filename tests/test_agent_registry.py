"""Tests for AgentRegistry.

Covers:
- Default role registration
- Capability matching
- Role lookup
- Custom registration
"""

from janus.models.agent_role import AgentRole
from janus.services.agent_registry import AgentCapability, AgentDefinition, AgentRegistry


class TestAgentRegistry:
    def test_default_roles_registered(self):
        registry = AgentRegistry()
        roles = registry.all_roles()
        assert AgentRole.PLANNER in roles
        assert AgentRole.RESEARCHER in roles
        assert AgentRole.EXECUTOR in roles
        assert AgentRole.REVIEWER in roles
        assert AgentRole.COACH in roles

    def test_get_existing_role(self):
        registry = AgentRegistry()
        agent = registry.get(AgentRole.PLANNER)
        assert agent is not None
        assert agent.role == AgentRole.PLANNER

    def test_get_nonexistent_role_returns_none(self):
        registry = AgentRegistry()
        # All default roles exist, so we test with a fresh registry
        # that has no registrations
        empty_registry = AgentRegistry()
        empty_registry._agents = {}
        assert empty_registry.get(AgentRole.PLANNER) is None

    def test_capabilities_for_role(self):
        registry = AgentRegistry()
        caps = registry.capabilities_for(AgentRole.PLANNER)
        assert "plan-roadmap" in caps
        assert "task-sequencing" in caps

    def test_capabilities_for_nonexistent_role(self):
        registry = AgentRegistry()
        registry._agents = {}
        assert registry.capabilities_for(AgentRole.PLANNER) == []

    def test_match_capabilities_planner(self):
        registry = AgentRegistry()
        role = registry.match_capabilities(["plan-roadmap"])
        assert role == AgentRole.PLANNER

    def test_match_capabilities_researcher(self):
        registry = AgentRegistry()
        role = registry.match_capabilities(["research-literature"])
        assert role == AgentRole.RESEARCHER

    def test_match_capabilities_executor(self):
        registry = AgentRegistry()
        role = registry.match_capabilities(["implement-feature"])
        assert role == AgentRole.EXECUTOR

    def test_match_capabilities_reviewer(self):
        registry = AgentRegistry()
        role = registry.match_capabilities(["review-code"])
        assert role == AgentRole.REVIEWER

    def test_match_capabilities_coach(self):
        registry = AgentRegistry()
        role = registry.match_capabilities(["explain-concept"])
        assert role == AgentRole.COACH

    def test_match_capabilities_empty_list(self):
        registry = AgentRegistry()
        assert registry.match_capabilities([]) is None

    def test_match_capabilities_no_match(self):
        registry = AgentRegistry()
        assert registry.match_capabilities(["nonexistent-capability"]) is None

    def test_match_capabilities_multiple_matches(self):
        """When multiple roles match, the one with most matches wins."""
        registry = AgentRegistry()
        # "implement-feature" matches EXECUTOR, "run-tests" also matches EXECUTOR
        role = registry.match_capabilities(["implement-feature", "run-tests"])
        assert role == AgentRole.EXECUTOR

    def test_register_custom_agent(self):
        registry = AgentRegistry()
        custom_role = AgentRole.PLANNER
        registry.register(AgentDefinition(
            role=custom_role,
            capabilities=[AgentCapability("custom-cap", "Custom capability")],
            description="Custom agent",
        ))
        agent = registry.get(custom_role)
        assert agent is not None
        assert "custom-cap" in registry.capabilities_for(custom_role)
