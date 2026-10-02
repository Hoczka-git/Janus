"""Assertion helpers for comparing planner outputs against expected values.

Provides a fluent API for asserting that a WeeklyPlan meets the criteria
defined in an ExpectedOutput. All assertions return AssertionResult objects
that can be combined for comprehensive scenario validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from janus.planner.evaluation.fixtures import ExpectedOutput
from janus.planner.models import (
    PlannedTask,
    PlanningContext,
    Priority,
    RiskSeverity,
    WeeklyPlan,
)


@dataclass
class AssertionResult:
    """Result of a single assertion.

    Attributes:
        passed: Whether the assertion passed.
        message: Human-readable description of the assertion result.
        assertion_name: Name of the assertion that was checked.
    """

    passed: bool
    message: str
    assertion_name: str

    def __bool__(self) -> bool:
        return self.passed


@dataclass
class AssertionReport:
    """Comprehensive report from running all assertions.

    Attributes:
        results: List of individual assertion results.
        all_passed: Whether all assertions passed.
    """

    results: list[AssertionResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    def add(self, result: AssertionResult) -> None:
        self.results.append(result)

    def summary(self) -> str:
        lines = [f"Assertions: {self.passed_count} passed, {self.failed_count} failed"]
        for r in self.results:
            status = "PASS" if r.passed else "FAIL"
            lines.append(f"  [{status}] {r.assertion_name}: {r.message}")
        return "\n".join(lines)


class AssertionHelper:
    """Fluent assertion helper for planner output validation.

    Usage::

        helper = AssertionHelper(plan, context, expected)
        report = helper.check_all()
        assert report.all_passed, report.summary()
    """

    def __init__(
        self,
        plan: WeeklyPlan,
        context: PlanningContext,
        expected: ExpectedOutput,
    ) -> None:
        self.plan = plan
        self.context = context
        self.expected = expected

    def check_all(self) -> AssertionReport:
        """Run all applicable assertions based on expected criteria."""
        report = AssertionReport()

        # Always check plan validity
        report.add(self.check_plan_validity())

        # Check task coverage if threshold > 0
        if self.expected.min_task_coverage > 0:
            report.add(self.check_task_coverage())

        # Check overdue handling if required
        if self.expected.overdue_handling:
            report.add(self.check_overdue_handling())

        # Check deadline awareness if required
        if self.expected.deadline_awareness:
            report.add(self.check_deadline_awareness())

        # Check calendar conflict rate if threshold > 0
        if self.expected.min_calendar_conflict_rate > 0:
            report.add(self.check_calendar_conflict_rate())

        # Check unsupported recommendations
        report.add(self.check_unsupported_recommendations())

        # Check expected risk keywords
        if self.expected.expected_risk_keywords:
            report.add(self.check_risk_keywords())

        # Check expected priority goals
        if self.expected.expected_priority_goals:
            report.add(self.check_priority_goals())

        return report

    def check_plan_validity(self) -> AssertionResult:
        """Check that the plan passes all validation checks."""
        valid_goal_ids = {g.title for g in self.context.goals}
        valid_task_ids = {t.title for t in self.context.tasks}

        # Check priorities reference known goals
        for entry in self.plan.priorities:
            if entry.goal_id not in valid_goal_ids:
                return AssertionResult(
                    passed=False,
                    message=f"Priority references unknown goal: {entry.goal_id!r}",
                    assertion_name="plan_validity",
                )

        # Check planned tasks reference known tasks and goals
        for task in self.plan.planned_tasks:
            if task.task_id not in valid_task_ids:
                return AssertionResult(
                    passed=False,
                    message=f"Planned task references unknown task: {task.task_id!r}",
                    assertion_name="plan_validity",
                )
            if task.goal_id and task.goal_id not in valid_goal_ids:
                return AssertionResult(
                    passed=False,
                    message=f"Planned task references unknown goal: {task.goal_id!r}",
                    assertion_name="plan_validity",
                )

        # Check for duplicate task scheduling
        task_days: dict[str, date] = {}
        for task in self.plan.planned_tasks:
            if task.task_id in task_days:
                return AssertionResult(
                    passed=False,
                    message=f"Task {task.task_id!r} scheduled for multiple days",
                    assertion_name="plan_validity",
                )
            task_days[task.task_id] = task.suggested_day

        return AssertionResult(
            passed=True,
            message="Plan is valid",
            assertion_name="plan_validity",
        )

    def check_task_coverage(self) -> AssertionResult:
        """Check that the minimum fraction of tasks are planned."""
        if not self.context.tasks:
            return AssertionResult(
                passed=True,
                message="No tasks to cover (vacuously true)",
                assertion_name="task_coverage",
            )

        planned_task_ids = {t.task_id for t in self.plan.planned_tasks}
        context_task_ids = {t.title for t in self.context.tasks}
        covered = len(planned_task_ids & context_task_ids)
        coverage = covered / len(context_task_ids)

        passed = coverage >= self.expected.min_task_coverage
        return AssertionResult(
            passed=passed,
            message=f"Task coverage: {coverage:.0%} (expected >= {self.expected.min_task_coverage:.0%})",
            assertion_name="task_coverage",
        )

    def check_overdue_handling(self) -> AssertionResult:
        """Check that all overdue tasks get HIGH priority."""
        if not self.context.signals.overdue_tasks:
            return AssertionResult(
                passed=True,
                message="No overdue tasks (vacuously true)",
                assertion_name="overdue_handling",
            )

        planned_task_map = {t.task_id: t for t in self.plan.planned_tasks}
        for task_title in self.context.signals.overdue_tasks:
            if task_title in planned_task_map:
                if planned_task_map[task_title].priority != Priority.HIGH:
                    return AssertionResult(
                        passed=False,
                        message=f"Overdue task {task_title!r} does not have HIGH priority",
                        assertion_name="overdue_handling",
                    )

        return AssertionResult(
            passed=True,
            message="All overdue tasks have HIGH priority",
            assertion_name="overdue_handling",
        )

    def check_deadline_awareness(self) -> AssertionResult:
        """Check that non-overdue tasks are scheduled on or before their due date."""
        if not self.context.tasks:
            return AssertionResult(
                passed=True,
                message="No tasks (vacuously true)",
                assertion_name="deadline_awareness",
            )

        today = date.today()
        task_due_map = {t.title: t.due_date for t in self.context.tasks if t.due_date}

        for planned in self.plan.planned_tasks:
            if planned.task_id in task_due_map:
                due = task_due_map[planned.task_id]
                if due and due >= today and planned.suggested_day > due:
                    return AssertionResult(
                        passed=False,
                        message=(
                            f"Task {planned.task_id!r} scheduled for {planned.suggested_day} "
                            f"but due {due}"
                        ),
                        assertion_name="deadline_awareness",
                    )

        return AssertionResult(
            passed=True,
            message="All non-overdue tasks scheduled on/before due date",
            assertion_name="deadline_awareness",
        )

    def check_calendar_conflict_rate(self) -> AssertionResult:
        """Check that the minimum fraction of calendar conflicts are detected."""
        if not self.context.signals.calendar_conflicts:
            return AssertionResult(
                passed=True,
                message="No calendar conflicts (vacuously true)",
                assertion_name="calendar_conflict_rate",
            )

        risk_descriptions = [r.description for r in self.plan.risks]
        detected = 0
        for conflict in self.context.signals.calendar_conflicts:
            if any(conflict in desc for desc in risk_descriptions):
                detected += 1

        rate = detected / len(self.context.signals.calendar_conflicts)
        passed = rate >= self.expected.min_calendar_conflict_rate

        return AssertionResult(
            passed=passed,
            message=f"Calendar conflict rate: {rate:.0%} (expected >= {self.expected.min_calendar_conflict_rate:.0%})",
            assertion_name="calendar_conflict_rate",
        )

    def check_unsupported_recommendations(self) -> AssertionResult:
        """Check that the number of unknown references is within the limit."""
        valid_goal_ids = {g.title for g in self.context.goals}
        valid_task_ids = {t.title for t in self.context.tasks}
        count = 0

        for entry in self.plan.priorities:
            if entry.goal_id not in valid_goal_ids:
                count += 1

        for task in self.plan.planned_tasks:
            if task.task_id not in valid_task_ids:
                count += 1
            if task.goal_id and task.goal_id not in valid_goal_ids:
                count += 1

        passed = count <= self.expected.max_unsupported_recommendations
        return AssertionResult(
            passed=passed,
            message=f"Unsupported recommendations: {count} (max allowed: {self.expected.max_unsupported_recommendations})",
            assertion_name="unsupported_recommendations",
        )

    def check_risk_keywords(self) -> AssertionResult:
        """Check that expected keywords appear in risk descriptions."""
        risk_descriptions = [r.description for r in self.plan.risks]
        missing = []
        for keyword in self.expected.expected_risk_keywords:
            if not any(keyword in desc for desc in risk_descriptions):
                missing.append(keyword)

        passed = not missing
        return AssertionResult(
            passed=passed,
            message=f"Missing risk keywords: {missing}" if missing else "All expected risk keywords found",
            assertion_name="risk_keywords",
        )

    def check_priority_goals(self) -> AssertionResult:
        """Check that expected goals appear in priorities."""
        priority_goal_ids = {p.goal_id for p in self.plan.priorities}
        missing = [g for g in self.expected.expected_priority_goals if g not in priority_goal_ids]

        passed = not missing
        return AssertionResult(
            passed=passed,
            message=f"Missing priority goals: {missing}" if missing else "All expected goals in priorities",
            assertion_name="priority_goals",
        )
