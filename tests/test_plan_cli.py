"""Tests for the 'janus plan week' CLI handler."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from io import StringIO
from unittest.mock import patch

import pytest

from janus.models.event import Event
from janus.models.goal import Goal
from janus.models.task import Task
from janus.plan_cli import (
    RuleBasedPlanner,
    _build_context,
    _format_plan,
    handle_plan_week,
    print_plan_help,
)
from janus.planner.models import (
    PlannedTask,
    PlanningContext,
    PlanningRisk,
    PlanningSignals,
    Priority,
    PriorityEntry,
    RiskSeverity,
    WeeklyPlan,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_goal(
    title: str = "Career",
    status: str = "active",
    deadline: str | None = None,
    related_tasks: list[str] | None = None,
    recent_activity: list[dict] | None = None,
) -> Goal:
    kwargs: dict = {
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
    return Event(title=title, start=start, all_day=all_day)


def _make_context() -> PlanningContext:
    """Create a minimal planning context for testing."""
    goal = _make_goal(title="Career", related_tasks=["Write plan"])
    task = _make_task(title="Write plan", due_date=date.today() + timedelta(days=3))
    event = _make_event(title="Team meeting")
    return PlanningContext(
        goals=[goal],
        tasks=[task],
        calendar=[event],
    )


def _make_plan() -> WeeklyPlan:
    """Create a minimal weekly plan for testing."""
    return WeeklyPlan(
        week_summary="Test week",
        priorities=[
            PriorityEntry(
                goal_id="Career",
                reason="Has overdue tasks",
                priority=Priority.HIGH,
            ),
        ],
        planned_tasks=[
            PlannedTask(
                task_id="Write plan",
                goal_id="Career",
                priority=Priority.HIGH,
                reason="Due soon",
                suggested_day=date.today() + timedelta(days=3),
            ),
        ],
        risks=[
            PlanningRisk(
                description="Overdue tasks: Old task",
                severity=RiskSeverity.HIGH,
            ),
        ],
    )


# ── print_plan_help tests ────────────────────────────────────────────────────


class TestPrintPlanHelp:
    def test_prints_usage(self, capsys):
        print_plan_help()
        out = capsys.readouterr().out
        assert "Usage: janus plan" in out
        assert "week" in out

    def test_prints_help_option(self, capsys):
        print_plan_help()
        out = capsys.readouterr().out
        assert "-h" in out
        assert "--help" in out


# ── handle_plan_week tests ───────────────────────────────────────────────────


class TestHandlePlanWeek:
    def test_basic_invocation(self, capsys):
        with patch("janus.plan_cli._build_context") as mock_build, \
             patch("janus.plan_cli.RuleBasedPlanner") as mock_planner_class:
            mock_build.return_value = _make_context()
            mock_planner = mock_planner_class.return_value
            mock_planner.plan.return_value = _make_plan()

            handle_plan_week([])

        out = capsys.readouterr().out
        assert "JANUS WEEKLY PLAN" in out
        assert "TOP PRIORITIES" in out
        assert "Career" in out
        assert "RISKS" in out
        assert "PLANNED TASKS" in out

    def test_help_flag(self, capsys):
        handle_plan_week(["--help"])
        out = capsys.readouterr().out
        assert "Usage: janus plan week" in out

    def test_h_flag(self, capsys):
        handle_plan_week(["-h"])
        out = capsys.readouterr().out
        assert "Usage: janus plan week" in out

    def test_rejects_arguments(self, capsys):
        with pytest.raises(SystemExit):
            handle_plan_week(["extra"])
        err = capsys.readouterr().err
        assert "does not accept arguments" in err

    def test_empty_context(self, capsys):
        with patch("janus.plan_cli._build_context") as mock_build, \
             patch("janus.plan_cli.RuleBasedPlanner") as mock_planner_class:
            mock_build.return_value = PlanningContext(
                goals=[],
                tasks=[],
                calendar=[],
            )
            mock_planner = mock_planner_class.return_value
            mock_planner.plan.return_value = WeeklyPlan(
                week_summary="Empty week",
            )

            handle_plan_week([])

        out = capsys.readouterr().out
        assert "JANUS WEEKLY PLAN" in out
        assert "Empty week" in out


# ── _build_context tests ─────────────────────────────────────────────────────


class TestBuildContext:
    def test_loads_goals_and_tasks(self):
        goals = [_make_goal(title="Career"), _make_goal(title="Health")]
        tasks = [_make_task(title="Task 1"), _make_task(title="Task 2")]

        with patch("janus.integrations.markdown_goals.load_goals", return_value=goals), \
             patch("janus.integrations.markdown_tasks.load_tasks", return_value=tasks), \
             patch("janus.integrations.google_calendar.list_upcoming_events", return_value=[]):
            context = _build_context()

        assert len(context.goals) == 2
        assert len(context.tasks) == 2

    def test_filters_inactive_goals(self):
        goals = [
            _make_goal(title="Active", status="active"),
            _make_goal(title="Completed", status="completed"),
        ]

        with patch("janus.integrations.markdown_goals.load_goals", return_value=goals), \
             patch("janus.integrations.markdown_tasks.load_tasks", return_value=[]), \
             patch("janus.integrations.google_calendar.list_upcoming_events", return_value=[]):
            context = _build_context()

        assert len(context.goals) == 1
        assert context.goals[0].title == "Active"

    def test_handles_missing_data(self):
        with patch("janus.integrations.markdown_goals.load_goals", side_effect=FileNotFoundError), \
             patch("janus.integrations.markdown_tasks.load_tasks", side_effect=FileNotFoundError), \
             patch("janus.integrations.google_calendar.list_upcoming_events", side_effect=Exception):
            context = _build_context()

        assert context.goals == []
        assert context.tasks == []
        assert context.calendar == []

    def test_computes_overdue_tasks(self):
        today = date.today()
        tasks = [
            _make_task(title="Overdue", due_date=today - timedelta(days=1)),
            _make_task(title="Future", due_date=today + timedelta(days=5)),
        ]

        with patch("janus.integrations.markdown_goals.load_goals", return_value=[]), \
             patch("janus.integrations.markdown_tasks.load_tasks", return_value=tasks), \
             patch("janus.integrations.google_calendar.list_upcoming_events", return_value=[]):
            context = _build_context()

        assert "Overdue" in context.signals.overdue_tasks
        assert "Future" not in context.signals.overdue_tasks

    def test_computes_due_soon_tasks(self):
        today = date.today()
        tasks = [
            _make_task(title="Due soon", due_date=today + timedelta(days=3)),
            _make_task(title="Later", due_date=today + timedelta(days=14)),
        ]

        with patch("janus.integrations.markdown_goals.load_goals", return_value=[]), \
             patch("janus.integrations.markdown_tasks.load_tasks", return_value=tasks), \
             patch("janus.integrations.google_calendar.list_upcoming_events", return_value=[]):
            context = _build_context()

        assert "Due soon" in context.signals.due_soon_tasks
        assert "Later" not in context.signals.due_soon_tasks

    def test_detects_stalled_goals(self):
        goals = [
            _make_goal(title="Stalled", recent_activity=None),
            _make_goal(title="Active", recent_activity=[{"task_id": "t1"}]),
        ]

        with patch("janus.integrations.markdown_goals.load_goals", return_value=goals), \
             patch("janus.integrations.markdown_tasks.load_tasks", return_value=[]), \
             patch("janus.integrations.google_calendar.list_upcoming_events", return_value=[]):
            context = _build_context()

        assert "Stalled" in context.signals.stalled_goals
        assert "Active" not in context.signals.stalled_goals


# ── RuleBasedPlanner tests ───────────────────────────────────────────────────


class TestRuleBasedPlanner:
    def test_plan_returns_weekly_plan(self):
        context = _make_context()
        planner = RuleBasedPlanner()
        plan = planner.plan(context)

        assert isinstance(plan, WeeklyPlan)
        assert plan.week_summary
        assert isinstance(plan.priorities, list)
        assert isinstance(plan.planned_tasks, list)
        assert isinstance(plan.risks, list)

    def test_prioritizes_goals_with_overdue_tasks(self):
        today = date.today()
        goal = _make_goal(title="Career", related_tasks=["Overdue task"])
        task = _make_task(title="Overdue task", due_date=today - timedelta(days=1))
        context = PlanningContext(
            goals=[goal],
            tasks=[task],
            calendar=[],
            signals=PlanningSignals(
                overdue_tasks=["Overdue task"],
            ),
        )

        planner = RuleBasedPlanner()
        plan = planner.plan(context)

        assert len(plan.priorities) == 1
        assert plan.priorities[0].goal_id == "Career"
        assert plan.priorities[0].priority == Priority.HIGH

    def test_schedules_tasks_by_due_date(self):
        today = date.today()
        task = _make_task(title="Task", due_date=today + timedelta(days=2))
        context = PlanningContext(
            goals=[],
            tasks=[task],
            calendar=[],
        )

        planner = RuleBasedPlanner()
        plan = planner.plan(context)

        assert len(plan.planned_tasks) == 1
        assert plan.planned_tasks[0].task_id == "Task"
        assert plan.planned_tasks[0].suggested_day == today + timedelta(days=2)

    def test_identifies_risks(self):
        context = PlanningContext(
            goals=[],
            tasks=[],
            calendar=[],
            signals=PlanningSignals(
                overdue_tasks=["Old task"],
                stalled_goals=["Stalled goal"],
            ),
        )

        planner = RuleBasedPlanner()
        plan = planner.plan(context)

        assert len(plan.risks) >= 2
        risk_descriptions = [r.description for r in plan.risks]
        assert any("Old task" in d for d in risk_descriptions)
        assert any("Stalled goal" in d for d in risk_descriptions)

    def test_empty_context_produces_empty_plan(self):
        context = PlanningContext(
            goals=[],
            tasks=[],
            calendar=[],
        )

        planner = RuleBasedPlanner()
        plan = planner.plan(context)

        assert plan.priorities == []
        assert plan.planned_tasks == []
        assert plan.risks == []
        assert plan.week_summary


# ── _format_plan tests ───────────────────────────────────────────────────────


class TestFormatPlan:
    def test_formats_complete_plan(self):
        plan = _make_plan()
        output = _format_plan(plan)

        assert "JANUS WEEKLY PLAN" in output
        assert "Test week" in output
        assert "TOP PRIORITIES" in output
        assert "Career" in output
        assert "RISKS" in output
        assert "PLANNED TASKS" in output

    def test_formats_empty_plan(self):
        plan = WeeklyPlan(week_summary="Empty")
        output = _format_plan(plan)

        assert "JANUS WEEKLY PLAN" in output
        assert "Empty" in output
        assert "TOP PRIORITIES" not in output

    def test_groups_tasks_by_day(self):
        today = date.today()
        plan = WeeklyPlan(
            week_summary="Test",
            planned_tasks=[
                PlannedTask(
                    task_id="Task A",
                    goal_id="",
                    priority=Priority.HIGH,
                    reason="",
                    suggested_day=today,
                ),
                PlannedTask(
                    task_id="Task B",
                    goal_id="",
                    priority=Priority.MEDIUM,
                    reason="",
                    suggested_day=today,
                ),
                PlannedTask(
                    task_id="Task C",
                    goal_id="",
                    priority=Priority.LOW,
                    reason="",
                    suggested_day=today + timedelta(days=1),
                ),
            ],
        )

        output = _format_plan(plan)
        assert today.strftime("%A") in output
        assert "Task A" in output
        assert "Task B" in output
        assert "Task C" in output
