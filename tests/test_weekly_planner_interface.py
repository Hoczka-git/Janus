"""Tests for the WeeklyPlanner interface and domain models."""

from __future__ import annotations

from datetime import date

import pytest

from janus.models.event import Event
from janus.models.goal import Goal
from janus.models.task import Task
from janus.planner import (
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


# ── Priority / RiskSeverity enums ───────────────────────────────────────────


class TestPriority:
    def test_values(self) -> None:
        assert Priority.HIGH == "high"
        assert Priority.MEDIUM == "medium"
        assert Priority.LOW == "low"

    def test_membership(self) -> None:
        assert len(Priority) == 3


class TestRiskSeverity:
    def test_values(self) -> None:
        assert RiskSeverity.LOW == "low"
        assert RiskSeverity.MEDIUM == "medium"
        assert RiskSeverity.HIGH == "high"

    def test_membership(self) -> None:
        assert len(RiskSeverity) == 3


# ── PlanningSignals ─────────────────────────────────────────────────────────


class TestPlanningSignals:
    def test_defaults(self) -> None:
        sig = PlanningSignals()
        assert sig.overdue_tasks == []
        assert sig.due_soon_tasks == []
        assert sig.stalled_goals == []
        assert sig.behind_target_goals == []
        assert sig.calendar_conflicts == []
        assert sig.competing_tasks == {}

    def test_with_values(self) -> None:
        sig = PlanningSignals(
            overdue_tasks=["t1"],
            due_soon_tasks=["t2"],
            stalled_goals=["g1"],
            behind_target_goals=["g2"],
            calendar_conflicts=["conflict"],
            competing_tasks={"t1": 3},
        )
        assert sig.overdue_tasks == ["t1"]
        assert sig.competing_tasks == {"t1": 3}


# ── PlanningContext ──────────────────────────────────────────────────────────


class TestPlanningContext:
    def test_minimal(self) -> None:
        ctx = PlanningContext(goals=[], tasks=[], calendar=[])
        assert ctx.goals == []
        assert ctx.tasks == []
        assert ctx.calendar == []
        assert isinstance(ctx.signals, PlanningSignals)

    def test_with_data(self) -> None:
        goal = Goal(title="Career")
        task = Task(title="Write plan")
        event = Event(title="Meeting")
        sig = PlanningSignals(overdue_tasks=["Write plan"])
        ctx = PlanningContext(
            goals=[goal],
            tasks=[task],
            calendar=[event],
            signals=sig,
        )
        assert ctx.goals == [goal]
        assert ctx.tasks == [task]
        assert ctx.calendar == [event]
        assert ctx.signals.overdue_tasks == ["Write plan"]


# ── PriorityEntry ────────────────────────────────────────────────────────────


class TestPriorityEntry:
    def test_construct(self) -> None:
        pe = PriorityEntry(
            goal_id="career",
            reason="Urgent deadline",
            priority=Priority.HIGH,
        )
        assert pe.goal_id == "career"
        assert pe.reason == "Urgent deadline"
        assert pe.priority == Priority.HIGH


# ── PlannedTask ──────────────────────────────────────────────────────────────


class TestPlannedTask:
    def test_construct(self) -> None:
        pt = PlannedTask(
            task_id="task-123",
            goal_id="career",
            priority=Priority.HIGH,
            reason="Overdue",
            suggested_day=date(2026, 10, 5),
        )
        assert pt.task_id == "task-123"
        assert pt.goal_id == "career"
        assert pt.priority == Priority.HIGH
        assert pt.reason == "Overdue"
        assert pt.suggested_day == date(2026, 10, 5)


# ── PlanningRisk ─────────────────────────────────────────────────────────────


class TestPlanningRisk:
    def test_construct(self) -> None:
        pr = PlanningRisk(
            description="Career goal has no completed actions",
            severity=RiskSeverity.MEDIUM,
        )
        assert pr.description == "Career goal has no completed actions"
        assert pr.severity == RiskSeverity.MEDIUM


# ── WeeklyPlan ───────────────────────────────────────────────────────────────


class TestWeeklyPlan:
    def test_minimal(self) -> None:
        plan = WeeklyPlan(week_summary="A focused week")
        assert plan.week_summary == "A focused week"
        assert plan.priorities == []
        assert plan.planned_tasks == []
        assert plan.risks == []

    def test_full(self) -> None:
        plan = WeeklyPlan(
            week_summary="Test week",
            priorities=[
                PriorityEntry(goal_id="g1", reason="test", priority=Priority.HIGH)
            ],
            planned_tasks=[
                PlannedTask(
                    task_id="t1",
                    goal_id="g1",
                    priority=Priority.HIGH,
                    reason="test",
                    suggested_day=date(2026, 10, 5),
                )
            ],
            risks=[
                PlanningRisk(description="test", severity=RiskSeverity.LOW)
            ],
        )
        assert len(plan.priorities) == 1
        assert len(plan.planned_tasks) == 1
        assert len(plan.risks) == 1


# ── WeeklyPlanner protocol ───────────────────────────────────────────────────


class TestWeeklyPlannerProtocol:
    def test_is_protocol(self) -> None:
        assert hasattr(WeeklyPlanner, "_is_protocol")
        assert getattr(WeeklyPlanner, "_is_protocol") is True

    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            WeeklyPlanner()  # type: ignore[abstract]

    def test_concrete_implementation(self) -> None:
        """A concrete class implementing the protocol can be instantiated."""

        class MockPlanner:
            def plan(self, context: PlanningContext) -> WeeklyPlan:
                return WeeklyPlan(week_summary="mock")

        planner: WeeklyPlanner = MockPlanner()  # type: ignore[assignment]
        ctx = PlanningContext(goals=[], tasks=[], calendar=[])
        plan = planner.plan(ctx)
        assert isinstance(plan, WeeklyPlan)
        assert plan.week_summary == "mock"
