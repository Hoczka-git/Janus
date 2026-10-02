"""WeeklyPlanner protocol — the interface for weekly planner implementations.

This module defines the :class:`WeeklyPlanner` protocol that all weekly
planner implementations must satisfy.  The first implementation will be
``LLMWeeklyPlanner`` (in a separate module), but the architecture also
supports ``RuleBasedPlanner`` and ``MockPlanner`` without changes to the
rest of the application.

The protocol is defined in ``docs/design/janus_weekly_planner_v1.md`` §4
(Domain model) as::

    class WeeklyPlanner(Protocol):
        def plan(
            self,
            context: PlanningContext,
        ) -> WeeklyPlan:
            ...
"""

from __future__ import annotations

from typing import Protocol

from janus.planner.models import PlanningContext, WeeklyPlan


class WeeklyPlanner(Protocol):
    """Interface for weekly planner implementations.

    Implementations must provide a single ``plan`` method that takes a
    :class:`PlanningContext` and returns a :class:`WeeklyPlan`.

    The first implementation is ``LLMWeeklyPlanner``.  The architecture
    also supports ``RuleBasedPlanner`` and ``MockPlanner`` for testing
    and fallback scenarios.

    Example usage::

        planner: WeeklyPlanner = LLMWeeklyPlanner(...)
        plan = planner.plan(context)
    """

    def plan(
        self,
        context: PlanningContext,
    ) -> WeeklyPlan:
        """Generate a weekly plan from the given context.

        Args:
            context: The planning context containing goals, tasks,
                calendar events, and pre-computed deterministic signals.

        Returns:
            A complete weekly plan with summary, priorities, scheduled
            tasks, and identified risks.

        Raises:
            ValueError: If the context is invalid or incomplete.
            RuntimeError: If the planner fails to generate a valid plan.
        """
        ...
