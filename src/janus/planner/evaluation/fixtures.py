"""Deterministic fixture loader for planner evaluation scenarios.

Loads scenario definitions from JSON fixture files and constructs
PlanningContext objects with fixed dates for reproducibility.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from janus.models.event import Event
from janus.models.goal import Goal
from janus.models.task import Task
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


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURE DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ExpectedOutput:
    """Expected output for a scenario assertion.

    Attributes:
        min_task_coverage: Minimum fraction of tasks that must be planned (0.0-1.0).
        overdue_handling: True if overdue tasks must get HIGH priority.
        deadline_awareness: True if tasks must be scheduled on/before due dates.
        min_calendar_conflict_rate: Minimum fraction of conflicts detected (0.0-1.0).
        plan_validity: True if plan must pass all validation checks.
        max_unsupported_recommendations: Max allowed unknown references.
        expected_risk_keywords: Keywords that must appear in risk descriptions.
        expected_priority_goals: Goals that must appear in priorities.
    """

    min_task_coverage: float = 0.0
    overdue_handling: bool = False
    deadline_awareness: bool = False
    min_calendar_conflict_rate: float = 0.0
    plan_validity: bool = True
    max_unsupported_recommendations: int = 0
    expected_risk_keywords: list[str] = field(default_factory=list)
    expected_priority_goals: list[str] = field(default_factory=list)


@dataclass
class Scenario:
    """A single evaluation scenario with input context and expected output.

    Attributes:
        id: Unique scenario identifier (e.g. "S01").
        name: Human-readable scenario name.
        description: What this scenario tests.
        context: The PlanningContext to feed the planner.
        expected: Expected output criteria.
        planner_type: Which planner to use ("rule_based" or "llm").
        llm_response: Optional mock LLM response (for LLM planner scenarios).
    """

    id: str
    name: str
    description: str
    context: PlanningContext
    expected: ExpectedOutput
    planner_type: str = "rule_based"
    llm_response: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURE LOADER
# ═══════════════════════════════════════════════════════════════════════════════


class FixtureLoader:
    """Loads evaluation scenarios from JSON fixture files.

    Fixture files are stored in ``tests/fixtures/planner_evaluation/``
    and define scenarios with fixed dates for reproducibility.

    Each fixture file is a JSON object with a ``scenarios`` array, where
    each scenario has:
        - id: str
        - name: str
        - description: str
        - context: { goals: [...], tasks: [...], calendar: [...], signals: {...} }
        - expected: { ... }
        - planner_type: "rule_based" | "llm"
        - llm_response: str (optional)
    """

    DEFAULT_FIXTURE_DIR = Path(__file__).parent.parent.parent.parent.parent / "tests" / "fixtures" / "planner_evaluation"

    def __init__(self, fixture_dir: Path | None = None) -> None:
        """Initialize the fixture loader.

        Args:
            fixture_dir: Directory containing fixture JSON files.
                Defaults to ``tests/fixtures/planner_evaluation/``.
        """
        self.fixture_dir = fixture_dir or self.DEFAULT_FIXTURE_DIR

    def load_all(self) -> list[Scenario]:
        """Load all scenarios from all fixture files in the directory.

        Returns:
            List of Scenario objects.

        Raises:
            FileNotFoundError: If the fixture directory does not exist.
        """
        if not self.fixture_dir.exists():
            raise FileNotFoundError(f"Fixture directory not found: {self.fixture_dir}")

        scenarios: list[Scenario] = []
        for fixture_file in sorted(self.fixture_dir.glob("*.json")):
            scenarios.extend(self.load_file(fixture_file))
        return scenarios

    def load_file(self, path: Path) -> list[Scenario]:
        """Load scenarios from a single fixture file.

        Args:
            path: Path to the JSON fixture file.

        Returns:
            List of Scenario objects.

        Raises:
            ValueError: If the fixture file is malformed.
        """
        with open(path) as f:
            data = json.load(f)

        if "scenarios" not in data:
            raise ValueError(f"Fixture file {path} missing 'scenarios' key")

        scenarios: list[Scenario] = []
        for scenario_data in data["scenarios"]:
            scenarios.append(self._parse_scenario(scenario_data))
        return scenarios

    def load_by_id(self, scenario_id: str) -> Scenario:
        """Load a single scenario by its ID.

        Args:
            scenario_id: The scenario ID (e.g. "S01").

        Returns:
            The matching Scenario.

        Raises:
            ValueError: If no scenario with the given ID is found.
        """
        for scenario in self.load_all():
            if scenario.id == scenario_id:
                return scenario
        raise ValueError(f"Scenario '{scenario_id}' not found in fixtures")

    def _parse_scenario(self, data: dict[str, Any]) -> Scenario:
        """Parse a scenario from JSON data."""
        context_data = data["context"]
        context = self._build_context(context_data)

        expected_data = data.get("expected", {})
        expected = ExpectedOutput(
            min_task_coverage=expected_data.get("min_task_coverage", 0.0),
            overdue_handling=expected_data.get("overdue_handling", False),
            deadline_awareness=expected_data.get("deadline_awareness", False),
            min_calendar_conflict_rate=expected_data.get("min_calendar_conflict_rate", 0.0),
            plan_validity=expected_data.get("plan_validity", True),
            max_unsupported_recommendations=expected_data.get("max_unsupported_recommendations", 0),
            expected_risk_keywords=expected_data.get("expected_risk_keywords", []),
            expected_priority_goals=expected_data.get("expected_priority_goals", []),
        )

        return Scenario(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            context=context,
            expected=expected,
            planner_type=data.get("planner_type", "rule_based"),
            llm_response=data.get("llm_response"),
        )

    def _build_context(self, data: dict[str, Any]) -> PlanningContext:
        """Build a PlanningContext from JSON data."""
        goals = [self._build_goal(g) for g in data.get("goals", [])]
        tasks = [self._build_task(t) for t in data.get("tasks", [])]
        calendar = [self._build_event(e) for e in data.get("calendar", [])]
        signals = self._build_signals(data.get("signals", {}))

        return PlanningContext(
            goals=goals,
            tasks=tasks,
            calendar=calendar,
            signals=signals,
        )

    def _build_goal(self, data: dict[str, Any]) -> Goal:
        """Build a Goal from JSON data."""
        return Goal(
            title=data["title"],
            status=data.get("status", "active"),
            deadline=data.get("deadline"),
            related_tasks=data.get("related_tasks"),
            recent_activity=data.get("recent_activity"),
        )

    def _build_task(self, data: dict[str, Any]) -> Task:
        """Build a Task from JSON data."""
        due_date = None
        if data.get("due_date"):
            due_date = self._resolve_date(data["due_date"])
        return Task(
            title=data["title"],
            due_date=due_date,
            priority=data.get("priority", 1),
            state=data.get("state"),
        )

    def _build_event(self, data: dict[str, Any]) -> Event:
        """Build an Event from JSON data."""
        start = None
        if data.get("start"):
            resolved = self._resolve_date(data["start"])
            if resolved is not None:
                start = datetime.combine(resolved, datetime.min.time())
        return Event(
            title=data["title"],
            start=start,
            all_day=data.get("all_day", False),
        )

    def _resolve_date(self, value: str) -> date | None:
        """Resolve a date string that may be relative to today.

        Supports:
        - "today" → date.today()
        - "today+N" → date.today() + N days
        - "today-N" → date.today() - N days
        - ISO format "YYYY-MM-DD" → parsed directly
        """
        if value == "today":
            return date.today()
        if value.startswith("today+"):
            days = int(value[6:])
            return date.today() + timedelta(days=days)
        if value.startswith("today-"):
            days = int(value[6:])
            return date.today() - timedelta(days=days)
        return date.fromisoformat(value)

    def _build_signals(self, data: dict[str, Any]) -> PlanningSignals:
        """Build PlanningSignals from JSON data."""
        return PlanningSignals(
            overdue_tasks=data.get("overdue_tasks", []),
            due_soon_tasks=data.get("due_soon_tasks", []),
            stalled_goals=data.get("stalled_goals", []),
            behind_target_goals=data.get("behind_target_goals", []),
            calendar_conflicts=data.get("calendar_conflicts", []),
            competing_tasks=data.get("competing_tasks", {}),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# INLINE FIXTURE BUILDER (for programmatic scenario construction)
# ═══════════════════════════════════════════════════════════════════════════════


class InlineFixtureBuilder:
    """Build scenarios programmatically without JSON files.

    Useful for tests that need to construct scenarios inline.
    """

    @staticmethod
    def make_scenario(
        scenario_id: str,
        name: str,
        description: str,
        goals: list[Goal] | None = None,
        tasks: list[Task] | None = None,
        calendar: list[Event] | None = None,
        signals: PlanningSignals | None = None,
        expected: ExpectedOutput | None = None,
        planner_type: str = "rule_based",
        llm_response: str | None = None,
    ) -> Scenario:
        """Build a Scenario from individual components."""
        context = PlanningContext(
            goals=goals or [],
            tasks=tasks or [],
            calendar=calendar or [],
            signals=signals or PlanningSignals(),
        )
        return Scenario(
            id=scenario_id,
            name=name,
            description=description,
            context=context,
            expected=expected or ExpectedOutput(),
            planner_type=planner_type,
            llm_response=llm_response,
        )

    @staticmethod
    def make_goal(
        title: str = "Career",
        status: str = "active",
        deadline: str | None = None,
        related_tasks: list[str] | None = None,
        recent_activity: list[dict] | None = None,
    ) -> Goal:
        """Create a Goal with sensible defaults."""
        return Goal(
            title=title,
            status=status,
            deadline=deadline,
            related_tasks=related_tasks,
            recent_activity=recent_activity,
        )

    @staticmethod
    def make_task(
        title: str = "Write plan",
        due_date: date | None = None,
        priority: int = 1,
        state: str | None = None,
    ) -> Task:
        """Create a Task with sensible defaults."""
        return Task(
            title=title,
            due_date=due_date,
            priority=priority,
            state=state,
        )

    @staticmethod
    def make_event(
        title: str = "Meeting",
        start: datetime | None = None,
        all_day: bool = False,
    ) -> Event:
        """Create an Event with sensible defaults."""
        return Event(title=title, start=start, all_day=all_day)
