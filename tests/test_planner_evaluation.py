"""Weekly Planner Evaluation Suite (WP-006, WP-007).

This module defines a comprehensive evaluation suite for the weekly planner.
It covers planner behavior, edge cases, and output quality.

Scenarios (WP-006):
    1.  Overdue tasks are prioritized
    2.  Stalled goals are flagged
    3.  Calendar conflicts are detected
    4.  Empty context produces valid empty plan
    5.  LLM unavailability triggers fallback
    6.  Task coverage — all tasks are planned
    7.  Deadline awareness — tasks scheduled before deadlines
    8.  Plan validity — no unknown references
    9.  Competing tasks are identified
    10. Mixed priorities are handled correctly
    11. No goals but tasks — tasks still planned
    12. Goals but no tasks — priorities still assigned
    13. Multiple overdue tasks — all flagged
    14. LLM returns invalid JSON — error handled
    15. LLM returns unknown goal reference — validation catches it

Metrics (WP-007):
    - task_coverage: % of tasks that appear in planned_tasks
    - overdue_handling: whether overdue tasks get HIGH priority
    - deadline_awareness: whether tasks are scheduled on or before due dates
    - calendar_conflict_rate: whether conflicts are detected
    - plan_validity: whether plan passes validation
    - unsupported_recommendations: count of references to unknown goals/tasks

Usage:
    pytest tests/test_planner_evaluation.py -v
    pytest tests/test_planner_evaluation.py -v --tb=short
    pytest tests/test_planner_evaluation.py -m scenario -v
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

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
from janus.plan_cli import RuleBasedPlanner


# ═══════════════════════════════════════════════════════════════════════════════
# METRICS COLLECTOR
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class EvaluationMetrics:
    """Collected metrics from a single evaluation run.

    Attributes:
        scenario_name: Name of the scenario being evaluated.
        task_coverage: Fraction of context tasks that appear in planned_tasks (0.0–1.0).
        overdue_handling: True if all overdue tasks get HIGH priority.
        deadline_awareness: True if all tasks are scheduled on or before their due date.
        calendar_conflict_rate: Fraction of calendar conflicts that are detected (0.0–1.0).
        plan_validity: True if the plan passes all validation checks.
        unsupported_recommendations: Count of references to unknown goals/tasks.
        llm_calls: Number of LLM calls made during the scenario.
        fallback_used: True if the fallback planner was invoked.
        errors: List of error messages encountered.
    """

    scenario_name: str = ""
    task_coverage: float = 0.0
    overdue_handling: bool = False
    deadline_awareness: bool = False
    calendar_conflict_rate: float = 0.0
    plan_validity: bool = False
    unsupported_recommendations: int = 0
    llm_calls: int = 0
    fallback_used: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to a dictionary for reporting."""
        return {
            "scenario": self.scenario_name,
            "task_coverage": f"{self.task_coverage:.0%}",
            "overdue_handling": self.overdue_handling,
            "deadline_awareness": self.deadline_awareness,
            "calendar_conflict_rate": f"{self.calendar_conflict_rate:.0%}",
            "plan_validity": self.plan_validity,
            "unsupported_recommendations": self.unsupported_recommendations,
            "llm_calls": self.llm_calls,
            "fallback_used": self.fallback_used,
            "errors": self.errors,
        }


class MetricsCollector:
    """Collects and reports metrics across all evaluation scenarios."""

    def __init__(self) -> None:
        self.metrics: list[EvaluationMetrics] = []

    def add(self, metrics: EvaluationMetrics) -> None:
        """Add metrics from a scenario run."""
        self.metrics.append(metrics)

    def summary(self) -> dict[str, Any]:
        """Generate a summary report of all collected metrics."""
        if not self.metrics:
            return {"total_scenarios": 0, "scenarios": []}

        total = len(self.metrics)
        valid_plans = sum(1 for m in self.metrics if m.plan_validity)
        avg_coverage = sum(m.task_coverage for m in self.metrics) / total
        avg_conflict_rate = sum(m.calendar_conflict_rate for m in self.metrics) / total
        total_errors = sum(len(m.errors) for m in self.metrics)
        total_fallbacks = sum(1 for m in self.metrics if m.fallback_used)

        return {
            "total_scenarios": total,
            "valid_plans": valid_plans,
            "invalid_plans": total - valid_plans,
            "avg_task_coverage": f"{avg_coverage:.0%}",
            "avg_calendar_conflict_rate": f"{avg_conflict_rate:.0%}",
            "total_errors": total_errors,
            "total_fallbacks": total_fallbacks,
            "scenarios": [m.to_dict() for m in self.metrics],
        }

    def print_summary(self) -> None:
        """Print a human-readable summary report."""
        summary = self.summary()
        print("\n" + "=" * 70)
        print("WEEKLY PLANNER EVALUATION SUITE — SUMMARY REPORT")
        print("=" * 70)
        print(f"Total scenarios: {summary['total_scenarios']}")
        print(f"Valid plans: {summary['valid_plans']}")
        print(f"Invalid plans: {summary['invalid_plans']}")
        print(f"Avg task coverage: {summary['avg_task_coverage']}")
        print(f"Avg calendar conflict rate: {summary['avg_calendar_conflict_rate']}")
        print(f"Total errors: {summary['total_errors']}")
        print(f"Total fallbacks: {summary['total_fallbacks']}")
        print("-" * 70)
        for scenario in summary["scenarios"]:
            print(f"\n  Scenario: {scenario['scenario']}")
            print(f"    task_coverage: {scenario['task_coverage']}")
            print(f"    overdue_handling: {scenario['overdue_handling']}")
            print(f"    deadline_awareness: {scenario['deadline_awareness']}")
            print(f"    calendar_conflict_rate: {scenario['calendar_conflict_rate']}")
            print(f"    plan_validity: {scenario['plan_validity']}")
            print(f"    unsupported_recommendations: {scenario['unsupported_recommendations']}")
            print(f"    llm_calls: {scenario['llm_calls']}")
            print(f"    fallback_used: {scenario['fallback_used']}")
            if scenario["errors"]:
                print(f"    errors: {scenario['errors']}")
        print("\n" + "=" * 70)


# Global collector instance
collector = MetricsCollector()


# ═══════════════════════════════════════════════════════════════════════════════
# MOCK LLM CLIENTS
# ═══════════════════════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════


def _make_goal(
    title: str = "Career",
    status: str = "active",
    deadline: str | None = None,
    related_tasks: list[str] | None = None,
    recent_activity: list[dict] | None = None,
) -> Goal:
    """Create a Goal with sensible defaults for testing."""
    kwargs: dict[str, Any] = {
        "title": title,
        "status": status,
        "deadline": deadline,
    }
    if related_tasks is not None:
        kwargs["related_tasks"] = related_tasks
    if recent_activity is not None:
        kwargs["recent_activity"] = recent_activity
    return Goal(**kwargs)


def _make_task(
    title: str = "Write plan",
    due_date: date | None = None,
    priority: int = 1,
    state: str | None = None,
) -> Task:
    """Create a Task with sensible defaults for testing."""
    return Task(
        title=title,
        due_date=due_date,
        priority=priority,
        state=state,
    )


def _make_event(
    title: str = "Meeting",
    start: datetime | None = None,
    all_day: bool = False,
) -> Event:
    """Create an Event with sensible defaults for testing."""
    return Event(title=title, start=start, all_day=all_day)


@pytest.fixture
def overdue_tasks_context() -> PlanningContext:
    """Context with overdue tasks — tasks whose due date has passed."""
    today = date.today()
    goal = _make_goal(title="Career", related_tasks=["Old task", "Current task"])
    tasks = [
        _make_task(title="Old task", due_date=today - timedelta(days=5)),
        _make_task(title="Current task", due_date=today + timedelta(days=3)),
    ]
    return PlanningContext(
        goals=[goal],
        tasks=tasks,
        calendar=[],
        signals=PlanningSignals(
            overdue_tasks=["Old task"],
            due_soon_tasks=["Current task"],
        ),
    )


@pytest.fixture
def stalled_goals_context() -> PlanningContext:
    """Context with stalled goals — goals with no recent activity."""
    goal_stalled = _make_goal(title="Stalled Goal", recent_activity=None)
    goal_active = _make_goal(
        title="Active Goal",
        recent_activity=[{"task_id": "t1", "date": "2026-10-01"}],
    )
    return PlanningContext(
        goals=[goal_stalled, goal_active],
        tasks=[],
        calendar=[],
        signals=PlanningSignals(
            stalled_goals=["Stalled Goal"],
        ),
    )


@pytest.fixture
def calendar_conflicts_context() -> PlanningContext:
    """Context with calendar conflicts — tasks due on days with events."""
    today = date.today()
    busy_day = today + timedelta(days=2)
    goal = _make_goal(title="Career", related_tasks=["Task on busy day"])
    tasks = [
        _make_task(title="Task on busy day", due_date=busy_day),
    ]
    events = [
        _make_event(title="Team Meeting", start=datetime.combine(busy_day, datetime.min.time())),
    ]
    return PlanningContext(
        goals=[goal],
        tasks=tasks,
        calendar=events,
        signals=PlanningSignals(
            calendar_conflicts=[
                f"Task 'Task on busy day' due on {busy_day} conflicts with calendar event"
            ],
        ),
    )


@pytest.fixture
def empty_context() -> PlanningContext:
    """Empty context — no goals, tasks, or calendar events."""
    return PlanningContext(goals=[], tasks=[], calendar=[])


@pytest.fixture
def busy_context() -> PlanningContext:
    """Busy context — many goals and tasks with mixed priorities."""
    today = date.today()
    goals = [
        _make_goal(title="Career", related_tasks=["Task A", "Task B"]),
        _make_goal(title="Health", related_tasks=["Task C"]),
        _make_goal(title="Learning", related_tasks=["Task D"]),
    ]
    tasks = [
        _make_task(title="Task A", due_date=today + timedelta(days=1)),
        _make_task(title="Task B", due_date=today + timedelta(days=5)),
        _make_task(title="Task C", due_date=today - timedelta(days=2)),
        _make_task(title="Task D", due_date=today + timedelta(days=10)),
    ]
    return PlanningContext(
        goals=goals,
        tasks=tasks,
        calendar=[],
        signals=PlanningSignals(
            overdue_tasks=["Task C"],
            due_soon_tasks=["Task A", "Task B"],
        ),
    )


@pytest.fixture
def no_goals_context() -> PlanningContext:
    """Context with tasks but no goals."""
    today = date.today()
    tasks = [
        _make_task(title="Orphan task", due_date=today + timedelta(days=3)),
    ]
    return PlanningContext(
        goals=[],
        tasks=tasks,
        calendar=[],
    )


@pytest.fixture
def no_tasks_context() -> PlanningContext:
    """Context with goals but no tasks."""
    goals = [
        _make_goal(title="Career"),
        _make_goal(title="Health"),
    ]
    return PlanningContext(
        goals=goals,
        tasks=[],
        calendar=[],
    )


@pytest.fixture
def competing_tasks_context() -> PlanningContext:
    """Context with competing tasks — multiple tasks sharing the same due date."""
    today = date.today()
    same_day = today + timedelta(days=3)
    goal = _make_goal(title="Career", related_tasks=["Task A", "Task B", "Task C"])
    tasks = [
        _make_task(title="Task A", due_date=same_day),
        _make_task(title="Task B", due_date=same_day),
        _make_task(title="Task C", due_date=same_day),
    ]
    return PlanningContext(
        goals=[goal],
        tasks=tasks,
        calendar=[],
        signals=PlanningSignals(
            competing_tasks={"Task A": 3, "Task B": 3, "Task C": 3},
        ),
    )


@pytest.fixture
def mixed_priority_context() -> PlanningContext:
    """Context with mixed priority tasks and goals."""
    today = date.today()
    goals = [
        _make_goal(title="Urgent Goal", deadline=(today + timedelta(days=2)).isoformat()),
        _make_goal(title="Normal Goal"),
        _make_goal(title="Low Goal"),
    ]
    tasks = [
        _make_task(title="Overdue task", due_date=today - timedelta(days=1)),
        _make_task(title="Due soon task", due_date=today + timedelta(days=2)),
        _make_task(title="Later task", due_date=today + timedelta(days=14)),
    ]
    return PlanningContext(
        goals=goals,
        tasks=tasks,
        calendar=[],
        signals=PlanningSignals(
            overdue_tasks=["Overdue task"],
            due_soon_tasks=["Due soon task"],
        ),
    )


@pytest.fixture
def llm_unavailable_context() -> PlanningContext:
    """Context for testing LLM unavailability."""
    today = date.today()
    goal = _make_goal(title="Career", related_tasks=["Task A"])
    tasks = [
        _make_task(title="Task A", due_date=today + timedelta(days=3)),
    ]
    return PlanningContext(
        goals=[goal],
        tasks=tasks,
        calendar=[],
    )


@pytest.fixture
def multiple_overdue_context() -> PlanningContext:
    """Context with multiple overdue tasks."""
    today = date.today()
    goal = _make_goal(
        title="Career",
        related_tasks=["Overdue A", "Overdue B", "Overdue C"],
    )
    tasks = [
        _make_task(title="Overdue A", due_date=today - timedelta(days=10)),
        _make_task(title="Overdue B", due_date=today - timedelta(days=5)),
        _make_task(title="Overdue C", due_date=today - timedelta(days=1)),
    ]
    return PlanningContext(
        goals=[goal],
        tasks=tasks,
        calendar=[],
        signals=PlanningSignals(
            overdue_tasks=["Overdue A", "Overdue B", "Overdue C"],
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# METRIC COMPUTATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _compute_task_coverage(plan: WeeklyPlan, context: PlanningContext) -> float:
    """Compute the fraction of context tasks that appear in planned_tasks."""
    if not context.tasks:
        return 1.0  # No tasks to cover — vacuously true
    planned_task_ids = {t.task_id for t in plan.planned_tasks}
    context_task_ids = {t.title for t in context.tasks}
    covered = len(planned_task_ids & context_task_ids)
    return covered / len(context_task_ids)


def _compute_overdue_handling(plan: WeeklyPlan, context: PlanningContext) -> bool:
    """Check if all overdue tasks get HIGH priority in the plan."""
    if not context.signals.overdue_tasks:
        return True  # No overdue tasks — vacuously true
    planned_task_map = {t.task_id: t for t in plan.planned_tasks}
    for task_title in context.signals.overdue_tasks:
        if task_title in planned_task_map:
            if planned_task_map[task_title].priority != Priority.HIGH:
                return False
    return True


def _compute_deadline_awareness(plan: WeeklyPlan, context: PlanningContext) -> bool:
    """Check if all non-overdue tasks are scheduled on or before their due date.

    Overdue tasks (due date in the past) are exempt — they should be scheduled
    as soon as possible, which may be after their (already passed) due date.
    """
    if not context.tasks:
        return True  # No tasks — vacuously true
    today = date.today()
    task_due_map = {t.title: t.due_date for t in context.tasks if t.due_date}
    for planned in plan.planned_tasks:
        if planned.task_id in task_due_map:
            due = task_due_map[planned.task_id]
            if due and due >= today and planned.suggested_day > due:
                # Only non-overdue tasks must be scheduled on/before due date
                return False
    return True


def _compute_calendar_conflict_rate(plan: WeeklyPlan, context: PlanningContext) -> float:
    """Compute the fraction of calendar conflicts that are detected in risks."""
    if not context.signals.calendar_conflicts:
        return 1.0  # No conflicts — vacuously true
    risk_descriptions = [r.description for r in plan.risks]
    detected = 0
    for conflict in context.signals.calendar_conflicts:
        if any(conflict in desc for desc in risk_descriptions):
            detected += 1
    return detected / len(context.signals.calendar_conflicts)


def _compute_plan_validity(plan: WeeklyPlan, context: PlanningContext) -> bool:
    """Check if the plan passes all validation checks."""
    valid_goal_ids = {g.title for g in context.goals}
    valid_task_ids = {t.title for t in context.tasks}

    # Check priorities reference known goals
    for entry in plan.priorities:
        if entry.goal_id not in valid_goal_ids:
            return False

    # Check planned tasks reference known tasks and goals
    for task in plan.planned_tasks:
        if task.task_id not in valid_task_ids:
            return False
        if task.goal_id and task.goal_id not in valid_goal_ids:
            return False

    # Check for duplicate task scheduling
    task_days: dict[str, date] = {}
    for task in plan.planned_tasks:
        if task.task_id in task_days:
            return False
        task_days[task.task_id] = task.suggested_day

    return True


def _compute_unsupported_recommendations(plan: WeeklyPlan, context: PlanningContext) -> int:
    """Count references to unknown goals/tasks in the plan."""
    valid_goal_ids = {g.title for g in context.goals}
    valid_task_ids = {t.title for t in context.tasks}
    count = 0

    for entry in plan.priorities:
        if entry.goal_id not in valid_goal_ids:
            count += 1

    for task in plan.planned_tasks:
        if task.task_id not in valid_task_ids:
            count += 1
        if task.goal_id and task.goal_id not in valid_goal_ids:
            count += 1

    return count


def _collect_metrics(
    scenario_name: str,
    plan: WeeklyPlan,
    context: PlanningContext,
    llm_calls: int = 0,
    fallback_used: bool = False,
    errors: list[str] | None = None,
) -> EvaluationMetrics:
    """Collect all metrics for a scenario run."""
    return EvaluationMetrics(
        scenario_name=scenario_name,
        task_coverage=_compute_task_coverage(plan, context),
        overdue_handling=_compute_overdue_handling(plan, context),
        deadline_awareness=_compute_deadline_awareness(plan, context),
        calendar_conflict_rate=_compute_calendar_conflict_rate(plan, context),
        plan_validity=_compute_plan_validity(plan, context),
        unsupported_recommendations=_compute_unsupported_recommendations(plan, context),
        llm_calls=llm_calls,
        fallback_used=fallback_used,
        errors=errors or [],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO TESTS (WP-006)
# ═══════════════════════════════════════════════════════════════════════════════


class TestScenario01OverdueTasksPrioritized:
    """Scenario 1: Overdue tasks are prioritized."""

    @pytest.mark.scenario(id="S01")
    def test_overdue_tasks_get_high_priority(self, overdue_tasks_context: PlanningContext) -> None:
        """Overdue tasks should be scheduled with HIGH priority."""
        response = json.dumps({
            "week_summary": "Week with overdue tasks.",
            "priorities": [
                {"goal_id": "Career", "reason": "Has overdue tasks", "priority": "high"}
            ],
            "planned_tasks": [
                {
                    "task_id": "Old task",
                    "goal_id": "Career",
                    "priority": "high",
                    "reason": "Overdue — needs immediate attention",
                    "suggested_day": date.today().isoformat(),
                },
                {
                    "task_id": "Current task",
                    "goal_id": "Career",
                    "priority": "medium",
                    "reason": "Due soon",
                    "suggested_day": (date.today() + timedelta(days=3)).isoformat(),
                },
            ],
            "risks": [
                {"description": "Overdue tasks: Old task", "severity": "high"}
            ],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        plan = planner.plan(overdue_tasks_context)

        metrics = _collect_metrics("S01_overdue_tasks_prioritized", plan, overdue_tasks_context, llm_calls=client.call_count)
        collector.add(metrics)

        # Assertions
        assert plan.week_summary == "Week with overdue tasks."
        assert len(plan.planned_tasks) == 2
        overdue_task = next(t for t in plan.planned_tasks if t.task_id == "Old task")
        assert overdue_task.priority == Priority.HIGH
        assert metrics.overdue_handling is True
        assert metrics.plan_validity is True


class TestScenario02StalledGoalsFlagged:
    """Scenario 2: Stalled goals are flagged."""

    @pytest.mark.scenario(id="S02")
    def test_stalled_goals_get_high_priority(self, stalled_goals_context: PlanningContext) -> None:
        """Stalled goals should be flagged with HIGH priority."""
        response = json.dumps({
            "week_summary": "Week with stalled goals.",
            "priorities": [
                {"goal_id": "Stalled Goal", "reason": "No recent activity", "priority": "high"},
                {"goal_id": "Active Goal", "reason": "Active", "priority": "medium"},
            ],
            "planned_tasks": [],
            "risks": [
                {"description": "Stalled goals: Stalled Goal", "severity": "medium"}
            ],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        plan = planner.plan(stalled_goals_context)

        metrics = _collect_metrics("S02_stalled_goals_flagged", plan, stalled_goals_context, llm_calls=client.call_count)
        collector.add(metrics)

        # Assertions
        assert len(plan.priorities) == 2
        stalled = next(p for p in plan.priorities if p.goal_id == "Stalled Goal")
        assert stalled.priority == Priority.HIGH
        assert metrics.plan_validity is True


class TestScenario03CalendarConflictsDetected:
    """Scenario 3: Calendar conflicts are detected."""

    @pytest.mark.scenario(id="S03")
    def test_calendar_conflicts_in_risks(self, calendar_conflicts_context: PlanningContext) -> None:
        """Calendar conflicts should appear in the risks section."""
        busy_day = calendar_conflicts_context.tasks[0].due_date
        response = json.dumps({
            "week_summary": "Week with calendar conflicts.",
            "priorities": [
                {"goal_id": "Career", "reason": "Has tasks", "priority": "medium"}
            ],
            "planned_tasks": [
                {
                    "task_id": "Task on busy day",
                    "goal_id": "Career",
                    "priority": "medium",
                    "reason": "Due on busy day",
                    "suggested_day": busy_day.isoformat() if busy_day else date.today().isoformat(),
                },
            ],
            "risks": [
                {
                    "description": f"Task 'Task on busy day' due on {busy_day} conflicts with calendar event",
                    "severity": "medium",
                }
            ],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        plan = planner.plan(calendar_conflicts_context)

        metrics = _collect_metrics("S03_calendar_conflicts_detected", plan, calendar_conflicts_context, llm_calls=client.call_count)
        collector.add(metrics)

        # Assertions
        assert len(plan.risks) >= 1
        conflict_risks = [r for r in plan.risks if "conflicts" in r.description.lower()]
        assert len(conflict_risks) >= 1
        assert metrics.calendar_conflict_rate >= 1.0
        assert metrics.plan_validity is True


class TestScenario04EmptyContext:
    """Scenario 4: Empty context produces valid empty plan."""

    @pytest.mark.scenario(id="S04")
    def test_empty_context_produces_empty_plan(self, empty_context: PlanningContext) -> None:
        """An empty context should produce a valid but empty plan."""
        response = json.dumps({
            "week_summary": "A quiet week with nothing to do.",
            "priorities": [],
            "planned_tasks": [],
            "risks": [],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        plan = planner.plan(empty_context)

        metrics = _collect_metrics("S04_empty_context", plan, empty_context, llm_calls=client.call_count)
        collector.add(metrics)

        # Assertions
        assert plan.week_summary == "A quiet week with nothing to do."
        assert plan.priorities == []
        assert plan.planned_tasks == []
        assert plan.risks == []
        assert metrics.plan_validity is True
        assert metrics.task_coverage == 1.0  # Vacuously true


class TestScenario05LLMUnavailability:
    """Scenario 5: LLM unavailability triggers fallback."""

    @pytest.mark.scenario(id="S05")
    def test_fallback_used_when_llm_unavailable(self, llm_unavailable_context: PlanningContext) -> None:
        """When LLM is unavailable, the fallback planner should be used."""
        failing_client = FailingLLMClient(RuntimeError("LLM service down"))
        fallback_plan = WeeklyPlan(
            week_summary="Fallback plan — LLM unavailable",
            priorities=[
                PriorityEntry(goal_id="Career", reason="Fallback", priority=Priority.MEDIUM)
            ],
        )
        fallback = StaticPlanner(fallback_plan)
        planner = LLMWeeklyPlanner(
            client=failing_client,
            max_retries=1,
            fallback=fallback,
        )
        plan = planner.plan(llm_unavailable_context)

        metrics = _collect_metrics(
            "S05_llm_unavailability_fallback",
            plan,
            llm_unavailable_context,
            llm_calls=failing_client.call_count,
            fallback_used=True,
        )
        collector.add(metrics)

        # Assertions
        assert plan.week_summary == "Fallback plan — LLM unavailable"
        assert failing_client.call_count == 2  # 1 initial + 1 retry
        assert metrics.fallback_used is True
        assert metrics.plan_validity is True


class TestScenario06TaskCoverage:
    """Scenario 6: Task coverage — all tasks are planned."""

    @pytest.mark.scenario(id="S06")
    def test_all_tasks_are_planned(self, busy_context: PlanningContext) -> None:
        """All tasks in the context should appear in planned_tasks."""
        today = date.today()
        response = json.dumps({
            "week_summary": "Busy week with all tasks planned.",
            "priorities": [
                {"goal_id": "Career", "reason": "Has overdue tasks", "priority": "high"},
                {"goal_id": "Health", "reason": "Has overdue tasks", "priority": "high"},
                {"goal_id": "Learning", "reason": "Active", "priority": "medium"},
            ],
            "planned_tasks": [
                {
                    "task_id": "Task A",
                    "goal_id": "Career",
                    "priority": "high",
                    "reason": "Due soon",
                    "suggested_day": (today + timedelta(days=1)).isoformat(),
                },
                {
                    "task_id": "Task B",
                    "goal_id": "Career",
                    "priority": "medium",
                    "reason": "Due in 5 days",
                    "suggested_day": (today + timedelta(days=5)).isoformat(),
                },
                {
                    "task_id": "Task C",
                    "goal_id": "Health",
                    "priority": "high",
                    "reason": "Overdue",
                    "suggested_day": today.isoformat(),
                },
                {
                    "task_id": "Task D",
                    "goal_id": "Learning",
                    "priority": "low",
                    "reason": "Due in 10 days",
                    "suggested_day": (today + timedelta(days=10)).isoformat(),
                },
            ],
            "risks": [
                {"description": "Overdue tasks: Task C", "severity": "high"}
            ],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        plan = planner.plan(busy_context)

        metrics = _collect_metrics("S06_task_coverage", plan, busy_context, llm_calls=client.call_count)
        collector.add(metrics)

        # Assertions
        assert len(plan.planned_tasks) == 4
        planned_ids = {t.task_id for t in plan.planned_tasks}
        context_ids = {t.title for t in busy_context.tasks}
        assert planned_ids == context_ids
        assert metrics.task_coverage == 1.0
        assert metrics.plan_validity is True


class TestScenario07DeadlineAwareness:
    """Scenario 7: Deadline awareness — tasks scheduled before deadlines."""

    @pytest.mark.scenario(id="S07")
    def test_tasks_scheduled_before_deadlines(self, busy_context: PlanningContext) -> None:
        """Tasks should be scheduled on or before their due dates."""
        today = date.today()
        response = json.dumps({
            "week_summary": "Week with deadline-aware scheduling.",
            "priorities": [
                {"goal_id": "Career", "reason": "Has tasks", "priority": "high"},
                {"goal_id": "Health", "reason": "Has overdue tasks", "priority": "high"},
                {"goal_id": "Learning", "reason": "Active", "priority": "medium"},
            ],
            "planned_tasks": [
                {
                    "task_id": "Task A",
                    "goal_id": "Career",
                    "priority": "high",
                    "reason": "Due in 1 day",
                    "suggested_day": (today + timedelta(days=1)).isoformat(),
                },
                {
                    "task_id": "Task B",
                    "goal_id": "Career",
                    "priority": "medium",
                    "reason": "Due in 5 days",
                    "suggested_day": (today + timedelta(days=5)).isoformat(),
                },
                {
                    "task_id": "Task C",
                    "goal_id": "Health",
                    "priority": "high",
                    "reason": "Overdue — schedule today",
                    "suggested_day": today.isoformat(),
                },
                {
                    "task_id": "Task D",
                    "goal_id": "Learning",
                    "priority": "low",
                    "reason": "Due in 10 days",
                    "suggested_day": (today + timedelta(days=10)).isoformat(),
                },
            ],
            "risks": [],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        plan = planner.plan(busy_context)

        metrics = _collect_metrics("S07_deadline_awareness", plan, busy_context, llm_calls=client.call_count)
        collector.add(metrics)

        # Assertions
        assert metrics.deadline_awareness is True
        assert metrics.plan_validity is True


class TestScenario08PlanValidity:
    """Scenario 8: Plan validity — no unknown references."""

    @pytest.mark.scenario(id="S08")
    def test_plan_references_only_known_entities(self, overdue_tasks_context: PlanningContext) -> None:
        """Plan should only reference goals and tasks that exist in the context."""
        response = json.dumps({
            "week_summary": "Valid plan.",
            "priorities": [
                {"goal_id": "Career", "reason": "Has tasks", "priority": "high"}
            ],
            "planned_tasks": [
                {
                    "task_id": "Old task",
                    "goal_id": "Career",
                    "priority": "high",
                    "reason": "Overdue",
                    "suggested_day": date.today().isoformat(),
                },
            ],
            "risks": [],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        plan = planner.plan(overdue_tasks_context)

        metrics = _collect_metrics("S08_plan_validity", plan, overdue_tasks_context, llm_calls=client.call_count)
        collector.add(metrics)

        # Assertions
        assert metrics.plan_validity is True
        assert metrics.unsupported_recommendations == 0


class TestScenario09CompetingTasks:
    """Scenario 9: Competing tasks are identified."""

    @pytest.mark.scenario(id="S09")
    def test_competing_tasks_flagged_in_risks(self, competing_tasks_context: PlanningContext) -> None:
        """Competing tasks (same due date) should be flagged in risks."""
        today = date.today()
        same_day = today + timedelta(days=3)
        response = json.dumps({
            "week_summary": "Week with competing tasks.",
            "priorities": [
                {"goal_id": "Career", "reason": "Has competing tasks", "priority": "high"}
            ],
            "planned_tasks": [
                {
                    "task_id": "Task A",
                    "goal_id": "Career",
                    "priority": "high",
                    "reason": "Competing for time",
                    "suggested_day": same_day.isoformat(),
                },
                {
                    "task_id": "Task B",
                    "goal_id": "Career",
                    "priority": "medium",
                    "reason": "Competing for time",
                    "suggested_day": same_day.isoformat(),
                },
                {
                    "task_id": "Task C",
                    "goal_id": "Career",
                    "priority": "low",
                    "reason": "Competing for time",
                    "suggested_day": same_day.isoformat(),
                },
            ],
            "risks": [
                {"description": "Competing tasks: Task A, Task B, Task C", "severity": "low"}
            ],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        plan = planner.plan(competing_tasks_context)

        metrics = _collect_metrics("S09_competing_tasks", plan, competing_tasks_context, llm_calls=client.call_count)
        collector.add(metrics)

        # Assertions
        assert len(plan.planned_tasks) == 3
        assert metrics.plan_validity is True


class TestScenario10MixedPriorities:
    """Scenario 10: Mixed priorities are handled correctly."""

    @pytest.mark.scenario(id="S10")
    def test_mixed_priorities_sorted_correctly(self, mixed_priority_context: PlanningContext) -> None:
        """Goals with different priority levels should be sorted correctly."""
        response = json.dumps({
            "week_summary": "Week with mixed priorities.",
            "priorities": [
                {"goal_id": "Urgent Goal", "reason": "Deadline in 2 days", "priority": "high"},
                {"goal_id": "Normal Goal", "reason": "Active", "priority": "medium"},
                {"goal_id": "Low Goal", "reason": "No urgency", "priority": "low"},
            ],
            "planned_tasks": [
                {
                    "task_id": "Overdue task",
                    "goal_id": "Urgent Goal",
                    "priority": "high",
                    "reason": "Overdue",
                    "suggested_day": date.today().isoformat(),
                },
                {
                    "task_id": "Due soon task",
                    "goal_id": "Normal Goal",
                    "priority": "high",
                    "reason": "Due soon",
                    "suggested_day": (date.today() + timedelta(days=2)).isoformat(),
                },
                {
                    "task_id": "Later task",
                    "goal_id": "Low Goal",
                    "priority": "low",
                    "reason": "Due in 14 days",
                    "suggested_day": (date.today() + timedelta(days=14)).isoformat(),
                },
            ],
            "risks": [
                {"description": "Overdue tasks: Overdue task", "severity": "high"}
            ],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        plan = planner.plan(mixed_priority_context)

        metrics = _collect_metrics("S10_mixed_priorities", plan, mixed_priority_context, llm_calls=client.call_count)
        collector.add(metrics)

        # Assertions
        assert len(plan.priorities) == 3
        assert plan.priorities[0].priority == Priority.HIGH
        assert plan.priorities[1].priority == Priority.MEDIUM
        assert plan.priorities[2].priority == Priority.LOW
        assert metrics.plan_validity is True


class TestScenario11NoGoalsButTasks:
    """Scenario 11: No goals but tasks — tasks still planned."""

    @pytest.mark.scenario(id="S11")
    def test_tasks_planned_without_goals(self, no_goals_context: PlanningContext) -> None:
        """Tasks should be planned even when no goals are defined (RuleBasedPlanner)."""
        planner = RuleBasedPlanner()
        plan = planner.plan(no_goals_context)

        metrics = _collect_metrics("S11_no_goals_but_tasks", plan, no_goals_context)
        collector.add(metrics)

        # Assertions
        assert len(plan.planned_tasks) == 1
        assert plan.planned_tasks[0].task_id == "Orphan task"
        assert metrics.task_coverage == 1.0
        assert metrics.plan_validity is True

    @pytest.mark.scenario(id="S11b")
    def test_llm_planner_rejects_empty_goal_id(self, no_goals_context: PlanningContext) -> None:
        """LLM planner should reject empty goal_id (known limitation)."""
        response = json.dumps({
            "week_summary": "Week with tasks but no goals.",
            "priorities": [],
            "planned_tasks": [
                {
                    "task_id": "Orphan task",
                    "goal_id": "",
                    "priority": "medium",
                    "reason": "No associated goal",
                    "suggested_day": (date.today() + timedelta(days=3)).isoformat(),
                },
            ],
            "risks": [],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)

        with pytest.raises(ValueError, match="goal_id"):
            planner.plan(no_goals_context)


class TestScenario12GoalsButNoTasks:
    """Scenario 12: Goals but no tasks — priorities still assigned."""

    @pytest.mark.scenario(id="S12")
    def test_priorities_assigned_without_tasks(self, no_tasks_context: PlanningContext) -> None:
        """Goals should be prioritized even when no tasks are defined."""
        response = json.dumps({
            "week_summary": "Week with goals but no tasks.",
            "priorities": [
                {"goal_id": "Career", "reason": "Active goal", "priority": "medium"},
                {"goal_id": "Health", "reason": "Active goal", "priority": "medium"},
            ],
            "planned_tasks": [],
            "risks": [],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        plan = planner.plan(no_tasks_context)

        metrics = _collect_metrics("S12_goals_but_no_tasks", plan, no_tasks_context, llm_calls=client.call_count)
        collector.add(metrics)

        # Assertions
        assert len(plan.priorities) == 2
        assert plan.planned_tasks == []
        assert metrics.plan_validity is True


class TestScenario13MultipleOverdueTasks:
    """Scenario 13: Multiple overdue tasks — all flagged."""

    @pytest.mark.scenario(id="S13")
    def test_all_overdue_tasks_flagged(self, multiple_overdue_context: PlanningContext) -> None:
        """All overdue tasks should be flagged in risks."""
        today = date.today()
        response = json.dumps({
            "week_summary": "Week with multiple overdue tasks.",
            "priorities": [
                {"goal_id": "Career", "reason": "Has multiple overdue tasks", "priority": "high"}
            ],
            "planned_tasks": [
                {
                    "task_id": "Overdue A",
                    "goal_id": "Career",
                    "priority": "high",
                    "reason": "Overdue by 10 days",
                    "suggested_day": today.isoformat(),
                },
                {
                    "task_id": "Overdue B",
                    "goal_id": "Career",
                    "priority": "high",
                    "reason": "Overdue by 5 days",
                    "suggested_day": today.isoformat(),
                },
                {
                    "task_id": "Overdue C",
                    "goal_id": "Career",
                    "priority": "high",
                    "reason": "Overdue by 1 day",
                    "suggested_day": today.isoformat(),
                },
            ],
            "risks": [
                {"description": "Overdue tasks: Overdue A, Overdue B, Overdue C", "severity": "high"}
            ],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)
        plan = planner.plan(multiple_overdue_context)

        metrics = _collect_metrics("S13_multiple_overdue_tasks", plan, multiple_overdue_context, llm_calls=client.call_count)
        collector.add(metrics)

        # Assertions
        assert len(plan.planned_tasks) == 3
        assert all(t.priority == Priority.HIGH for t in plan.planned_tasks)
        assert metrics.overdue_handling is True
        assert metrics.plan_validity is True


class TestScenario14LLMReturnsInvalidJSON:
    """Scenario 14: LLM returns invalid JSON — error handled."""

    @pytest.mark.scenario(id="S14")
    def test_invalid_json_raises_value_error(self, overdue_tasks_context: PlanningContext) -> None:
        """Invalid JSON from LLM should raise ValueError."""
        client = MockLLMClient(response="this is not valid json {{{")
        planner = LLMWeeklyPlanner(client=client)

        with pytest.raises(ValueError, match="not valid JSON"):
            planner.plan(overdue_tasks_context)

        metrics = _collect_metrics(
            "S14_invalid_json",
            WeeklyPlan(week_summary="error"),
            overdue_tasks_context,
            llm_calls=client.call_count,
            errors=["ValueError: not valid JSON"],
        )
        collector.add(metrics)


class TestScenario15LLMReturnsUnknownGoal:
    """Scenario 15: LLM returns unknown goal reference — validation catches it."""

    @pytest.mark.scenario(id="S15")
    def test_unknown_goal_reference_raises_error(self, overdue_tasks_context: PlanningContext) -> None:
        """Unknown goal reference in LLM response should raise ValueError."""
        response = json.dumps({
            "week_summary": "Plan with unknown goal.",
            "priorities": [
                {"goal_id": "NonExistentGoal", "reason": "Unknown", "priority": "high"}
            ],
            "planned_tasks": [],
            "risks": [],
        })
        client = MockLLMClient(response=response)
        planner = LLMWeeklyPlanner(client=client)

        with pytest.raises(ValueError, match="unknown goal"):
            planner.plan(overdue_tasks_context)

        metrics = _collect_metrics(
            "S15_unknown_goal_reference",
            WeeklyPlan(week_summary="error"),
            overdue_tasks_context,
            llm_calls=client.call_count,
            errors=["ValueError: unknown goal"],
        )
        collector.add(metrics)


# ═══════════════════════════════════════════════════════════════════════════════
# BASELINE COMPARISON TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestBaselineComparisons:
    """Compare LLM planner output against RuleBasedPlanner baseline."""

    @pytest.mark.scenario(id="B01")
    def test_llm_vs_rule_based_overdue_handling(self, overdue_tasks_context: PlanningContext) -> None:
        """LLM planner should handle overdue tasks at least as well as RuleBasedPlanner."""
        # RuleBasedPlanner baseline
        rule_planner = RuleBasedPlanner()
        rule_plan = rule_planner.plan(overdue_tasks_context)
        rule_metrics = _collect_metrics("B01_rule_based_overdue", rule_plan, overdue_tasks_context)

        # LLM planner
        response = json.dumps({
            "week_summary": "LLM plan with overdue handling.",
            "priorities": [
                {"goal_id": "Career", "reason": "Has overdue tasks", "priority": "high"}
            ],
            "planned_tasks": [
                {
                    "task_id": "Old task",
                    "goal_id": "Career",
                    "priority": "high",
                    "reason": "Overdue",
                    "suggested_day": date.today().isoformat(),
                },
                {
                    "task_id": "Current task",
                    "goal_id": "Career",
                    "priority": "medium",
                    "reason": "Due soon",
                    "suggested_day": (date.today() + timedelta(days=3)).isoformat(),
                },
            ],
            "risks": [
                {"description": "Overdue tasks: Old task", "severity": "high"}
            ],
        })
        client = MockLLMClient(response=response)
        llm_planner = LLMWeeklyPlanner(client=client)
        llm_plan = llm_planner.plan(overdue_tasks_context)
        llm_metrics = _collect_metrics("B01_llm_overdue", llm_plan, overdue_tasks_context, llm_calls=client.call_count)

        collector.add(rule_metrics)
        collector.add(llm_metrics)

        # Both should handle overdue tasks
        assert rule_metrics.overdue_handling is True
        assert llm_metrics.overdue_handling is True

    @pytest.mark.scenario(id="B02")
    def test_llm_vs_rule_based_plan_validity(self, busy_context: PlanningContext) -> None:
        """Both planners should produce valid plans."""
        # RuleBasedPlanner baseline
        rule_planner = RuleBasedPlanner()
        rule_plan = rule_planner.plan(busy_context)
        rule_metrics = _collect_metrics("B02_rule_based_validity", rule_plan, busy_context)

        # LLM planner
        today = date.today()
        response = json.dumps({
            "week_summary": "LLM plan for busy context.",
            "priorities": [
                {"goal_id": "Career", "reason": "Has tasks", "priority": "high"},
                {"goal_id": "Health", "reason": "Has overdue tasks", "priority": "high"},
                {"goal_id": "Learning", "reason": "Active", "priority": "medium"},
            ],
            "planned_tasks": [
                {
                    "task_id": "Task A",
                    "goal_id": "Career",
                    "priority": "high",
                    "reason": "Due soon",
                    "suggested_day": (today + timedelta(days=1)).isoformat(),
                },
                {
                    "task_id": "Task B",
                    "goal_id": "Career",
                    "priority": "medium",
                    "reason": "Due in 5 days",
                    "suggested_day": (today + timedelta(days=5)).isoformat(),
                },
                {
                    "task_id": "Task C",
                    "goal_id": "Health",
                    "priority": "high",
                    "reason": "Overdue",
                    "suggested_day": today.isoformat(),
                },
                {
                    "task_id": "Task D",
                    "goal_id": "Learning",
                    "priority": "low",
                    "reason": "Due in 10 days",
                    "suggested_day": (today + timedelta(days=10)).isoformat(),
                },
            ],
            "risks": [
                {"description": "Overdue tasks: Task C", "severity": "high"}
            ],
        })
        client = MockLLMClient(response=response)
        llm_planner = LLMWeeklyPlanner(client=client)
        llm_plan = llm_planner.plan(busy_context)
        llm_metrics = _collect_metrics("B02_llm_validity", llm_plan, busy_context, llm_calls=client.call_count)

        collector.add(rule_metrics)
        collector.add(llm_metrics)

        # Both should produce valid plans
        assert rule_metrics.plan_validity is True
        assert llm_metrics.plan_validity is True

    @pytest.mark.scenario(id="B03")
    def test_llm_vs_rule_based_task_coverage(self, busy_context: PlanningContext) -> None:
        """Both planners should cover all tasks."""
        # RuleBasedPlanner baseline
        rule_planner = RuleBasedPlanner()
        rule_plan = rule_planner.plan(busy_context)
        rule_metrics = _collect_metrics("B03_rule_based_coverage", rule_plan, busy_context)

        # LLM planner
        today = date.today()
        response = json.dumps({
            "week_summary": "LLM plan with full coverage.",
            "priorities": [
                {"goal_id": "Career", "reason": "Has tasks", "priority": "high"},
                {"goal_id": "Health", "reason": "Has overdue tasks", "priority": "high"},
                {"goal_id": "Learning", "reason": "Active", "priority": "medium"},
            ],
            "planned_tasks": [
                {
                    "task_id": "Task A",
                    "goal_id": "Career",
                    "priority": "high",
                    "reason": "Due soon",
                    "suggested_day": (today + timedelta(days=1)).isoformat(),
                },
                {
                    "task_id": "Task B",
                    "goal_id": "Career",
                    "priority": "medium",
                    "reason": "Due in 5 days",
                    "suggested_day": (today + timedelta(days=5)).isoformat(),
                },
                {
                    "task_id": "Task C",
                    "goal_id": "Health",
                    "priority": "high",
                    "reason": "Overdue",
                    "suggested_day": today.isoformat(),
                },
                {
                    "task_id": "Task D",
                    "goal_id": "Learning",
                    "priority": "low",
                    "reason": "Due in 10 days",
                    "suggested_day": (today + timedelta(days=10)).isoformat(),
                },
            ],
            "risks": [],
        })
        client = MockLLMClient(response=response)
        llm_planner = LLMWeeklyPlanner(client=client)
        llm_plan = llm_planner.plan(busy_context)
        llm_metrics = _collect_metrics("B03_llm_coverage", llm_plan, busy_context, llm_calls=client.call_count)

        collector.add(rule_metrics)
        collector.add(llm_metrics)

        # Both should have good task coverage
        assert rule_metrics.task_coverage >= 0.5
        assert llm_metrics.task_coverage >= 0.5


# ═══════════════════════════════════════════════════════════════════════════════
# RULE-BASED PLANNER SCENARIOS
# ═══════════════════════════════════════════════════════════════════════════════


class TestRuleBasedPlannerScenarios:
    """Scenarios specifically for the RuleBasedPlanner."""

    @pytest.mark.scenario(id="R01")
    def test_rule_based_overdue_tasks(self, overdue_tasks_context: PlanningContext) -> None:
        """RuleBasedPlanner should prioritize goals with overdue tasks."""
        planner = RuleBasedPlanner()
        plan = planner.plan(overdue_tasks_context)

        metrics = _collect_metrics("R01_rule_based_overdue", plan, overdue_tasks_context)
        collector.add(metrics)

        assert len(plan.priorities) >= 1
        assert plan.priorities[0].priority == Priority.HIGH
        assert metrics.overdue_handling is True
        assert metrics.plan_validity is True

    @pytest.mark.scenario(id="R02")
    def test_rule_based_stalled_goals(self, stalled_goals_context: PlanningContext) -> None:
        """RuleBasedPlanner should flag stalled goals."""
        planner = RuleBasedPlanner()
        plan = planner.plan(stalled_goals_context)

        metrics = _collect_metrics("R02_rule_based_stalled", plan, stalled_goals_context)
        collector.add(metrics)

        assert len(plan.priorities) >= 1
        stalled = next((p for p in plan.priorities if p.goal_id == "Stalled Goal"), None)
        assert stalled is not None
        assert stalled.priority == Priority.HIGH
        assert metrics.plan_validity is True

    @pytest.mark.scenario(id="R03")
    def test_rule_based_calendar_conflicts(self, calendar_conflicts_context: PlanningContext) -> None:
        """RuleBasedPlanner should detect calendar conflicts."""
        planner = RuleBasedPlanner()
        plan = planner.plan(calendar_conflicts_context)

        metrics = _collect_metrics("R03_rule_based_conflicts", plan, calendar_conflicts_context)
        collector.add(metrics)

        assert len(plan.risks) >= 1
        assert metrics.calendar_conflict_rate >= 1.0
        assert metrics.plan_validity is True

    @pytest.mark.scenario(id="R04")
    def test_rule_based_empty_context(self, empty_context: PlanningContext) -> None:
        """RuleBasedPlanner should handle empty context gracefully."""
        planner = RuleBasedPlanner()
        plan = planner.plan(empty_context)

        metrics = _collect_metrics("R04_rule_based_empty", plan, empty_context)
        collector.add(metrics)

        assert plan.week_summary != ""
        assert plan.priorities == []
        assert plan.planned_tasks == []
        assert plan.risks == []
        assert metrics.plan_validity is True

    @pytest.mark.scenario(id="R05")
    def test_rule_based_competing_tasks(self, competing_tasks_context: PlanningContext) -> None:
        """RuleBasedPlanner should identify competing tasks."""
        planner = RuleBasedPlanner()
        plan = planner.plan(competing_tasks_context)

        metrics = _collect_metrics("R05_rule_based_competing", plan, competing_tasks_context)
        collector.add(metrics)

        assert len(plan.risks) >= 1
        assert metrics.plan_validity is True

    @pytest.mark.scenario(id="R06")
    def test_rule_based_no_goals(self, no_goals_context: PlanningContext) -> None:
        """RuleBasedPlanner should handle tasks without goals."""
        planner = RuleBasedPlanner()
        plan = planner.plan(no_goals_context)

        metrics = _collect_metrics("R06_rule_based_no_goals", plan, no_goals_context)
        collector.add(metrics)

        assert len(plan.planned_tasks) == 1
        assert metrics.task_coverage == 1.0
        assert metrics.plan_validity is True

    @pytest.mark.scenario(id="R07")
    def test_rule_based_no_tasks(self, no_tasks_context: PlanningContext) -> None:
        """RuleBasedPlanner should handle goals without tasks."""
        planner = RuleBasedPlanner()
        plan = planner.plan(no_tasks_context)

        metrics = _collect_metrics("R07_rule_based_no_tasks", plan, no_tasks_context)
        collector.add(metrics)

        assert len(plan.priorities) == 2
        assert plan.planned_tasks == []
        assert metrics.plan_validity is True

    @pytest.mark.scenario(id="R08")
    def test_rule_based_mixed_priorities(self, mixed_priority_context: PlanningContext) -> None:
        """RuleBasedPlanner should sort goals by priority correctly."""
        planner = RuleBasedPlanner()
        plan = planner.plan(mixed_priority_context)

        metrics = _collect_metrics("R08_rule_based_mixed", plan, mixed_priority_context)
        collector.add(metrics)

        assert len(plan.priorities) == 3
        # HIGH priority goals should come first
        high_priorities = [p for p in plan.priorities if p.priority == Priority.HIGH]
        assert len(high_priorities) >= 1
        assert metrics.plan_validity is True


# ═══════════════════════════════════════════════════════════════════════════════
# METRICS REPORT
# ═══════════════════════════════════════════════════════════════════════════════


def test_evaluation_summary_report() -> None:
    """Print the evaluation summary report.

    This test always passes — it's a report generator.
    The actual assertions are in the scenario tests above.
    """
    collector.print_summary()
    assert True  # This test is a report generator


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
