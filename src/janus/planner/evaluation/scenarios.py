"""Scenario runner for executing evaluation scenarios in isolation.

Executes scenarios with full state isolation, collects results, and
provides a summary report. Each scenario runs independently with its
own planner instance and deep-copied context.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from janus.planner.evaluation.assertions import AssertionReport, AssertionResult
from janus.planner.evaluation.fixtures import (
    ExpectedOutput,
    FixtureLoader,
    InlineFixtureBuilder,
    Scenario,
)
from janus.planner.evaluation.runner import MockLLMClient, PlannerRunner, PlannerResult
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
from janus.planner.llm_planner import LLMWeeklyPlanner
from janus.plan_cli import RuleBasedPlanner


@dataclass
class ScenarioResult:
    """Result of executing a single scenario.

    Attributes:
        scenario_id: The scenario ID.
        scenario_name: Human-readable name.
        passed: Whether the scenario passed all assertions.
        planner_result: The raw planner invocation result.
        assertion_report: Detailed assertion results.
        error: Error message if the scenario failed to execute.
    """

    scenario_id: str
    scenario_name: str
    passed: bool
    planner_result: PlannerResult | None = None
    assertion_report: AssertionReport | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for reporting."""
        return {
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "passed": self.passed,
            "error": self.error,
            "assertions_passed": self.assertion_report.passed_count if self.assertion_report else 0,
            "assertions_failed": self.assertion_report.failed_count if self.assertion_report else 0,
        }


@dataclass
class ScenarioSuiteResult:
    """Results from running a suite of scenarios.

    Attributes:
        results: List of individual scenario results.
        total_scenarios: Total number of scenarios executed.
        passed_scenarios: Number of scenarios that passed.
        failed_scenarios: Number of scenarios that failed.
    """

    results: list[ScenarioResult] = field(default_factory=list)

    @property
    def total_scenarios(self) -> int:
        return len(self.results)

    @property
    def passed_scenarios(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_scenarios(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def all_passed(self) -> bool:
        return self.failed_scenarios == 0

    def summary(self) -> str:
        lines = [
            f"Scenario Suite: {self.passed_scenarios}/{self.total_scenarios} passed",
            "-" * 60,
        ]
        for r in self.results:
            status = "PASS" if r.passed else "FAIL"
            lines.append(f"  [{status}] {r.scenario_id}: {r.scenario_name}")
            if r.error:
                lines.append(f"         Error: {r.error}")
            if r.assertion_report:
                for ar in r.assertion_report.results:
                    if not ar.passed:
                        lines.append(f"         Assertion failed: {ar.message}")
        return "\n".join(lines)


class ScenarioRunner:
    """Runs evaluation scenarios in isolation.

    Each scenario is executed with:
    - A fresh planner instance (no shared state).
    - A deep-copied context (no mutation of original).
    - Full assertion reporting.

    Usage::

        runner = ScenarioRunner()
        result = runner.run_scenario(scenario)
        assert result.passed

        # Or run all scenarios from fixtures:
        suite = runner.run_all()
        print(suite.summary())
    """

    def __init__(self) -> None:
        self._runner = PlannerRunner()

    def run_scenario(self, scenario: Scenario) -> ScenarioResult:
        """Execute a single scenario in isolation.

        Args:
            scenario: The scenario to execute.

        Returns:
            ScenarioResult with pass/fail status and details.
        """
        try:
            # Build the appropriate planner
            planner = self._build_planner(scenario)

            # Run with state isolation
            planner_result = self._runner.run_isolated(planner, scenario.context)

            if not planner_result.success or planner_result.plan is None:
                return ScenarioResult(
                    scenario_id=scenario.id,
                    scenario_name=scenario.name,
                    passed=False,
                    planner_result=planner_result,
                    error=planner_result.error,
                )

            # Run assertions
            from janus.planner.evaluation.assertions import AssertionHelper
            helper = AssertionHelper(
                plan=planner_result.plan,
                context=scenario.context,
                expected=scenario.expected,
            )
            report = helper.check_all()

            return ScenarioResult(
                scenario_id=scenario.id,
                scenario_name=scenario.name,
                passed=report.all_passed,
                planner_result=planner_result,
                assertion_report=report,
            )

        except Exception as e:
            return ScenarioResult(
                scenario_id=scenario.id,
                scenario_name=scenario.name,
                passed=False,
                error=f"{type(e).__name__}: {e}",
            )

    def run_all(self, scenarios: list[Scenario] | None = None) -> ScenarioSuiteResult:
        """Run all scenarios and return the suite result.

        Args:
            scenarios: List of scenarios to run. If None, loads all
                scenarios from the default fixture directory.

        Returns:
            ScenarioSuiteResult with all scenario results.
        """
        if scenarios is None:
            loader = FixtureLoader()
            scenarios = loader.load_all()

        results = [self.run_scenario(s) for s in scenarios]
        return ScenarioSuiteResult(results=results)

    def run_by_id(self, scenario_id: str) -> ScenarioResult:
        """Run a single scenario by ID.

        Args:
            scenario_id: The scenario ID (e.g. "S01").

        Returns:
            ScenarioResult for the matching scenario.
        """
        loader = FixtureLoader()
        scenario = loader.load_by_id(scenario_id)
        return self.run_scenario(scenario)

    def _build_planner(self, scenario: Scenario):
        """Build the appropriate planner for a scenario."""
        if scenario.planner_type == "rule_based":
            return RuleBasedPlanner()
        elif scenario.planner_type == "llm":
            if scenario.llm_response is None:
                raise ValueError(f"LLM scenario {scenario.id} missing llm_response")
            client = MockLLMClient(response=scenario.llm_response)
            return LLMWeeklyPlanner(client=client)
        else:
            raise ValueError(f"Unknown planner_type: {scenario.planner_type!r}")


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════


def run_scenario(scenario: Scenario) -> ScenarioResult:
    """Convenience function to run a single scenario."""
    return ScenarioRunner().run_scenario(scenario)


def run_all_scenarios(fixture_dir: str | None = None) -> ScenarioSuiteResult:
    """Convenience function to run all scenarios from fixtures."""
    if fixture_dir:
        loader = FixtureLoader(fixture_dir=__import__("pathlib").Path(fixture_dir))
        scenarios = loader.load_all()
    else:
        scenarios = None
    return ScenarioRunner().run_all(scenarios)
