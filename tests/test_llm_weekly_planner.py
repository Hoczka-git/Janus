"""Tests for the LLM weekly planner implementation."""

from __future__ import annotations

import json
from datetime import date

import pytest

from janus.models.event import Event
from janus.models.goal import Goal
from janus.models.task import Task
from janus.planner import (
    LLMClient,
    LLMWeeklyPlanner,
    PlannedTask,
    PlanningContext,
    PlanningRisk,
    PlanningSignals,
    Priority,
    PriorityEntry,
    RiskSeverity,
    WeeklyPlan,
    WeeklyPlanner,
)


# ── Mock LLM client ─────────────────────────────────────────────────────────


class MockLLMClient:
    """A mock LLM client for testing.

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


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_context() -> PlanningContext:
    """Create a minimal planning context for testing."""
    goal = Goal(title="Career")
    task = Task(title="Write plan")
    event = Event(title="Meeting")
    return PlanningContext(
        goals=[goal],
        tasks=[task],
        calendar=[event],
    )


def _make_valid_response() -> str:
    """Create a valid LLM response JSON."""
    return json.dumps({
        "week_summary": "A focused week on career development.",
        "priorities": [
            {
                "goal_id": "Career",
                "reason": "Urgent deadline",
                "priority": "high",
            }
        ],
        "planned_tasks": [
            {
                "task_id": "Write plan",
                "goal_id": "Career",
                "priority": "high",
                "reason": "Overdue",
                "suggested_day": "2026-10-05",
            }
        ],
        "risks": [
            {
                "description": "Career goal has no completed actions",
                "severity": "medium",
            }
        ],
    })


def _make_empty_response() -> str:
    """Create a valid LLM response JSON with no priorities/tasks/risks."""
    return json.dumps({
        "week_summary": "A quiet week.",
        "priorities": [],
        "planned_tasks": [],
        "risks": [],
    })


# ── Protocol conformance ────────────────────────────────────────────────────


class TestProtocolConformance:
    def test_llm_weekly_planner_satisfies_protocol(self) -> None:
        client = MockLLMClient(response=_make_valid_response())
        planner: WeeklyPlanner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        plan = planner.plan(ctx)
        assert isinstance(plan, WeeklyPlan)

    def test_llm_client_is_protocol(self) -> None:
        assert hasattr(LLMClient, "_is_protocol")
        assert getattr(LLMClient, "_is_protocol") is True


# ── Initialization ──────────────────────────────────────────────────────────


class TestInitialization:
    def test_default_max_retries(self) -> None:
        client = MockLLMClient()
        planner = LLMWeeklyPlanner(client=client)
        assert planner._max_retries == 2

    def test_custom_max_retries(self) -> None:
        client = MockLLMClient()
        planner = LLMWeeklyPlanner(client=client, max_retries=5)
        assert planner._max_retries == 5

    def test_negative_max_retries_raises(self) -> None:
        client = MockLLMClient()
        with pytest.raises(ValueError, match="max_retries must be >= 0"):
            LLMWeeklyPlanner(client=client, max_retries=-1)

    def test_fallback_stored(self) -> None:
        client = MockLLMClient()
        fallback = StaticPlanner(WeeklyPlan(week_summary="fallback"))
        planner = LLMWeeklyPlanner(client=client, fallback=fallback)
        assert planner._fallback is fallback


# ── Prompt building ─────────────────────────────────────────────────────────


class TestPromptBuilding:
    def test_prompt_contains_goals(self) -> None:
        client = MockLLMClient(response=_make_valid_response())
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        planner.plan(ctx)
        assert client.last_prompt is not None
        assert "Career" in client.last_prompt

    def test_prompt_contains_tasks(self) -> None:
        client = MockLLMClient(response=_make_valid_response())
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        planner.plan(ctx)
        assert client.last_prompt is not None
        assert "Write plan" in client.last_prompt

    def test_prompt_contains_calendar(self) -> None:
        client = MockLLMClient(response=_make_valid_response())
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        planner.plan(ctx)
        assert client.last_prompt is not None
        assert "Meeting" in client.last_prompt

    def test_prompt_contains_signals(self) -> None:
        client = MockLLMClient(response=_make_empty_response())
        planner = LLMWeeklyPlanner(client=client)
        ctx = PlanningContext(
            goals=[],
            tasks=[],
            calendar=[],
            signals=PlanningSignals(overdue_tasks=["Old task"]),
        )
        planner.plan(ctx)
        assert client.last_prompt is not None
        assert "Old task" in client.last_prompt

    def test_prompt_with_empty_context(self) -> None:
        client = MockLLMClient(response=_make_empty_response())
        planner = LLMWeeklyPlanner(client=client)
        ctx = PlanningContext(goals=[], tasks=[], calendar=[])
        planner.plan(ctx)
        assert client.last_prompt is not None
        assert "No active goals" in client.last_prompt
        assert "No open tasks" in client.last_prompt
        assert "No calendar events" in client.last_prompt


# ── Response parsing ────────────────────────────────────────────────────────


class TestResponseParsing:
    def test_valid_response(self) -> None:
        client = MockLLMClient(response=_make_valid_response())
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        plan = planner.plan(ctx)

        assert plan.week_summary == "A focused week on career development."
        assert len(plan.priorities) == 1
        assert plan.priorities[0].goal_id == "Career"
        assert plan.priorities[0].priority == Priority.HIGH
        assert len(plan.planned_tasks) == 1
        assert plan.planned_tasks[0].task_id == "Write plan"
        assert plan.planned_tasks[0].suggested_day == date(2026, 10, 5)
        assert len(plan.risks) == 1
        assert plan.risks[0].severity == RiskSeverity.MEDIUM

    def test_empty_json_object(self) -> None:
        client = MockLLMClient(response="{}")
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        with pytest.raises(ValueError, match="week_summary"):
            planner.plan(ctx)

    def test_invalid_json(self) -> None:
        client = MockLLMClient(response="not json at all")
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        with pytest.raises(ValueError, match="not valid JSON"):
            planner.plan(ctx)

    def test_json_array_instead_of_object(self) -> None:
        client = MockLLMClient(response='["not", "an", "object"]')
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        with pytest.raises(ValueError, match="JSON object"):
            planner.plan(ctx)

    def test_missing_week_summary(self) -> None:
        response = json.dumps({"priorities": [], "planned_tasks": [], "risks": []})
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        with pytest.raises(ValueError, match="week_summary"):
            planner.plan(ctx)

    def test_empty_week_summary(self) -> None:
        response = json.dumps({
            "week_summary": "   ",
            "priorities": [],
            "planned_tasks": [],
            "risks": [],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        with pytest.raises(ValueError, match="week_summary"):
            planner.plan(ctx)

    def test_priorities_not_a_list(self) -> None:
        response = json.dumps({
            "week_summary": "test",
            "priorities": "not a list",
            "planned_tasks": [],
            "risks": [],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        with pytest.raises(ValueError, match="priorities.*must be a list"):
            planner.plan(ctx)

    def test_planned_tasks_not_a_list(self) -> None:
        response = json.dumps({
            "week_summary": "test",
            "priorities": [],
            "planned_tasks": "not a list",
            "risks": [],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        with pytest.raises(ValueError, match="planned_tasks.*must be a list"):
            planner.plan(ctx)

    def test_risks_not_a_list(self) -> None:
        response = json.dumps({
            "week_summary": "test",
            "priorities": [],
            "planned_tasks": [],
            "risks": "not a list",
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        with pytest.raises(ValueError, match="risks.*must be a list"):
            planner.plan(ctx)

    def test_invalid_priority_value(self) -> None:
        response = json.dumps({
            "week_summary": "test",
            "priorities": [
                {"goal_id": "Career", "reason": "test", "priority": "urgent"}
            ],
            "planned_tasks": [],
            "risks": [],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        with pytest.raises(ValueError, match="Invalid priority"):
            planner.plan(ctx)

    def test_invalid_severity_value(self) -> None:
        response = json.dumps({
            "week_summary": "test",
            "priorities": [],
            "planned_tasks": [],
            "risks": [
                {"description": "test", "severity": "critical"}
            ],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        with pytest.raises(ValueError, match="Invalid severity"):
            planner.plan(ctx)

    def test_invalid_date_format(self) -> None:
        response = json.dumps({
            "week_summary": "test",
            "priorities": [],
            "planned_tasks": [
                {
                    "task_id": "Write plan",
                    "goal_id": "Career",
                    "priority": "high",
                    "reason": "test",
                    "suggested_day": "10/05/2026",
                }
            ],
            "risks": [],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        with pytest.raises(ValueError, match="Invalid suggested_day"):
            planner.plan(ctx)

    def test_missing_task_id(self) -> None:
        response = json.dumps({
            "week_summary": "test",
            "priorities": [],
            "planned_tasks": [
                {
                    "goal_id": "Career",
                    "priority": "high",
                    "reason": "test",
                    "suggested_day": "2026-10-05",
                }
            ],
            "risks": [],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        with pytest.raises(ValueError, match="task_id"):
            planner.plan(ctx)

    def test_missing_goal_id_in_priority(self) -> None:
        response = json.dumps({
            "week_summary": "test",
            "priorities": [
                {"reason": "test", "priority": "high"}
            ],
            "planned_tasks": [],
            "risks": [],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        with pytest.raises(ValueError, match="goal_id"):
            planner.plan(ctx)


# ── Validation ──────────────────────────────────────────────────────────────


class TestValidation:
    def test_unknown_goal_in_priorities(self) -> None:
        response = json.dumps({
            "week_summary": "test",
            "priorities": [
                {"goal_id": "UnknownGoal", "reason": "test", "priority": "high"}
            ],
            "planned_tasks": [],
            "risks": [],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        with pytest.raises(ValueError, match="unknown goal"):
            planner.plan(ctx)

    def test_unknown_task_in_planned_tasks(self) -> None:
        response = json.dumps({
            "week_summary": "test",
            "priorities": [],
            "planned_tasks": [
                {
                    "task_id": "UnknownTask",
                    "goal_id": "Career",
                    "priority": "high",
                    "reason": "test",
                    "suggested_day": "2026-10-05",
                }
            ],
            "risks": [],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        with pytest.raises(ValueError, match="unknown task"):
            planner.plan(ctx)

    def test_unknown_goal_in_planned_tasks(self) -> None:
        response = json.dumps({
            "week_summary": "test",
            "priorities": [],
            "planned_tasks": [
                {
                    "task_id": "Write plan",
                    "goal_id": "UnknownGoal",
                    "priority": "high",
                    "reason": "test",
                    "suggested_day": "2026-10-05",
                }
            ],
            "risks": [],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        with pytest.raises(ValueError, match="unknown goal"):
            planner.plan(ctx)

    def test_duplicate_task_scheduling(self) -> None:
        response = json.dumps({
            "week_summary": "test",
            "priorities": [],
            "planned_tasks": [
                {
                    "task_id": "Write plan",
                    "goal_id": "Career",
                    "priority": "high",
                    "reason": "test",
                    "suggested_day": "2026-10-05",
                },
                {
                    "task_id": "Write plan",
                    "goal_id": "Career",
                    "priority": "medium",
                    "reason": "test",
                    "suggested_day": "2026-10-06",
                },
            ],
            "risks": [],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        with pytest.raises(ValueError, match="multiple days"):
            planner.plan(ctx)


# ── Retry logic ─────────────────────────────────────────────────────────────


class TestRetryLogic:
    def test_success_on_first_attempt(self) -> None:
        client = MockLLMClient(response=_make_valid_response())
        planner = LLMWeeklyPlanner(client=client, max_retries=2)
        ctx = _make_context()
        plan = planner.plan(ctx)
        assert isinstance(plan, WeeklyPlan)
        assert client.call_count == 1

    def test_retry_on_failure_then_success(self) -> None:
        """First call fails, second succeeds."""
        client = MockLLMClient(exception=RuntimeError("transient"))
        planner = LLMWeeklyPlanner(client=client, max_retries=2)

        # Make first call fail, second succeed
        original_generate = client.generate
        call_count = 0

        def flaky_generate(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient error")
            return _make_valid_response()

        client.generate = flaky_generate  # type: ignore[method-assign]

        ctx = _make_context()
        plan = planner.plan(ctx)
        assert isinstance(plan, WeeklyPlan)
        assert call_count == 2

    def test_all_retries_exhausted_raises(self) -> None:
        client = FailingLLMClient(RuntimeError("persistent error"))
        planner = LLMWeeklyPlanner(client=client, max_retries=2)
        ctx = _make_context()
        with pytest.raises(RuntimeError, match="failed after 3 attempts"):
            planner.plan(ctx)
        assert client.call_count == 3

    def test_no_retries_configured(self) -> None:
        client = FailingLLMClient(RuntimeError("error"))
        planner = LLMWeeklyPlanner(client=client, max_retries=0)
        ctx = _make_context()
        with pytest.raises(RuntimeError, match="failed after 1 attempts"):
            planner.plan(ctx)
        assert client.call_count == 1


# ── Fallback handling ───────────────────────────────────────────────────────


class TestFallback:
    def test_fallback_used_when_all_retries_fail(self) -> None:
        failing_client = FailingLLMClient(RuntimeError("LLM down"))
        fallback_planner = StaticPlanner(
            WeeklyPlan(week_summary="fallback plan")
        )

        planner = LLMWeeklyPlanner(
            client=failing_client,
            max_retries=1,
            fallback=fallback_planner,
        )
        ctx = _make_context()
        plan = planner.plan(ctx)
        assert isinstance(plan, WeeklyPlan)
        assert plan.week_summary == "fallback plan"
        assert failing_client.call_count == 2  # 1 initial + 1 retry

    def test_no_fallback_raises_after_retries(self) -> None:
        failing_client = FailingLLMClient(RuntimeError("LLM down"))
        planner = LLMWeeklyPlanner(
            client=failing_client,
            max_retries=1,
            fallback=None,
        )
        ctx = _make_context()
        with pytest.raises(RuntimeError, match="failed after 2 attempts"):
            planner.plan(ctx)


# ── Edge cases ──────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_goals_tasks_calendar(self) -> None:
        response = json.dumps({
            "week_summary": "A quiet week.",
            "priorities": [],
            "planned_tasks": [],
            "risks": [],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        ctx = PlanningContext(goals=[], tasks=[], calendar=[])
        plan = planner.plan(ctx)
        assert plan.week_summary == "A quiet week."
        assert plan.priorities == []
        assert plan.planned_tasks == []
        assert plan.risks == []

    def test_multiple_goals_and_tasks(self) -> None:
        response = json.dumps({
            "week_summary": "Busy week.",
            "priorities": [
                {"goal_id": "Career", "reason": "deadline", "priority": "high"},
                {"goal_id": "Health", "reason": "maintenance", "priority": "medium"},
            ],
            "planned_tasks": [
                {
                    "task_id": "Write plan",
                    "goal_id": "Career",
                    "priority": "high",
                    "reason": "overdue",
                    "suggested_day": "2026-10-05",
                },
                {
                    "task_id": "Review code",
                    "goal_id": "Career",
                    "priority": "medium",
                    "reason": "important",
                    "suggested_day": "2026-10-06",
                },
            ],
            "risks": [
                {"description": "Too many tasks", "severity": "low"},
            ],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        ctx = PlanningContext(
            goals=[Goal(title="Career"), Goal(title="Health")],
            tasks=[Task(title="Write plan"), Task(title="Review code")],
            calendar=[],
        )
        plan = planner.plan(ctx)
        assert len(plan.priorities) == 2
        assert len(plan.planned_tasks) == 2
        assert len(plan.risks) == 1

    def test_case_insensitive_priority(self) -> None:
        response = json.dumps({
            "week_summary": "test",
            "priorities": [
                {"goal_id": "Career", "reason": "test", "priority": "HIGH"}
            ],
            "planned_tasks": [],
            "risks": [],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        plan = planner.plan(ctx)
        assert plan.priorities[0].priority == Priority.HIGH

    def test_case_insensitive_severity(self) -> None:
        response = json.dumps({
            "week_summary": "test",
            "priorities": [],
            "planned_tasks": [],
            "risks": [
                {"description": "test", "severity": "MEDIUM"}
            ],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        ctx = _make_context()
        plan = planner.plan(ctx)
        assert plan.risks[0].severity == RiskSeverity.MEDIUM
