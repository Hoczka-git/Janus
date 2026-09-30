"""Agent registry for multi-agent orchestration.

Maps agent roles to their capabilities. The registry is the capability
index that the dispatch function uses to match tasks to agent roles.

Design reference: docs/design/phase_h_multi_agent_orchestration.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from janus.models.agent_role import AgentRole

logger = logging.getLogger(__name__)


@dataclass
class AgentCapability:
    """A capability provided by an agent role."""

    name: str
    description: str = ""


@dataclass
class AgentDefinition:
    """Definition of an agent role and its capabilities."""

    role: AgentRole
    capabilities: list[AgentCapability] = field(default_factory=list)
    description: str = ""


class AgentRegistry:
    """Registry of available agent roles and their capabilities.

    The registry maps each AgentRole to its set of capabilities. This is
    the capability index that the dispatch function uses to match tasks
    to agent roles.

    The registry is populated with default role-to-capability mappings.
    In a fuller implementation, this would be backed by the Phase G
    skill registry.
    """

    def __init__(self) -> None:
        self._agents: dict[AgentRole, AgentDefinition] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default agent role definitions."""
        self.register(AgentDefinition(
            role=AgentRole.PLANNER,
            capabilities=[
                AgentCapability("plan-roadmap", "Goal decomposition and milestone planning"),
                AgentCapability("task-sequencing", "Task sequencing and dependency analysis"),
            ],
            description="Goal decomposition, milestone planning, task sequencing",
        ))
        self.register(AgentDefinition(
            role=AgentRole.RESEARCHER,
            capabilities=[
                AgentCapability("research-literature", "Literature search and web research"),
                AgentCapability("data-gathering", "Data gathering and synthesis"),
            ],
            description="Literature search, web research, data gathering, synthesis",
        ))
        self.register(AgentDefinition(
            role=AgentRole.EXECUTOR,
            capabilities=[
                AgentCapability("implement-feature", "Code implementation and file operations"),
                AgentCapability("run-tests", "Test running and verification"),
            ],
            description="Code implementation, file operations, CLI execution, test running",
        ))
        self.register(AgentDefinition(
            role=AgentRole.REVIEWER,
            capabilities=[
                AgentCapability("review-code", "Code review and quality assessment"),
                AgentCapability("verify-implementation", "Verification and evidence validation"),
            ],
            description="Code review, verification, quality assessment, evidence validation",
        ))
        self.register(AgentDefinition(
            role=AgentRole.COACH,
            capabilities=[
                AgentCapability("explain-concept", "Explanation and scaffolding"),
                AgentCapability("skill-development", "Skill development and guidance"),
            ],
            description="Guidance, explanation, scaffolding, skill development",
        ))

    def register(self, agent: AgentDefinition) -> None:
        """Register an agent definition."""
        self._agents[agent.role] = agent

    def get(self, role: AgentRole) -> AgentDefinition | None:
        """Get the agent definition for a role."""
        return self._agents.get(role)

    def capabilities_for(self, role: AgentRole) -> list[str]:
        """Get the capability names for a role."""
        agent = self._agents.get(role)
        if agent is None:
            return []
        return [cap.name for cap in agent.capabilities]

    def match_capabilities(self, required: list[str]) -> AgentRole | None:
        """Match required capabilities to an agent role.

        Returns the role with the most matching capabilities, or None
        if no role matches.
        """
        if not required:
            return None

        best_role: AgentRole | None = None
        best_score = 0

        for role, agent in self._agents.items():
            role_caps = {cap.name for cap in agent.capabilities}
            score = len(set(required) & role_caps)
            if score > best_score:
                best_score = score
                best_role = role

        return best_role if best_score > 0 else None

    def all_roles(self) -> list[AgentRole]:
        """Get all registered agent roles."""
        return list(self._agents.keys())
