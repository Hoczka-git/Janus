"""Action Proposal Engine protocol — the interface for proposal generation.

This module defines the :class:`ActionProposalEngine` protocol that all
proposal engine implementations must satisfy.

V1 is proposal-only: the engine generates ActionProposal objects but
never executes them. The interface explicitly excludes mutation methods
for tasks, goals, and calendar.

Design reference: docs/design/action_proposal_engine_v1.md
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from janus.planner.models import PlanningContext, WeeklyPlan
from janus.proposal.models import ActionProposal


@runtime_checkable
class ActionProposalEngine(Protocol):
    """Interface for action proposal engine implementations.

    Implementations must provide a single ``generate`` method that takes
    a WeeklyPlan and PlanningContext and returns a list of ActionProposal.

    The engine is proposal-only: it generates structured proposals but
    never executes them. No mutation methods are exposed.

    V1 implementation is ``RuleBasedProposalEngine`` (deterministic).
    Future implementations may use LLM-based proposal generation.

    Example usage::

        engine: ActionProposalEngine = RuleBasedProposalEngine()
        proposals = engine.generate(plan, context)
    """

    def generate(
        self,
        plan: WeeklyPlan,
        context: PlanningContext,
    ) -> list[ActionProposal]:
        """Generate action proposals from a weekly plan.

        Args:
            plan: The weekly plan to transform into proposals.
            context: The planning context with goals, tasks, calendar.

        Returns:
            A list of validated action proposals. May be empty if no
            actions are proposed.

        Raises:
            ValueError: If the plan or context is invalid.
        """
        ...
