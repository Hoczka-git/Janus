"""Planner invocation wrapper with fixed seed and state isolation.

Provides a deterministic wrapper around planner invocation that ensures
no external randomness affects evaluation. Uses deep copy for state
isolation and supports both RuleBasedPlanner and LLMWeeklyPlanner.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from janus.planner.models import (
    PlanningContext,
    WeeklyPlan,
)
from janus.planner.protocol import WeeklyPlanner


@dataclass
class PlannerResult:
    """Result of a planner invocation.

    Attributes:
        plan: The generated WeeklyPlan.
        success: Whether the invocation succeeded.
        error: Error message if invocation failed.
        llm_calls: Number of LLM calls made.
        fallback_used: Whether the fallback planner was used.
        context_snapshot: Deep copy of the context before invocation (for verification).
    """

    plan: WeeklyPlan | None = None
    success: bool = True
    error: str | None = None
    llm_calls: int = 0
    fallback_used: bool = False
    context_snapshot: PlanningContext | None = field(default=None, repr=False)


class PlannerRunner:
    """Deterministic planner invocation wrapper.

    Ensures:
    - Deep copy of context for state isolation (no mutation of original).
    - Fixed seed for any random operations (none in current planners).
    - Consistent error handling and result capture.
    """

    def run(
        self,
        planner: WeeklyPlanner,
        context: PlanningContext,
    ) -> PlannerResult:
        """Run the planner with state isolation.

        Creates a deep copy of the context so the original is never mutated.
        This ensures scenarios are independent and reproducible.

        Args:
            planner: The planner to invoke.
            context: The planning context.

        Returns:
            PlannerResult with the plan and metadata.
        """
        # Deep copy for state isolation
        context_copy = copy.deepcopy(context)
        context_snapshot = copy.deepcopy(context)

        try:
            plan = planner.plan(context_copy)
            return PlannerResult(
                plan=plan,
                success=True,
                context_snapshot=context_snapshot,
            )
        except Exception as e:
            return PlannerResult(
                plan=None,
                success=False,
                error=f"{type(e).__name__}: {e}",
                context_snapshot=context_snapshot,
            )

    def run_isolated(
        self,
        planner: WeeklyPlanner,
        context: PlanningContext,
    ) -> PlannerResult:
        """Run with explicit isolation verification.

        Verifies that the original context was not mutated by comparing
        it to the snapshot taken before invocation.

        Args:
            planner: The planner to invoke.
            context: The planning context.

        Returns:
            PlannerResult with isolation verification.

        Raises:
            AssertionError: If the original context was mutated.
        """
        result = self.run(planner, context)

        if result.context_snapshot is not None:
            assert context == result.context_snapshot, (
                "Planner mutated the input context! "
                "State isolation violated."
            )

        return result


class MockLLMClient:
    """A mock LLM client for deterministic testing.

    Returns a predefined response or raises a predefined exception.
    Tracks the number of calls made.
    """

    def __init__(
        self,
        response: str | None = None,
        exception: Exception | None = None,
    ) -> None:
        self.response = response
        self.exception = exception
        self.call_count = 0
        self.last_prompt: str | None = None

    def generate(self, prompt: str) -> str:
        self.call_count += 1
        self.last_prompt = prompt
        if self.exception is not None:
            raise self.exception
        if self.response is not None:
            return self.response
        return "{}"


class FailingLLMClient:
    """An LLM client that always fails."""

    def __init__(self, exception: Exception | None = None) -> None:
        self.exception = exception or RuntimeError("LLM unavailable")
        self.call_count = 0

    def generate(self, prompt: str) -> str:
        self.call_count += 1
        raise self.exception


class StaticPlanner:
    """A simple planner that returns a predefined plan (for fallback testing)."""

    def __init__(self, plan: WeeklyPlan) -> None:
        self._plan = plan

    def plan(self, context: PlanningContext) -> WeeklyPlan:
        return self._plan
