"""Scenario test cases 1-5 for the weekly planner evaluation suite.

Covers the first 5 scenarios from the spec:
    S01: Single urgent task
    S02: Multiple overdue tasks
    S03: Stalled goal
    S04: No calendar availability
    S05: Deadline conflict

Each test case:
    1. SETUP: Loads the scenario fixture from JSON.
    2. INVOCATION: Runs the planner deterministically via ScenarioRunner.
    3. ASSERTIONS: Validates expected outputs (coverage, priorities, risks).
    4. TEARDOWN: Verifies no state leakage between scenarios.

Usage:
    pytest tests/test_planner_scenarios_1_5.py -v
    pytest tests/test_planner_scenarios_1_5.py -v --tb=short
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from janus.planner.evaluation.fixtures import FixtureLoader, Scenario
from janus.planner.evaluation.scenarios import ScenarioResult, ScenarioRunner
from janus.planner.models import Priority


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES (SETUP)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def loader() -> FixtureLoader:
    """Provide a FixtureLoader instance for all scenario tests."""
    return FixtureLoader()


@pytest.fixture(scope="module")
def runner() -> ScenarioRunner:
    """Provide a ScenarioRunner instance for all scenario tests."""
    return ScenarioRunner()


@pytest.fixture(scope="module")
def s01(loader: FixtureLoader) -> Scenario:
    """Load S01: Single urgent task."""
    return loader.load_by_id("S01")


@pytest.fixture(scope="module")
def s02(loader: FixtureLoader) -> Scenario:
    """Load S02: Multiple overdue tasks."""
    return loader.load_by_id("S02")


@pytest.fixture(scope="module")
def s03(loader: FixtureLoader) -> Scenario:
    """Load S03: Stalled goal."""
    return loader.load_by_id("S03")


@pytest.fixture(scope="module")
def s04(loader: FixtureLoader) -> Scenario:
    """Load S04: No calendar availability."""
    return loader.load_by_id("S04")


@pytest.fixture(scope="module")
def s05(loader: FixtureLoader) -> Scenario:
    """Load S05: Deadline conflict."""
    return loader.load_by_id("S05")


# ═══════════════════════════════════════════════════════════════════════════════
# S01: SINGLE URGENT TASK
# ═══════════════════════════════════════════════════════════════════════════════


class TestS01SingleUrgentTask:
    """S01: Verify the planner elevates a single urgent task to HIGH priority."""

    def test_s01_scenario_loaded(self, s01: Scenario) -> None:
        """SETUP: S01 fixture loads correctly."""
        assert s01.id == "S01"
        assert s01.name == "Single urgent task"
        assert len(s01.context.goals) == 1
        assert len(s01.context.tasks) == 1
        assert len(s01.context.calendar) == 0

    def test_s01_planner_produces_plan(
        self, runner: ScenarioRunner, s01: Scenario
    ) -> None:
        """INVOCATION: Planner produces a valid WeeklyPlan."""
        result = runner.run_scenario(s01)
        assert result.error is None, f"S01 failed to execute: {result.error}"
        assert result.planner_result is not None
        assert result.planner_result.success is True
        assert result.planner_result.plan is not None

    def test_s01_task_coverage(
        self, runner: ScenarioRunner, s01: Scenario
    ) -> None:
        """ASSERTION: All tasks are covered in the plan."""
        result = runner.run_scenario(s01)
        assert result.passed is True, (
            f"S01 assertions failed: {result.assertion_report.summary() if result.assertion_report else 'no report'}"
        )
        assert result.assertion_report is not None
        assert result.assertion_report.all_passed is True

    def test_s01_goal_in_priorities(
        self, runner: ScenarioRunner, s01: Scenario
    ) -> None:
        """ASSERTION: The 'Career' goal appears in priorities."""
        result = runner.run_scenario(s01)
        assert result.planner_result is not None
        assert result.planner_result.plan is not None
        plan = result.planner_result.plan
        priority_goal_ids = {p.goal_id for p in plan.priorities}
        assert "Career" in priority_goal_ids, (
            f"Expected 'Career' in priorities, got: {priority_goal_ids}"
        )

    def test_s01_urgent_task_high_priority(
        self, runner: ScenarioRunner, s01: Scenario
    ) -> None:
        """ASSERTION: The urgent task (due today) gets HIGH priority."""
        result = runner.run_scenario(s01)
        assert result.planner_result is not None
        assert result.planner_result.plan is not None
        plan = result.planner_result.plan
        planned_task_map = {t.task_id: t for t in plan.planned_tasks}
        assert "Write plan" in planned_task_map, (
            f"Expected 'Write plan' in planned tasks, got: {list(planned_task_map.keys())}"
        )
        assert planned_task_map["Write plan"].priority == Priority.HIGH, (
            f"Expected HIGH priority for urgent task, got: {planned_task_map['Write plan'].priority}"
        )

    def test_s01_no_state_leakage(
        self, runner: ScenarioRunner, s01: Scenario
    ) -> None:
        """TEARDOWN: Original context is not mutated by planner execution."""
        original_task_count = len(s01.context.tasks)
        original_goal_count = len(s01.context.goals)
        runner.run_scenario(s01)
        assert len(s01.context.tasks) == original_task_count
        assert len(s01.context.goals) == original_goal_count


# ═══════════════════════════════════════════════════════════════════════════════
# S02: MULTIPLE OVERDUE TASKS
# ═══════════════════════════════════════════════════════════════════════════════


class TestS02MultipleOverdueTasks:
    """S02: All overdue tasks must be flagged HIGH priority and appear in risks."""

    def test_s02_scenario_loaded(self, s02: Scenario) -> None:
        """SETUP: S02 fixture loads correctly."""
        assert s02.id == "S02"
        assert s02.name == "Multiple overdue tasks"
        assert len(s02.context.goals) == 1
        assert len(s02.context.tasks) == 3
        assert len(s02.context.calendar) == 0

    def test_s02_planner_produces_plan(
        self, runner: ScenarioRunner, s02: Scenario
    ) -> None:
        """INVOCATION: Planner produces a valid WeeklyPlan."""
        result = runner.run_scenario(s02)
        assert result.error is None, f"S02 failed to execute: {result.error}"
        assert result.planner_result is not None
        assert result.planner_result.success is True
        assert result.planner_result.plan is not None

    def test_s02_task_coverage(
        self, runner: ScenarioRunner, s02: Scenario
    ) -> None:
        """ASSERTION: All 3 overdue tasks are covered in the plan."""
        result = runner.run_scenario(s02)
        assert result.passed is True, (
            f"S02 assertions failed: {result.assertion_report.summary() if result.assertion_report else 'no report'}"
        )
        assert result.assertion_report is not None
        assert result.assertion_report.all_passed is True

    def test_s02_overdue_tasks_high_priority(
        self, runner: ScenarioRunner, s02: Scenario
    ) -> None:
        """ASSERTION: All overdue tasks get HIGH priority."""
        result = runner.run_scenario(s02)
        assert result.planner_result is not None
        assert result.planner_result.plan is not None
        plan = result.planner_result.plan
        planned_task_map = {t.task_id: t for t in plan.planned_tasks}
        overdue_titles = ["Overdue A", "Overdue B", "Overdue C"]
        for title in overdue_titles:
            assert title in planned_task_map, (
                f"Expected overdue task '{title}' in planned tasks, got: {list(planned_task_map.keys())}"
            )
            assert planned_task_map[title].priority == Priority.HIGH, (
                f"Expected HIGH priority for overdue task '{title}', got: {planned_task_map[title].priority}"
            )

    def test_s02_overdue_risks_present(
        self, runner: ScenarioRunner, s02: Scenario
    ) -> None:
        """ASSERTION: Overdue tasks appear in risk descriptions."""
        result = runner.run_scenario(s02)
        assert result.planner_result is not None
        assert result.planner_result.plan is not None
        plan = result.planner_result.plan
        risk_descriptions = [r.description for r in plan.risks]
        overdue_risk_found = any(
            "Overdue" in desc for desc in risk_descriptions
        )
        assert overdue_risk_found, (
            f"Expected 'Overdue' in risk descriptions, got: {risk_descriptions}"
        )

    def test_s02_no_state_leakage(
        self, runner: ScenarioRunner, s02: Scenario
    ) -> None:
        """TEARDOWN: Original context is not mutated by planner execution."""
        original_task_count = len(s02.context.tasks)
        original_goal_count = len(s02.context.goals)
        runner.run_scenario(s02)
        assert len(s02.context.tasks) == original_task_count
        assert len(s02.context.goals) == original_goal_count


# ═══════════════════════════════════════════════════════════════════════════════
# S03: STALLED GOAL
# ═══════════════════════════════════════════════════════════════════════════════


class TestS03StalledGoal:
    """S03: A goal with no recent activity must be flagged as HIGH priority and in risks."""

    def test_s03_scenario_loaded(self, s03: Scenario) -> None:
        """SETUP: S03 fixture loads correctly."""
        assert s03.id == "S03"
        assert s03.name == "Stalled goal"
        assert len(s03.context.goals) == 2
        assert len(s03.context.tasks) == 0
        assert len(s03.context.calendar) == 0

    def test_s03_planner_produces_plan(
        self, runner: ScenarioRunner, s03: Scenario
    ) -> None:
        """INVOCATION: Planner produces a valid WeeklyPlan."""
        result = runner.run_scenario(s03)
        assert result.error is None, f"S03 failed to execute: {result.error}"
        assert result.planner_result is not None
        assert result.planner_result.success is True
        assert result.planner_result.plan is not None

    def test_s03_stalled_goal_in_priorities(
        self, runner: ScenarioRunner, s03: Scenario
    ) -> None:
        """ASSERTION: The 'Stalled Goal' appears in priorities."""
        result = runner.run_scenario(s03)
        assert result.planner_result is not None
        assert result.planner_result.plan is not None
        plan = result.planner_result.plan
        priority_goal_ids = {p.goal_id for p in plan.priorities}
        assert "Stalled Goal" in priority_goal_ids, (
            f"Expected 'Stalled Goal' in priorities, got: {priority_goal_ids}"
        )

    def test_s03_stalled_goal_high_priority(
        self, runner: ScenarioRunner, s03: Scenario
    ) -> None:
        """ASSERTION: The stalled goal gets HIGH priority."""
        result = runner.run_scenario(s03)
        assert result.planner_result is not None
        assert result.planner_result.plan is not None
        plan = result.planner_result.plan
        priority_map = {p.goal_id: p for p in plan.priorities}
        assert "Stalled Goal" in priority_map, (
            f"Expected 'Stalled Goal' in priorities, got: {list(priority_map.keys())}"
        )
        assert priority_map["Stalled Goal"].priority == Priority.HIGH, (
            f"Expected HIGH priority for stalled goal, got: {priority_map['Stalled Goal'].priority}"
        )

    def test_s03_stalled_risk_present(
        self, runner: ScenarioRunner, s03: Scenario
    ) -> None:
        """ASSERTION: Stalled goal appears in risk descriptions."""
        result = runner.run_scenario(s03)
        assert result.planner_result is not None
        assert result.planner_result.plan is not None
        plan = result.planner_result.plan
        risk_descriptions = [r.description for r in plan.risks]
        stalled_risk_found = any(
            "Stalled" in desc for desc in risk_descriptions
        )
        assert stalled_risk_found, (
            f"Expected 'Stalled' in risk descriptions, got: {risk_descriptions}"
        )

    def test_s03_no_state_leakage(
        self, runner: ScenarioRunner, s03: Scenario
    ) -> None:
        """TEARDOWN: Original context is not mutated by planner execution."""
        original_task_count = len(s03.context.tasks)
        original_goal_count = len(s03.context.goals)
        runner.run_scenario(s03)
        assert len(s03.context.tasks) == original_task_count
        assert len(s03.context.goals) == original_goal_count


# ═══════════════════════════════════════════════════════════════════════════════
# S04: NO CALENDAR AVAILABILITY
# ═══════════════════════════════════════════════════════════════════════════════


class TestS04NoCalendarAvailability:
    """S04: Planner should handle week with zero free slots (all days have events)."""

    def test_s04_scenario_loaded(self, s04: Scenario) -> None:
        """SETUP: S04 fixture loads correctly."""
        assert s04.id == "S04"
        assert s04.name == "No calendar availability"
        assert len(s04.context.goals) == 1
        assert len(s04.context.tasks) == 2
        assert len(s04.context.calendar) == 7  # All 7 days blocked

    def test_s04_planner_produces_plan(
        self, runner: ScenarioRunner, s04: Scenario
    ) -> None:
        """INVOCATION: Planner produces a valid WeeklyPlan."""
        result = runner.run_scenario(s04)
        assert result.error is None, f"S04 failed to execute: {result.error}"
        assert result.planner_result is not None
        assert result.planner_result.success is True
        assert result.planner_result.plan is not None

    def test_s04_task_coverage(
        self, runner: ScenarioRunner, s04: Scenario
    ) -> None:
        """ASSERTION: All tasks are covered despite zero free slots."""
        result = runner.run_scenario(s04)
        assert result.passed is True, (
            f"S04 assertions failed: {result.assertion_report.summary() if result.assertion_report else 'no report'}"
        )
        assert result.assertion_report is not None
        assert result.assertion_report.all_passed is True

    def test_s04_calendar_conflicts_detected(
        self, runner: ScenarioRunner, s04: Scenario
    ) -> None:
        """ASSERTION: Calendar conflicts are detected and reported as risks."""
        result = runner.run_scenario(s04)
        assert result.planner_result is not None
        assert result.planner_result.plan is not None
        plan = result.planner_result.plan
        risk_descriptions = [r.description for r in plan.risks]
        conflict_risks = [d for d in risk_descriptions if "conflicts" in d.lower()]
        assert len(conflict_risks) > 0, (
            f"Expected calendar conflict risks, got: {risk_descriptions}"
        )

    def test_s04_no_state_leakage(
        self, runner: ScenarioRunner, s04: Scenario
    ) -> None:
        """TEARDOWN: Original context is not mutated by planner execution."""
        original_task_count = len(s04.context.tasks)
        original_goal_count = len(s04.context.goals)
        original_calendar_count = len(s04.context.calendar)
        runner.run_scenario(s04)
        assert len(s04.context.tasks) == original_task_count
        assert len(s04.context.goals) == original_goal_count
        assert len(s04.context.calendar) == original_calendar_count


# ═══════════════════════════════════════════════════════════════════════════════
# S05: DEADLINE CONFLICT
# ═══════════════════════════════════════════════════════════════════════════════


class TestS05DeadlineConflict:
    """S05: Two tasks with the same deadline should be flagged as competing."""

    def test_s05_scenario_loaded(self, s05: Scenario) -> None:
        """SETUP: S05 fixture loads correctly."""
        assert s05.id == "S05"
        assert s05.name == "Deadline conflict"
        assert len(s05.context.goals) == 1
        assert len(s05.context.tasks) == 2
        assert len(s05.context.calendar) == 0

    def test_s05_planner_produces_plan(
        self, runner: ScenarioRunner, s05: Scenario
    ) -> None:
        """INVOCATION: Planner produces a valid WeeklyPlan."""
        result = runner.run_scenario(s05)
        assert result.error is None, f"S05 failed to execute: {result.error}"
        assert result.planner_result is not None
        assert result.planner_result.success is True
        assert result.planner_result.plan is not None

    def test_s05_task_coverage(
        self, runner: ScenarioRunner, s05: Scenario
    ) -> None:
        """ASSERTION: Both tasks are covered in the plan."""
        result = runner.run_scenario(s05)
        assert result.passed is True, (
            f"S05 assertions failed: {result.assertion_report.summary() if result.assertion_report else 'no report'}"
        )
        assert result.assertion_report is not None
        assert result.assertion_report.all_passed is True

    def test_s05_competing_tasks_risk(
        self, runner: ScenarioRunner, s05: Scenario
    ) -> None:
        """ASSERTION: Competing tasks are flagged in risk descriptions."""
        result = runner.run_scenario(s05)
        assert result.planner_result is not None
        assert result.planner_result.plan is not None
        plan = result.planner_result.plan
        risk_descriptions = [r.description for r in plan.risks]
        competing_risk_found = any(
            "Competing" in desc for desc in risk_descriptions
        )
        assert competing_risk_found, (
            f"Expected 'Competing' in risk descriptions, got: {risk_descriptions}"
        )

    def test_s05_deadline_awareness(
        self, runner: ScenarioRunner, s05: Scenario
    ) -> None:
        """ASSERTION: Tasks are scheduled on or before their due date."""
        result = runner.run_scenario(s05)
        assert result.planner_result is not None
        assert result.planner_result.plan is not None
        plan = result.planner_result.plan
        today = date.today()
        planned_task_map = {t.task_id: t for t in plan.planned_tasks}
        for task in s05.context.tasks:
            if task.title in planned_task_map:
                planned = planned_task_map[task.title]
                if task.due_date and task.due_date >= today:
                    assert planned.suggested_day <= task.due_date, (
                        f"Task '{task.title}' scheduled for {planned.suggested_day} "
                        f"but due {task.due_date}"
                    )

    def test_s05_no_state_leakage(
        self, runner: ScenarioRunner, s05: Scenario
    ) -> None:
        """TEARDOWN: Original context is not mutated by planner execution."""
        original_task_count = len(s05.context.tasks)
        original_goal_count = len(s05.context.goals)
        runner.run_scenario(s05)
        assert len(s05.context.tasks) == original_task_count
        assert len(s05.context.goals) == original_goal_count


# ═══════════════════════════════════════════════════════════════════════════════
# CROSS-SCENARIO DETERMINISM TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeterminismScenarios1To5:
    """Verify that scenarios 1-5 produce deterministic results across multiple runs."""

    @pytest.mark.parametrize("scenario_id", ["S01", "S02", "S03", "S04", "S05"])
    def test_scenario_deterministic(
        self, loader: FixtureLoader, runner: ScenarioRunner, scenario_id: str
    ) -> None:
        """Running the same scenario twice should produce identical results."""
        scenario = loader.load_by_id(scenario_id)
        result1 = runner.run_scenario(scenario)
        result2 = runner.run_scenario(scenario)
        assert result1.passed == result2.passed, (
            f"{scenario_id}: First run passed={result1.passed}, second run passed={result2.passed}"
        )
        if result1.planner_result and result2.planner_result:
            assert result1.planner_result.plan == result2.planner_result.plan, (
                f"{scenario_id}: Plans differ between runs"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# SUITE-LEVEL TEST
# ═══════════════════════════════════════════════════════════════════════════════


class TestScenarios1To5Suite:
    """Run all scenarios 1-5 as a suite and verify all pass."""

    def test_all_scenarios_pass(
        self, loader: FixtureLoader, runner: ScenarioRunner
    ) -> None:
        """All 5 scenarios should pass their assertions."""
        scenario_ids = ["S01", "S02", "S03", "S04", "S05"]
        results: list[ScenarioResult] = []
        for sid in scenario_ids:
            scenario = loader.load_by_id(sid)
            result = runner.run_scenario(scenario)
            results.append(result)

        failed = [r for r in results if not r.passed]
        assert len(failed) == 0, (
            f"Failed scenarios: {[(r.scenario_id, r.error) for r in failed]}"
        )
