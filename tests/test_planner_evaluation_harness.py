"""Unit tests for the planner evaluation harness.

Tests the fixture loader, planner runner, assertion helpers, and scenario
runner in isolation.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from janus.models.goal import Goal
from janus.models.task import Task
from janus.planner.evaluation.assertions import AssertionHelper, AssertionResult
from janus.planner.evaluation.fixtures import (
    ExpectedOutput,
    FixtureLoader,
    InlineFixtureBuilder,
    Scenario,
)
from janus.planner.evaluation.runner import MockLLMClient, PlannerRunner, PlannerResult
from janus.planner.evaluation.scenarios import ScenarioResult, ScenarioRunner, ScenarioSuiteResult
from janus.planner.models import (
    PlannedTask,
    PlanningContext,
    PlanningSignals,
    Priority,
    PriorityEntry,
    RiskSeverity,
    WeeklyPlan,
)
from janus.planner.llm_planner import LLMWeeklyPlanner
from janus.plan_cli import RuleBasedPlanner


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURE LOADER TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestFixtureLoader:
    """Tests for the FixtureLoader class."""

    def test_load_all_from_default_dir(self) -> None:
        """Should load all scenarios from the default fixture directory."""
        loader = FixtureLoader()
        scenarios = loader.load_all()
        assert len(scenarios) == 10
        assert all(isinstance(s, Scenario) for s in scenarios)

    def test_load_by_id(self) -> None:
        """Should load a single scenario by ID."""
        loader = FixtureLoader()
        scenario = loader.load_by_id("S01")
        assert scenario.id == "S01"
        assert scenario.name == "Single urgent task"

    def test_load_by_id_not_found(self) -> None:
        """Should raise ValueError for unknown scenario ID."""
        loader = FixtureLoader()
        with pytest.raises(ValueError, match="not found"):
            loader.load_by_id("NONEXISTENT")

    def test_load_file_not_found(self) -> None:
        """Should raise FileNotFoundError for missing directory."""
        loader = FixtureLoader(fixture_dir=Path("/nonexistent/path"))
        with pytest.raises(FileNotFoundError):
            loader.load_all()

    def test_scenario_has_context(self) -> None:
        """Loaded scenarios should have a valid PlanningContext."""
        loader = FixtureLoader()
        scenarios = loader.load_all()
        for scenario in scenarios:
            assert isinstance(scenario.context, PlanningContext)
            assert isinstance(scenario.expected, ExpectedOutput)

    def test_scenario_has_expected_output(self) -> None:
        """Loaded scenarios should have expected output criteria."""
        loader = FixtureLoader()
        scenario = loader.load_by_id("S02")
        assert scenario.expected.overdue_handling is True
        assert scenario.expected.min_task_coverage == 1.0

    def test_relative_date_resolution(self) -> None:
        """Should resolve relative dates like 'today', 'today+1', 'today-5'."""
        loader = FixtureLoader()
        scenario = loader.load_by_id("S02")
        # S02 has tasks with due_date "today-10", "today-5", "today-1"
        tasks = scenario.context.tasks
        assert len(tasks) == 3
        today = date.today()
        assert tasks[0].due_date == today - timedelta(days=10)
        assert tasks[1].due_date == today - timedelta(days=5)
        assert tasks[2].due_date == today - timedelta(days=1)

    def test_scenario_s01_structure(self) -> None:
        """S01 should have 1 goal, 1 task, no calendar."""
        loader = FixtureLoader()
        scenario = loader.load_by_id("S01")
        assert len(scenario.context.goals) == 1
        assert len(scenario.context.tasks) == 1
        assert len(scenario.context.calendar) == 0
        assert scenario.context.signals.due_soon_tasks == ["Write plan"]

    def test_scenario_s07_empty_tasks(self) -> None:
        """S07 should have 1 goal, 0 tasks, 0 calendar events."""
        loader = FixtureLoader()
        scenario = loader.load_by_id("S07")
        assert len(scenario.context.goals) == 1
        assert len(scenario.context.tasks) == 0
        assert len(scenario.context.calendar) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# INLINE FIXTURE BUILDER TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestInlineFixtureBuilder:
    """Tests for the InlineFixtureBuilder class."""

    def test_make_scenario(self) -> None:
        """Should build a scenario from components."""
        scenario = InlineFixtureBuilder.make_scenario(
            scenario_id="TEST01",
            name="Test Scenario",
            description="A test scenario",
            goals=[InlineFixtureBuilder.make_goal("Career")],
            tasks=[InlineFixtureBuilder.make_task("Task 1")],
        )
        assert scenario.id == "TEST01"
        assert scenario.name == "Test Scenario"
        assert len(scenario.context.goals) == 1
        assert len(scenario.context.tasks) == 1

    def test_make_goal_defaults(self) -> None:
        """Should create a goal with sensible defaults."""
        goal = InlineFixtureBuilder.make_goal("Career")
        assert goal.title == "Career"
        assert goal.status == "active"
        assert goal.deadline is None
        assert goal.related_tasks == []

    def test_make_task_defaults(self) -> None:
        """Should create a task with sensible defaults."""
        task = InlineFixtureBuilder.make_task("Write plan")
        assert task.title == "Write plan"
        assert task.due_date is None
        assert task.priority == 1
        assert task.state is None

    def test_make_task_with_due_date(self) -> None:
        """Should create a task with a specific due date."""
        due = date.today() + timedelta(days=5)
        task = InlineFixtureBuilder.make_task("Task", due_date=due)
        assert task.due_date == due


# ═══════════════════════════════════════════════════════════════════════════════
# PLANNER RUNNER TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestPlannerRunner:
    """Tests for the PlannerRunner class."""

    def test_run_returns_result(self) -> None:
        """Should return a PlannerResult with a plan."""
        runner = PlannerRunner()
        planner = RuleBasedPlanner()
        context = PlanningContext(
            goals=[Goal(title="Career", related_tasks=["Task 1"])],
            tasks=[Task(title="Task 1", due_date=date.today() + timedelta(days=3))],
            calendar=[],
        )
        result = runner.run(planner, context)
        assert result.success is True
        assert result.plan is not None
        assert isinstance(result.plan, WeeklyPlan)

    def test_run_isolated_no_mutation(self) -> None:
        """Should not mutate the original context."""
        runner = PlannerRunner()
        planner = RuleBasedPlanner()
        context = PlanningContext(
            goals=[Goal(title="Career", related_tasks=["Task 1"])],
            tasks=[Task(title="Task 1", due_date=date.today() + timedelta(days=3))],
            calendar=[],
        )
        original_tasks = list(context.tasks)
        result = runner.run_isolated(planner, context)
        assert result.success is True
        assert context.tasks == original_tasks

    def test_run_with_failing_planner(self) -> None:
        """Should capture errors in the result."""
        runner = PlannerRunner()

        class FailingPlanner:
            def plan(self, context: PlanningContext) -> WeeklyPlan:
                raise RuntimeError("Planner failed")

        context = PlanningContext(goals=[], tasks=[], calendar=[])
        result = runner.run(FailingPlanner(), context)
        assert result.success is False
        assert result.plan is None
        assert result.error is not None
        assert "Planner failed" in result.error

    def test_run_isolated_deep_copy_prevents_mutation(self) -> None:
        """Deep copy in run_isolated should prevent mutation of original context."""
        runner = PlannerRunner()

        class MutatingPlanner:
            def plan(self, context: PlanningContext) -> WeeklyPlan:
                context.tasks.clear()  # type: ignore
                return WeeklyPlan(week_summary="mutated")

        context = PlanningContext(
            goals=[],
            tasks=[Task(title="Task 1")],
            calendar=[],
        )
        result = runner.run_isolated(MutatingPlanner(), context)
        # Original context should be unchanged due to deep copy
        assert len(context.tasks) == 1
        assert result.success is True


# ═══════════════════════════════════════════════════════════════════════════════
# ASSERTION HELPER TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestAssertionHelper:
    """Tests for the AssertionHelper class."""

    def _make_plan(self) -> WeeklyPlan:
        return WeeklyPlan(
            week_summary="Test plan",
            priorities=[
                PriorityEntry(goal_id="Career", reason="Has tasks", priority=Priority.HIGH),
            ],
            planned_tasks=[
                PlannedTask(
                    task_id="Task 1",
                    goal_id="Career",
                    priority=Priority.HIGH,
                    reason="Due soon",
                    suggested_day=date.today(),
                ),
            ],
            risks=[],
        )

    def _make_context(self) -> PlanningContext:
        return PlanningContext(
            goals=[Goal(title="Career", related_tasks=["Task 1"])],
            tasks=[Task(title="Task 1", due_date=date.today() + timedelta(days=3))],
            calendar=[],
        )

    def test_check_all_passes(self) -> None:
        """Should pass all assertions for a valid plan."""
        plan = self._make_plan()
        context = self._make_context()
        expected = ExpectedOutput(
            min_task_coverage=1.0,
            plan_validity=True,
        )
        helper = AssertionHelper(plan, context, expected)
        report = helper.check_all()
        assert report.all_passed is True

    def test_check_plan_validity_passes(self) -> None:
        """Should pass for a plan with valid references."""
        plan = self._make_plan()
        context = self._make_context()
        expected = ExpectedOutput(plan_validity=True)
        helper = AssertionHelper(plan, context, expected)
        result = helper.check_plan_validity()
        assert result.passed is True

    def test_check_plan_validity_fails_unknown_goal(self) -> None:
        """Should fail for a plan referencing an unknown goal."""
        plan = WeeklyPlan(
            week_summary="Bad plan",
            priorities=[
                PriorityEntry(goal_id="Unknown", reason="???", priority=Priority.HIGH),
            ],
        )
        context = self._make_context()
        expected = ExpectedOutput(plan_validity=True)
        helper = AssertionHelper(plan, context, expected)
        result = helper.check_plan_validity()
        assert result.passed is False
        assert "unknown goal" in result.message.lower()

    def test_check_task_coverage_passes(self) -> None:
        """Should pass when all tasks are planned."""
        plan = self._make_plan()
        context = self._make_context()
        expected = ExpectedOutput(min_task_coverage=1.0)
        helper = AssertionHelper(plan, context, expected)
        result = helper.check_task_coverage()
        assert result.passed is True

    def test_check_task_coverage_fails(self) -> None:
        """Should fail when not all tasks are planned."""
        plan = WeeklyPlan(week_summary="Empty plan")
        context = self._make_context()
        expected = ExpectedOutput(min_task_coverage=1.0)
        helper = AssertionHelper(plan, context, expected)
        result = helper.check_task_coverage()
        assert result.passed is False

    def test_check_overdue_handling_passes(self) -> None:
        """Should pass when overdue tasks have HIGH priority."""
        today = date.today()
        plan = WeeklyPlan(
            week_summary="Plan",
            planned_tasks=[
                PlannedTask(
                    task_id="Overdue",
                    goal_id="Career",
                    priority=Priority.HIGH,
                    reason="Overdue",
                    suggested_day=today,
                ),
            ],
        )
        context = PlanningContext(
            goals=[Goal(title="Career", related_tasks=["Overdue"])],
            tasks=[Task(title="Overdue", due_date=today - timedelta(days=5))],
            calendar=[],
            signals=PlanningSignals(overdue_tasks=["Overdue"]),
        )
        expected = ExpectedOutput(overdue_handling=True)
        helper = AssertionHelper(plan, context, expected)
        result = helper.check_overdue_handling()
        assert result.passed is True

    def test_check_deadline_awareness_passes(self) -> None:
        """Should pass when tasks are scheduled on/before due date."""
        today = date.today()
        plan = WeeklyPlan(
            week_summary="Plan",
            planned_tasks=[
                PlannedTask(
                    task_id="Task 1",
                    goal_id="Career",
                    priority=Priority.MEDIUM,
                    reason="Due soon",
                    suggested_day=today + timedelta(days=2),
                ),
            ],
        )
        context = PlanningContext(
            goals=[Goal(title="Career", related_tasks=["Task 1"])],
            tasks=[Task(title="Task 1", due_date=today + timedelta(days=3))],
            calendar=[],
        )
        expected = ExpectedOutput(deadline_awareness=True)
        helper = AssertionHelper(plan, context, expected)
        result = helper.check_deadline_awareness()
        assert result.passed is True

    def test_check_deadline_awareness_fails(self) -> None:
        """Should fail when task is scheduled after due date."""
        today = date.today()
        plan = WeeklyPlan(
            week_summary="Plan",
            planned_tasks=[
                PlannedTask(
                    task_id="Task 1",
                    goal_id="Career",
                    priority=Priority.MEDIUM,
                    reason="Late",
                    suggested_day=today + timedelta(days=5),
                ),
            ],
        )
        context = PlanningContext(
            goals=[Goal(title="Career", related_tasks=["Task 1"])],
            tasks=[Task(title="Task 1", due_date=today + timedelta(days=3))],
            calendar=[],
        )
        expected = ExpectedOutput(deadline_awareness=True)
        helper = AssertionHelper(plan, context, expected)
        result = helper.check_deadline_awareness()
        assert result.passed is False

    def test_check_unsupported_recommendations_passes(self) -> None:
        """Should pass when no unknown references exist."""
        plan = self._make_plan()
        context = self._make_context()
        expected = ExpectedOutput(max_unsupported_recommendations=0)
        helper = AssertionHelper(plan, context, expected)
        result = helper.check_unsupported_recommendations()
        assert result.passed is True

    def test_check_risk_keywords_passes(self) -> None:
        """Should pass when expected keywords appear in risks."""
        plan = WeeklyPlan(
            week_summary="Plan",
            risks=[],
        )
        context = PlanningContext(
            goals=[Goal(title="Career")],
            tasks=[],
            calendar=[],
            signals=PlanningSignals(overdue_tasks=["Task 1"]),
        )
        expected = ExpectedOutput(expected_risk_keywords=["Overdue"])
        helper = AssertionHelper(plan, context, expected)
        result = helper.check_risk_keywords()
        assert result.passed is False  # No risks in plan

    def test_check_priority_goals_passes(self) -> None:
        """Should pass when expected goals appear in priorities."""
        plan = self._make_plan()
        context = self._make_context()
        expected = ExpectedOutput(expected_priority_goals=["Career"])
        helper = AssertionHelper(plan, context, expected)
        result = helper.check_priority_goals()
        assert result.passed is True

    def test_check_priority_goals_fails(self) -> None:
        """Should fail when expected goals are missing from priorities."""
        plan = WeeklyPlan(week_summary="Plan")
        context = self._make_context()
        expected = ExpectedOutput(expected_priority_goals=["Missing Goal"])
        helper = AssertionHelper(plan, context, expected)
        result = helper.check_priority_goals()
        assert result.passed is False


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO RUNNER TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestScenarioRunner:
    """Tests for the ScenarioRunner class."""

    def test_run_scenario_s01(self) -> None:
        """Should run S01 and pass."""
        runner = ScenarioRunner()
        loader = FixtureLoader()
        scenario = loader.load_by_id("S01")
        result = runner.run_scenario(scenario)
        assert result.passed is True
        assert result.error is None

    def test_run_scenario_s02(self) -> None:
        """Should run S02 and pass."""
        runner = ScenarioRunner()
        loader = FixtureLoader()
        scenario = loader.load_by_id("S02")
        result = runner.run_scenario(scenario)
        assert result.passed is True

    def test_run_scenario_s07_empty(self) -> None:
        """Should run S07 (empty tasks) and pass."""
        runner = ScenarioRunner()
        loader = FixtureLoader()
        scenario = loader.load_by_id("S07")
        result = runner.run_scenario(scenario)
        assert result.passed is True

    def test_run_all_scenarios(self) -> None:
        """Should run all scenarios from fixtures."""
        runner = ScenarioRunner()
        suite = runner.run_all()
        assert suite.total_scenarios == 10
        assert suite.all_passed is True

    def test_run_by_id(self) -> None:
        """Should run a single scenario by ID."""
        runner = ScenarioRunner()
        result = runner.run_by_id("S01")
        assert result.scenario_id == "S01"
        assert result.passed is True

    def test_suite_result_summary(self) -> None:
        """Should produce a summary string."""
        runner = ScenarioRunner()
        suite = runner.run_all()
        summary = suite.summary()
        assert "10/10 passed" in summary

    def test_scenario_result_to_dict(self) -> None:
        """Should convert to dictionary."""
        result = ScenarioResult(
            scenario_id="S01",
            scenario_name="Test",
            passed=True,
        )
        d = result.to_dict()
        assert d["scenario_id"] == "S01"
        assert d["passed"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# MOCK LLM CLIENT TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestMockLLMClient:
    """Tests for the MockLLMClient class."""

    def test_generate_returns_response(self) -> None:
        """Should return the predefined response."""
        client = MockLLMClient(response='{"test": true}')
        result = client.generate("prompt")
        assert result == '{"test": true}'
        assert client.call_count == 1

    def test_generate_raises_exception(self) -> None:
        """Should raise the predefined exception."""
        client = MockLLMClient(exception=RuntimeError("LLM down"))
        with pytest.raises(RuntimeError, match="LLM down"):
            client.generate("prompt")
        assert client.call_count == 1

    def test_generate_returns_empty_json_by_default(self) -> None:
        """Should return '{}' when no response is set."""
        client = MockLLMClient()
        result = client.generate("prompt")
        assert result == "{}"

    def test_tracks_prompt(self) -> None:
        """Should store the last prompt."""
        client = MockLLMClient(response="ok")
        client.generate("test prompt")
        assert client.last_prompt == "test prompt"


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegration:
    """Integration tests for the full evaluation pipeline."""

    def test_full_pipeline_s01(self) -> None:
        """Should load, run, and validate S01 end-to-end."""
        loader = FixtureLoader()
        runner = ScenarioRunner()
        scenario = loader.load_by_id("S01")
        result = runner.run_scenario(scenario)
        assert result.passed is True
        assert result.assertion_report is not None
        assert result.assertion_report.all_passed is True

    def test_full_pipeline_all_scenarios(self) -> None:
        """Should run all 10 scenarios and produce a report."""
        runner = ScenarioRunner()
        suite = runner.run_all()
        assert suite.total_scenarios == 10
        assert suite.all_passed is True
        summary = suite.summary()
        assert "10/10 passed" in summary

    def test_determinism_same_result_twice(self) -> None:
        """Running the same scenario twice should produce the same result."""
        loader = FixtureLoader()
        runner = ScenarioRunner()
        scenario = loader.load_by_id("S01")
        result1 = runner.run_scenario(scenario)
        result2 = runner.run_scenario(scenario)
        assert result1.passed == result2.passed
        if result1.planner_result and result2.planner_result:
            assert result1.planner_result.plan == result2.planner_result.plan

    def test_context_not_mutated_by_runner(self) -> None:
        """The original scenario context should not be mutated."""
        loader = FixtureLoader()
        runner = ScenarioRunner()
        scenario = loader.load_by_id("S02")
        original_task_count = len(scenario.context.tasks)
        original_goal_count = len(scenario.context.goals)
        runner.run_scenario(scenario)
        assert len(scenario.context.tasks) == original_task_count
        assert len(scenario.context.goals) == original_goal_count
