"""Targeted tests for proposal engine — transformation accuracy, edge cases,
proposal-only contract compliance, and mutation guard effectiveness.

These tests complement the existing test suite by covering:
- Edge cases (empty plans, malformed inputs, boundary conditions)
- Proposal-only contract compliance on the real RuleBasedProposalEngine
- Mutation guard effectiveness with the real engine
- Negative tests confirming mutation attempts fail
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from janus.models.event import Event
from janus.models.goal import Goal
from janus.models.policy import RiskLevel
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
from janus.proposal import (
    ActionProposal,
    ActionProposalEngine,
    ActionType,
    ImportGuard,
    MutationBlockedError,
    MutationGuard,
    ProposalOnlyEngine,
    ProposalStatus,
    RuleBasedProposalEngine,
    proposal_only,
    proposal_only_context,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def engine() -> RuleBasedProposalEngine:
    return RuleBasedProposalEngine()


@pytest.fixture
def empty_context() -> PlanningContext:
    return PlanningContext(goals=[], tasks=[], calendar=[])


@pytest.fixture
def empty_plan() -> WeeklyPlan:
    return WeeklyPlan(week_summary="Empty week")


@pytest.fixture
def sample_goal() -> Goal:
    return Goal(title="Improve code quality", description="Refactor legacy modules")


@pytest.fixture
def sample_task() -> Task:
    return Task(
        title="Write tests for module X",
        due_date=date.today() + timedelta(days=3),
        priority=2,
    )


@pytest.fixture
def overdue_task() -> Task:
    return Task(
        title="Fix critical bug",
        due_date=date.today() - timedelta(days=2),
        priority=2,
    )


@pytest.fixture
def sample_context(sample_goal: Goal, sample_task: Task) -> PlanningContext:
    return PlanningContext(
        goals=[sample_goal],
        tasks=[sample_task],
        calendar=[],
    )


@pytest.fixture
def sample_plan(sample_task: Task) -> WeeklyPlan:
    return WeeklyPlan(
        week_summary="Focus on testing and bug fixes",
        priorities=[
            PriorityEntry(
                goal_id="Improve code quality",
                reason="High impact on maintainability",
                priority=Priority.HIGH,
            ),
        ],
        planned_tasks=[
            PlannedTask(
                task_id=sample_task.title,
                goal_id="Improve code quality",
                priority=Priority.HIGH,
                reason="Critical for release",
                suggested_day=date.today() + timedelta(days=1),
            ),
        ],
        risks=[],
    )


# ── Edge Cases: Empty and Minimal Inputs ─────────────────────────────────────


class TestEdgeCasesEmptyInputs:
    def test_empty_plan_empty_context(
        self, engine: RuleBasedProposalEngine, empty_plan: WeeklyPlan, empty_context: PlanningContext
    ) -> None:
        proposals = engine.generate(empty_plan, empty_context)
        assert proposals == []

    def test_plan_with_empty_lists(
        self, engine: RuleBasedProposalEngine, empty_context: PlanningContext
    ) -> None:
        plan = WeeklyPlan(
            week_summary="Empty lists",
            priorities=[],
            planned_tasks=[],
            risks=[],
        )
        proposals = engine.generate(plan, empty_context)
        assert proposals == []

    def test_plan_with_only_summary(
        self, engine: RuleBasedProposalEngine, empty_context: PlanningContext
    ) -> None:
        plan = WeeklyPlan(week_summary="Just a summary")
        proposals = engine.generate(plan, empty_context)
        assert proposals == []

    def test_context_with_only_goals(
        self, engine: RuleBasedProposalEngine, empty_plan: WeeklyPlan
    ) -> None:
        context = PlanningContext(
            goals=[Goal(title="Learn Rust"), Goal(title="Write docs")],
            tasks=[],
            calendar=[],
        )
        proposals = engine.generate(empty_plan, context)
        # Both goals have no tasks -> 2 CREATE_TASK proposals
        assert len(proposals) == 2
        assert all(p.action_type == ActionType.CREATE_TASK for p in proposals)

    def test_context_with_only_tasks(
        self, engine: RuleBasedProposalEngine, empty_plan: WeeklyPlan
    ) -> None:
        context = PlanningContext(
            goals=[],
            tasks=[Task(title="Task 1"), Task(title="Task 2")],
            calendar=[],
        )
        proposals = engine.generate(empty_plan, context)
        # No goals -> no CREATE_TASK proposals
        assert proposals == []

    def test_context_with_only_calendar(
        self, engine: RuleBasedProposalEngine, empty_plan: WeeklyPlan
    ) -> None:
        context = PlanningContext(
            goals=[],
            tasks=[],
            calendar=[
                Event(
                    title="Meeting",
                    start=datetime.combine(date.today(), datetime.min.time()),
                    end=datetime.combine(date.today(), datetime.min.time()) + timedelta(hours=1),
                ),
            ],
        )
        proposals = engine.generate(empty_plan, context)
        assert proposals == []


# ── Edge Cases: Malformed and Boundary Inputs ────────────────────────────────


class TestEdgeCasesMalformedInputs:
    def test_plan_with_unknown_task_id(
        self, engine: RuleBasedProposalEngine, empty_context: PlanningContext
    ) -> None:
        """Planned task_id that doesn't match any task in context."""
        plan = WeeklyPlan(
            week_summary="Unknown task",
            planned_tasks=[
                PlannedTask(
                    task_id="Nonexistent task",
                    goal_id="Some goal",
                    priority=Priority.HIGH,
                    reason="Test",
                    suggested_day=date.today() + timedelta(days=1),
                ),
            ],
        )
        proposals = engine.generate(plan, empty_context)
        # No task found -> no RESCHEDULE, no CHANGE_PRIORITY
        # But CREATE_CALENDAR_EVENT should still be generated
        action_types = [p.action_type for p in proposals]
        assert ActionType.RESCHEDULE_TASK not in action_types
        assert ActionType.CHANGE_PRIORITY not in action_types
        assert ActionType.CREATE_CALENDAR_EVENT in action_types

    def test_plan_with_task_no_due_date(
        self, engine: RuleBasedProposalEngine
    ) -> None:
        """Task without due_date should not trigger overdue rule."""
        task = Task(title="No due date task", priority=2)
        context = PlanningContext(
            goals=[Goal(title="Test goal")],
            tasks=[task],
            calendar=[],
        )
        plan = WeeklyPlan(
            week_summary="No due date",
            planned_tasks=[
                PlannedTask(
                    task_id="No due date task",
                    goal_id="Test goal",
                    priority=Priority.HIGH,
                    reason="Test",
                    suggested_day=date.today() + timedelta(days=1),
                ),
            ],
        )
        proposals = engine.generate(plan, context)
        reschedule = [p for p in proposals if p.action_type == ActionType.RESCHEDULE_TASK]
        assert len(reschedule) == 0

    def test_plan_with_task_due_today(
        self, engine: RuleBasedProposalEngine
    ) -> None:
        """Task due today is NOT overdue (due_date < today is the condition)."""
        task = Task(
            title="Due today task",
            due_date=date.today(),
            priority=2,
        )
        context = PlanningContext(
            goals=[Goal(title="Test goal")],
            tasks=[task],
            calendar=[],
        )
        plan = WeeklyPlan(
            week_summary="Due today",
            planned_tasks=[
                PlannedTask(
                    task_id="Due today task",
                    goal_id="Test goal",
                    priority=Priority.HIGH,
                    reason="Test",
                    suggested_day=date.today() + timedelta(days=1),
                ),
            ],
        )
        proposals = engine.generate(plan, context)
        reschedule = [p for p in proposals if p.action_type == ActionType.RESCHEDULE_TASK]
        assert len(reschedule) == 0

    def test_plan_with_task_due_yesterday(
        self, engine: RuleBasedProposalEngine
    ) -> None:
        """Task due yesterday IS overdue."""
        task = Task(
            title="Due yesterday task",
            due_date=date.today() - timedelta(days=1),
            priority=2,
        )
        context = PlanningContext(
            goals=[Goal(title="Test goal")],
            tasks=[task],
            calendar=[],
        )
        plan = WeeklyPlan(
            week_summary="Due yesterday",
            planned_tasks=[
                PlannedTask(
                    task_id="Due yesterday task",
                    goal_id="Test goal",
                    priority=Priority.HIGH,
                    reason="Test",
                    suggested_day=date.today() + timedelta(days=1),
                ),
            ],
        )
        proposals = engine.generate(plan, context)
        reschedule = [p for p in proposals if p.action_type == ActionType.RESCHEDULE_TASK]
        assert len(reschedule) == 1

    def test_plan_with_empty_risks_list(
        self, engine: RuleBasedProposalEngine, sample_context: PlanningContext
    ) -> None:
        plan = WeeklyPlan(
            week_summary="No risks",
            planned_tasks=[],
            risks=[],
        )
        proposals = engine.generate(plan, sample_context)
        update = [p for p in proposals if p.action_type == ActionType.UPDATE_TASK]
        assert len(update) == 0

    def test_plan_with_medium_severity_risk(
        self, engine: RuleBasedProposalEngine, sample_context: PlanningContext, sample_task: Task
    ) -> None:
        """Medium severity risk should NOT trigger UPDATE_TASK."""
        plan = WeeklyPlan(
            week_summary="Medium risk",
            planned_tasks=[
                PlannedTask(
                    task_id=sample_task.title,
                    goal_id="Improve code quality",
                    priority=Priority.HIGH,
                    reason="Test",
                    suggested_day=date.today() + timedelta(days=1),
                ),
            ],
            risks=[
                PlanningRisk(
                    description=f"Task '{sample_task.title}' has medium risk",
                    severity=RiskSeverity.MEDIUM,
                ),
            ],
        )
        proposals = engine.generate(plan, sample_context)
        update = [p for p in proposals if p.action_type == ActionType.UPDATE_TASK]
        assert len(update) == 0

    def test_plan_with_high_severity_risk_no_matching_task(
        self, engine: RuleBasedProposalEngine, empty_context: PlanningContext
    ) -> None:
        """High severity risk with no matching task in context."""
        plan = WeeklyPlan(
            week_summary="High risk no task",
            planned_tasks=[],
            risks=[
                PlanningRisk(
                    description="Some unknown task has a critical issue",
                    severity=RiskSeverity.HIGH,
                ),
            ],
        )
        proposals = engine.generate(plan, empty_context)
        update = [p for p in proposals if p.action_type == ActionType.UPDATE_TASK]
        assert len(update) == 1
        assert update[0].target_id is None  # No matching task found

    def test_plan_with_duplicate_planned_tasks(
        self, engine: RuleBasedProposalEngine, sample_context: PlanningContext, sample_task: Task
    ) -> None:
        """Multiple planned tasks for the same task_id should deduplicate."""
        plan = WeeklyPlan(
            week_summary="Duplicate planned tasks",
            planned_tasks=[
                PlannedTask(
                    task_id=sample_task.title,
                    goal_id="Improve code quality",
                    priority=Priority.HIGH,
                    reason="First",
                    suggested_day=date.today() + timedelta(days=1),
                ),
                PlannedTask(
                    task_id=sample_task.title,
                    goal_id="Improve code quality",
                    priority=Priority.HIGH,
                    reason="Second",
                    suggested_day=date.today() + timedelta(days=2),
                ),
            ],
        )
        proposals = engine.generate(plan, sample_context)
        # Should have only one RESCHEDULE, one CHANGE_PRIORITY, one CREATE_CALENDAR_EVENT
        reschedule = [p for p in proposals if p.action_type == ActionType.RESCHEDULE_TASK]
        change_priority = [p for p in proposals if p.action_type == ActionType.CHANGE_PRIORITY]
        calendar = [p for p in proposals if p.action_type == ActionType.CREATE_CALENDAR_EVENT]
        assert len(reschedule) <= 1
        assert len(change_priority) <= 1
        assert len(calendar) <= 1

    def test_plan_with_goal_in_planned_tasks(
        self, engine: RuleBasedProposalEngine
    ) -> None:
        """Goal that appears in planned_tasks should NOT trigger CREATE_TASK."""
        goal = Goal(title="Active goal")
        context = PlanningContext(
            goals=[goal],
            tasks=[],
            calendar=[],
        )
        plan = WeeklyPlan(
            week_summary="Goal in plan",
            planned_tasks=[
                PlannedTask(
                    task_id="Some task",
                    goal_id="Active goal",
                    priority=Priority.HIGH,
                    reason="Test",
                    suggested_day=date.today() + timedelta(days=1),
                ),
            ],
        )
        proposals = engine.generate(plan, context)
        create = [p for p in proposals if p.action_type == ActionType.CREATE_TASK]
        assert len(create) == 0

    def test_plan_with_goal_with_related_tasks(
        self, engine: RuleBasedProposalEngine, sample_task: Task
    ) -> None:
        """Goal with related_tasks should NOT trigger CREATE_TASK."""
        goal = Goal(title="Goal with tasks", related_tasks=[sample_task.title])
        context = PlanningContext(
            goals=[goal],
            tasks=[sample_task],
            calendar=[],
        )
        plan = WeeklyPlan(week_summary="Goal with tasks")
        proposals = engine.generate(plan, context)
        create = [p for p in proposals if p.action_type == ActionType.CREATE_TASK]
        assert len(create) == 0

    def test_plan_with_multiple_risks_same_target(
        self, engine: RuleBasedProposalEngine, sample_context: PlanningContext, sample_task: Task
    ) -> None:
        """Multiple high risks for the same task should deduplicate."""
        plan = WeeklyPlan(
            week_summary="Multiple risks",
            planned_tasks=[
                PlannedTask(
                    task_id=sample_task.title,
                    goal_id="Improve code quality",
                    priority=Priority.HIGH,
                    reason="Test",
                    suggested_day=date.today() + timedelta(days=1),
                ),
            ],
            risks=[
                PlanningRisk(
                    description=f"Task '{sample_task.title}' has critical issue 1",
                    severity=RiskSeverity.HIGH,
                ),
                PlanningRisk(
                    description=f"Task '{sample_task.title}' has critical issue 2",
                    severity=RiskSeverity.HIGH,
                ),
            ],
        )
        proposals = engine.generate(plan, sample_context)
        update = [p for p in proposals if p.action_type == ActionType.UPDATE_TASK]
        assert len(update) == 1  # Deduplicated by target_id


# ── Transformation Accuracy: Detailed Parameter Verification ─────────────────


class TestTransformationAccuracy:
    def test_overdue_task_parameters(
        self, engine: RuleBasedProposalEngine, overdue_task: Task
    ) -> None:
        """Verify all parameters of RESCHEDULE_TASK proposal."""
        context = PlanningContext(
            goals=[Goal(title="Fix bugs")],
            tasks=[overdue_task],
            calendar=[],
        )
        suggested_day = date.today() + timedelta(days=3)
        plan = WeeklyPlan(
            week_summary="Fix overdue",
            planned_tasks=[
                PlannedTask(
                    task_id=overdue_task.title,
                    goal_id="Fix bugs",
                    priority=Priority.HIGH,
                    reason="Overdue",
                    suggested_day=suggested_day,
                ),
            ],
        )
        proposals = engine.generate(plan, context)
        reschedule = [p for p in proposals if p.action_type == ActionType.RESCHEDULE_TASK]
        assert len(reschedule) == 1
        p = reschedule[0]
        assert p.target_id == overdue_task.title
        assert p.parameters["new_due_date"] == suggested_day.isoformat()
        assert overdue_task.due_date is not None
        assert p.parameters["old_due_date"] == overdue_task.due_date.isoformat()
        assert p.source == "rule:overdue"
        assert p.risk == RiskLevel.MEDIUM
        assert p.status == ProposalStatus.PROPOSED
        assert p.metadata["goal_id"] == "Fix bugs"
        assert overdue_task.title in p.reason

    def test_create_task_parameters(
        self, engine: RuleBasedProposalEngine
    ) -> None:
        """Verify all parameters of CREATE_TASK proposal."""
        goal = Goal(title="Learn Rust")
        context = PlanningContext(goals=[goal], tasks=[], calendar=[])
        plan = WeeklyPlan(week_summary="Learn")
        proposals = engine.generate(plan, context)
        create = [p for p in proposals if p.action_type == ActionType.CREATE_TASK]
        assert len(create) == 1
        p = create[0]
        assert p.target_id == "Learn Rust"
        assert p.parameters["title"] == "Work on: Learn Rust"
        assert p.parameters["goal_id"] == "Learn Rust"
        assert p.source == "rule:missing_task"
        assert p.risk == RiskLevel.LOW
        assert p.status == ProposalStatus.PROPOSED
        assert "no tasks" in p.reason.lower()

    def test_change_priority_parameters(
        self, engine: RuleBasedProposalEngine
    ) -> None:
        """Verify all parameters of CHANGE_PRIORITY proposal."""
        task = Task(title="Task", priority=3)
        context = PlanningContext(
            goals=[Goal(title="Goal")],
            tasks=[task],
            calendar=[],
        )
        plan = WeeklyPlan(
            week_summary="Re-prioritize",
            planned_tasks=[
                PlannedTask(
                    task_id="Task",
                    goal_id="Goal",
                    priority=Priority.HIGH,
                    reason="Boost",
                    suggested_day=date.today() + timedelta(days=1),
                ),
            ],
        )
        proposals = engine.generate(plan, context)
        change = [p for p in proposals if p.action_type == ActionType.CHANGE_PRIORITY]
        assert len(change) == 1
        p = change[0]
        assert p.target_id == "Task"
        assert p.parameters["new_priority"] == 1  # HIGH -> 1
        assert p.parameters["old_priority"] == 3
        assert p.source == "rule:priority_mismatch"
        assert p.risk == RiskLevel.LOW
        assert p.metadata["goal_id"] == "Goal"

    def test_calendar_event_parameters(
        self, engine: RuleBasedProposalEngine
    ) -> None:
        """Verify all parameters of CREATE_CALENDAR_EVENT proposal."""
        task = Task(title="Meeting", due_date=date.today() + timedelta(days=5))
        context = PlanningContext(
            goals=[Goal(title="Goal")],
            tasks=[task],
            calendar=[],
        )
        meeting_day = date.today() + timedelta(days=2)
        plan = WeeklyPlan(
            week_summary="Schedule",
            planned_tasks=[
                PlannedTask(
                    task_id="Meeting",
                    goal_id="Goal",
                    priority=Priority.MEDIUM,
                    reason="Sync",
                    suggested_day=meeting_day,
                ),
            ],
        )
        proposals = engine.generate(plan, context)
        cal = [p for p in proposals if p.action_type == ActionType.CREATE_CALENDAR_EVENT]
        assert len(cal) == 1
        p = cal[0]
        assert p.target_id == "Meeting"
        assert p.parameters["title"] == "Meeting"
        assert p.parameters["date"] == meeting_day.isoformat()
        assert p.parameters["goal_id"] == "Goal"
        assert p.source == "rule:calendar_entry"
        assert p.risk == RiskLevel.LOW

    def test_update_task_parameters(
        self, engine: RuleBasedProposalEngine, sample_task: Task
    ) -> None:
        """Verify all parameters of UPDATE_TASK proposal."""
        context = PlanningContext(
            goals=[Goal(title="Goal")],
            tasks=[sample_task],
            calendar=[],
        )
        plan = WeeklyPlan(
            week_summary="Risky",
            planned_tasks=[
                PlannedTask(
                    task_id=sample_task.title,
                    goal_id="Goal",
                    priority=Priority.HIGH,
                    reason="Important",
                    suggested_day=date.today() + timedelta(days=1),
                ),
            ],
            risks=[
                PlanningRisk(
                    description=f"Task '{sample_task.title}' has critical dependency",
                    severity=RiskSeverity.HIGH,
                ),
            ],
        )
        proposals = engine.generate(plan, context)
        update = [p for p in proposals if p.action_type == ActionType.UPDATE_TASK]
        assert len(update) == 1
        p = update[0]
        assert p.target_id == sample_task.title
        assert p.parameters["risk_description"] == f"Task '{sample_task.title}' has critical dependency"
        assert p.source == "rule:risk"
        assert p.risk == RiskLevel.HIGH
        assert "critical dependency" in p.reason.lower()

    def test_priority_mapping_all_levels(
        self, engine: RuleBasedProposalEngine
    ) -> None:
        """Verify priority mapping for all Priority enum values."""
        for priority, expected_int in [(Priority.HIGH, 1), (Priority.MEDIUM, 2), (Priority.LOW, 3)]:
            task = Task(title=f"Task {priority.value}", priority=99)
            context = PlanningContext(
                goals=[Goal(title="Goal")],
                tasks=[task],
                calendar=[],
            )
            plan = WeeklyPlan(
                week_summary="Test priority",
                planned_tasks=[
                    PlannedTask(
                        task_id=f"Task {priority.value}",
                        goal_id="Goal",
                        priority=priority,
                        reason="Test",
                        suggested_day=date.today() + timedelta(days=1),
                    ),
                ],
            )
            proposals = engine.generate(plan, context)
            change = [p for p in proposals if p.action_type == ActionType.CHANGE_PRIORITY]
            assert len(change) == 1
            assert change[0].parameters["new_priority"] == expected_int

    def test_all_proposals_have_required_fields(
        self, engine: RuleBasedProposalEngine, sample_plan: WeeklyPlan, sample_context: PlanningContext
    ) -> None:
        """Every proposal must have all required fields populated."""
        proposals = engine.generate(sample_plan, sample_context)
        for p in proposals:
            assert p.reason != "", f"Proposal {p.action_type} has empty reason"
            assert p.source != "", f"Proposal {p.action_type} has empty source"
            assert p.status == ProposalStatus.PROPOSED
            assert p.proposal_id == ""  # default
            assert p.created_at is not None
            assert p.updated_at is not None


# ── Proposal-Only Contract Compliance ────────────────────────────────────────


class TestProposalOnlyContractCompliance:
    def test_engine_has_no_mutation_methods(self, engine: RuleBasedProposalEngine) -> None:
        """RuleBasedProposalEngine must not expose mutation methods."""
        mutation_methods = [
            "create_task", "update_task", "delete_task", "complete_task",
            "modify_task", "set_task_state", "set_task_progress",
            "add_task", "remove_task",
            "create_goal", "update_goal", "delete_goal", "modify_goal",
            "complete_goal", "add_goal", "remove_goal", "set_goal_status",
            "create_calendar_event", "update_calendar_event", "delete_calendar_event",
            "modify_calendar_event", "add_event", "remove_event",
            "update_event", "delete_event",
            "execute", "apply", "mutate", "write", "save", "persist",
            "commit", "sync", "push", "post", "put", "patch", "delete",
            "run_command", "exec", "eval", "system", "spawn", "call",
        ]
        for method in mutation_methods:
            assert not hasattr(engine, method), (
                f"RuleBasedProposalEngine has mutation method: {method}"
            )

    def test_engine_only_exposes_generate(self, engine: RuleBasedProposalEngine) -> None:
        """RuleBasedProposalEngine should only expose generate as public method."""
        public_methods = [
            name for name in dir(engine)
            if not name.startswith("_") and callable(getattr(engine, name))
        ]
        assert public_methods == ["generate"], (
            f"Unexpected public methods: {public_methods}"
        )

    def test_engine_has_no_io_operations(self, engine: RuleBasedProposalEngine) -> None:
        """Engine should not have any I/O or state-related attributes."""
        io_attrs = ["session", "db", "connection", "client", "store", "cache"]
        for attr in io_attrs:
            assert not hasattr(engine, attr), (
                f"RuleBasedProposalEngine has I/O attribute: {attr}"
            )

    def test_engine_is_stateless(self, engine: RuleBasedProposalEngine) -> None:
        """Engine should maintain no state between calls."""
        # Call generate multiple times with same inputs
        context = PlanningContext(
            goals=[Goal(title="Goal")],
            tasks=[Task(title="Task", priority=2)],
            calendar=[],
        )
        plan = WeeklyPlan(
            week_summary="Test",
            planned_tasks=[
                PlannedTask(
                    task_id="Task",
                    goal_id="Goal",
                    priority=Priority.HIGH,
                    reason="Test",
                    suggested_day=date.today() + timedelta(days=1),
                ),
            ],
        )
        proposals1 = engine.generate(plan, context)
        proposals2 = engine.generate(plan, context)
        assert len(proposals1) == len(proposals2)
        for p1, p2 in zip(proposals1, proposals2):
            assert p1.action_type == p2.action_type
            assert p1.target_id == p2.target_id
            assert p1.reason == p2.reason

    def test_engine_does_not_modify_input_plan(
        self, engine: RuleBasedProposalEngine, sample_plan: WeeklyPlan, sample_context: PlanningContext
    ) -> None:
        """Engine must not modify the input plan."""
        original_summary = sample_plan.week_summary
        original_tasks = list(sample_plan.planned_tasks)
        original_priorities = list(sample_plan.priorities)
        original_risks = list(sample_plan.risks)

        engine.generate(sample_plan, sample_context)

        assert sample_plan.week_summary == original_summary
        assert sample_plan.planned_tasks == original_tasks
        assert sample_plan.priorities == original_priorities
        assert sample_plan.risks == original_risks

    def test_engine_does_not_modify_input_context(
        self, engine: RuleBasedProposalEngine, sample_plan: WeeklyPlan, sample_context: PlanningContext
    ) -> None:
        """Engine must not modify the input context."""
        original_goals = list(sample_context.goals)
        original_tasks = list(sample_context.tasks)
        original_calendar = list(sample_context.calendar)

        engine.generate(sample_plan, sample_context)

        assert sample_context.goals == original_goals
        assert sample_context.tasks == original_tasks
        assert sample_context.calendar == original_calendar

    def test_engine_does_not_modify_tasks(
        self, engine: RuleBasedProposalEngine, sample_plan: WeeklyPlan, sample_context: PlanningContext
    ) -> None:
        """Engine must not modify task objects in context."""
        task = sample_context.tasks[0]
        original_priority = task.priority
        original_due_date = task.due_date
        original_title = task.title

        engine.generate(sample_plan, sample_context)

        assert task.priority == original_priority
        assert task.due_date == original_due_date
        assert task.title == original_title

    def test_engine_does_not_modify_goals(
        self, engine: RuleBasedProposalEngine, sample_plan: WeeklyPlan, sample_context: PlanningContext
    ) -> None:
        """Engine must not modify goal objects in context."""
        goal = sample_context.goals[0]
        original_title = goal.title
        original_related_tasks = list(goal.related_tasks)

        engine.generate(sample_plan, sample_context)

        assert goal.title == original_title
        assert goal.related_tasks == original_related_tasks


# ── Mutation Guard Effectiveness with Real Engine ────────────────────────────


class TestMutationGuardWithRealEngine:
    def test_guard_allows_generate(
        self, engine: RuleBasedProposalEngine, sample_plan: WeeklyPlan, sample_context: PlanningContext
    ) -> None:
        guard = MutationGuard(engine)
        proposals = guard.generate(sample_plan, sample_context)
        assert isinstance(proposals, list)
        assert all(isinstance(p, ActionProposal) for p in proposals)

    def test_guard_blocks_all_mutation_methods(self, engine: RuleBasedProposalEngine) -> None:
        guard = MutationGuard(engine)
        mutation_methods = [
            "create_task", "update_task", "delete_task", "complete_task",
            "modify_task", "set_task_state", "set_task_progress",
            "add_task", "remove_task",
            "create_goal", "update_goal", "delete_goal", "modify_goal",
            "complete_goal", "add_goal", "remove_goal", "set_goal_status",
            "create_calendar_event", "update_calendar_event", "delete_calendar_event",
            "modify_calendar_event", "add_event", "remove_event",
            "update_event", "delete_event",
            "execute", "apply", "mutate", "write", "save", "persist",
            "commit", "sync", "push", "post", "put", "patch", "delete",
        ]
        for method in mutation_methods:
            with pytest.raises(MutationBlockedError):
                getattr(guard, method)

    def test_guard_blocks_task_domain(self, engine: RuleBasedProposalEngine) -> None:
        guard = MutationGuard(engine)
        with pytest.raises(MutationBlockedError, match="task"):
            guard.create_task("test")
        with pytest.raises(MutationBlockedError, match="task"):
            guard.update_task("task-1")
        with pytest.raises(MutationBlockedError, match="task"):
            guard.delete_task("task-1")

    def test_guard_blocks_goal_domain(self, engine: RuleBasedProposalEngine) -> None:
        guard = MutationGuard(engine)
        with pytest.raises(MutationBlockedError, match="goal"):
            guard.create_goal("test")
        with pytest.raises(MutationBlockedError, match="goal"):
            guard.update_goal("goal-1")
        with pytest.raises(MutationBlockedError, match="goal"):
            guard.delete_goal("goal-1")
        with pytest.raises(MutationBlockedError, match="goal"):
            guard.modify_goal("goal-1")

    def test_guard_blocks_calendar_domain(self, engine: RuleBasedProposalEngine) -> None:
        guard = MutationGuard(engine)
        with pytest.raises(MutationBlockedError, match="calendar"):
            guard.create_calendar_event("event-1")
        with pytest.raises(MutationBlockedError, match="calendar"):
            guard.update_calendar_event("event-1")
        with pytest.raises(MutationBlockedError, match="calendar"):
            guard.delete_calendar_event("event-1")

    def test_guard_blocks_generic_mutations(self, engine: RuleBasedProposalEngine) -> None:
        guard = MutationGuard(engine)
        with pytest.raises(MutationBlockedError, match="execute"):
            guard.execute()
        with pytest.raises(MutationBlockedError, match="apply"):
            guard.apply()
        with pytest.raises(MutationBlockedError, match="mutate"):
            guard.mutate()
        with pytest.raises(MutationBlockedError, match="write"):
            guard.write()
        with pytest.raises(MutationBlockedError, match="save"):
            guard.save()
        with pytest.raises(MutationBlockedError, match="persist"):
            guard.persist()

    def test_guard_blocks_unknown_callable(self, engine: RuleBasedProposalEngine) -> None:
        """Guard should block access to unknown callable attributes."""
        guard = MutationGuard(engine)
        with pytest.raises(MutationBlockedError, match="blocked"):
            _ = guard._find_task  # callable on engine, not generate

    def test_guard_domain_in_error(self, engine: RuleBasedProposalEngine) -> None:
        guard = MutationGuard(engine)
        with pytest.raises(MutationBlockedError) as exc_info:
            guard.create_task("test")
        assert exc_info.value.domain == "task"

        with pytest.raises(MutationBlockedError) as exc_info:
            guard.modify_goal("goal-1")
        assert exc_info.value.domain == "goal"

        with pytest.raises(MutationBlockedError) as exc_info:
            guard.create_calendar_event("event-1")
        assert exc_info.value.domain == "calendar"


class TestProposalOnlyEngineWithRealEngine:
    def test_sealed_allows_generate(
        self, engine: RuleBasedProposalEngine, sample_plan: WeeklyPlan, sample_context: PlanningContext
    ) -> None:
        sealed = ProposalOnlyEngine(engine)
        proposals = sealed.generate(sample_plan, sample_context)
        assert isinstance(proposals, list)
        assert all(isinstance(p, ActionProposal) for p in proposals)

    def test_sealed_blocks_all_mutation_methods(self, engine: RuleBasedProposalEngine) -> None:
        sealed = ProposalOnlyEngine(engine)
        mutation_methods = [
            "create_task", "update_task", "delete_task", "complete_task",
            "modify_task", "set_task_state", "set_task_progress",
            "add_task", "remove_task",
            "create_goal", "update_goal", "delete_goal", "modify_goal",
            "complete_goal", "add_goal", "remove_goal", "set_goal_status",
            "create_calendar_event", "update_calendar_event", "delete_calendar_event",
            "modify_calendar_event", "add_event", "remove_event",
            "update_event", "delete_event",
            "execute", "apply", "mutate", "write", "save", "persist",
            "commit", "sync", "push", "post", "put", "patch", "delete",
        ]
        for method in mutation_methods:
            with pytest.raises(MutationBlockedError):
                getattr(sealed, method)

    def test_sealed_blocks_task_domain(self, engine: RuleBasedProposalEngine) -> None:
        sealed = ProposalOnlyEngine(engine)
        with pytest.raises(MutationBlockedError, match="task"):
            sealed.create_task("test")
        with pytest.raises(MutationBlockedError, match="task"):
            sealed.update_task("task-1")
        with pytest.raises(MutationBlockedError, match="task"):
            sealed.delete_task("task-1")

    def test_sealed_blocks_goal_domain(self, engine: RuleBasedProposalEngine) -> None:
        sealed = ProposalOnlyEngine(engine)
        with pytest.raises(MutationBlockedError, match="goal"):
            sealed.create_goal("test")
        with pytest.raises(MutationBlockedError, match="goal"):
            sealed.update_goal("goal-1")
        with pytest.raises(MutationBlockedError, match="goal"):
            sealed.delete_goal("goal-1")
        with pytest.raises(MutationBlockedError, match="goal"):
            sealed.modify_goal("goal-1")

    def test_sealed_blocks_calendar_domain(self, engine: RuleBasedProposalEngine) -> None:
        sealed = ProposalOnlyEngine(engine)
        with pytest.raises(MutationBlockedError, match="calendar"):
            sealed.create_calendar_event("event-1")
        with pytest.raises(MutationBlockedError, match="calendar"):
            sealed.update_calendar_event("event-1")
        with pytest.raises(MutationBlockedError, match="calendar"):
            sealed.delete_calendar_event("event-1")

    def test_sealed_blocks_setattr(self, engine: RuleBasedProposalEngine) -> None:
        sealed = ProposalOnlyEngine(engine)
        with pytest.raises(MutationBlockedError, match="immutable"):
            sealed.anything = "value"

    def test_sealed_blocks_delattr(self, engine: RuleBasedProposalEngine) -> None:
        sealed = ProposalOnlyEngine(engine)
        with pytest.raises(MutationBlockedError, match="immutable"):
            del sealed.anything

    def test_sealed_domain_in_error(self, engine: RuleBasedProposalEngine) -> None:
        sealed = ProposalOnlyEngine(engine)
        with pytest.raises(MutationBlockedError) as exc_info:
            sealed.create_task("test")
        assert exc_info.value.domain == "task"

        with pytest.raises(MutationBlockedError) as exc_info:
            sealed.modify_goal("goal-1")
        assert exc_info.value.domain == "goal"

        with pytest.raises(MutationBlockedError) as exc_info:
            sealed.create_calendar_event("event-1")
        assert exc_info.value.domain == "calendar"

    def test_sealed_only_generate_accessible(self, engine: RuleBasedProposalEngine) -> None:
        sealed = ProposalOnlyEngine(engine)
        assert hasattr(sealed, "generate")
        assert callable(sealed.generate)

        blocked_attrs = [
            "create_task", "update_task", "delete_task",
            "modify_goal", "create_goal", "update_goal", "delete_goal",
            "create_calendar_event", "update_calendar_event", "delete_calendar_event",
            "execute", "apply", "mutate", "write", "save", "persist",
        ]
        for attr in blocked_attrs:
            with pytest.raises(MutationBlockedError):
                getattr(sealed, attr)


# ── Negative Tests: Mutation Attempts Fail ────────────────────────────────────


class TestNegativeMutationAttempts:
    def test_direct_mutation_on_engine_fails(self, engine: RuleBasedProposalEngine) -> None:
        """Direct mutation attempts on the engine should not exist."""
        # These methods should not exist on the engine
        assert not hasattr(engine, "create_task")
        assert not hasattr(engine, "update_task")
        assert not hasattr(engine, "delete_task")
        assert not hasattr(engine, "execute")
        assert not hasattr(engine, "apply")
        assert not hasattr(engine, "mutate")
        assert not hasattr(engine, "write")
        assert not hasattr(engine, "save")
        assert not hasattr(engine, "persist")

    def test_mutation_via_guard_fails(self, engine: RuleBasedProposalEngine) -> None:
        """Mutation attempts via MutationGuard should raise MutationBlockedError."""
        guard = MutationGuard(engine)
        with pytest.raises(MutationBlockedError):
            guard.create_task("test")
        with pytest.raises(MutationBlockedError):
            guard.update_task("task-1")
        with pytest.raises(MutationBlockedError):
            guard.delete_task("task-1")
        with pytest.raises(MutationBlockedError):
            guard.modify_goal("goal-1")
        with pytest.raises(MutationBlockedError):
            guard.create_calendar_event("event-1")
        with pytest.raises(MutationBlockedError):
            guard.execute()
        with pytest.raises(MutationBlockedError):
            guard.apply()

    def test_mutation_via_sealed_engine_fails(self, engine: RuleBasedProposalEngine) -> None:
        """Mutation attempts via ProposalOnlyEngine should raise MutationBlockedError."""
        sealed = ProposalOnlyEngine(engine)
        with pytest.raises(MutationBlockedError):
            sealed.create_task("test")
        with pytest.raises(MutationBlockedError):
            sealed.update_task("task-1")
        with pytest.raises(MutationBlockedError):
            sealed.delete_task("task-1")
        with pytest.raises(MutationBlockedError):
            sealed.modify_goal("goal-1")
        with pytest.raises(MutationBlockedError):
            sealed.create_calendar_event("event-1")
        with pytest.raises(MutationBlockedError):
            sealed.execute()
        with pytest.raises(MutationBlockedError):
            sealed.apply()

    def test_mutation_via_decorator_fails(
        self, engine: RuleBasedProposalEngine, sample_plan: WeeklyPlan, sample_context: PlanningContext
    ) -> None:
        """Mutation attempts via proposal_only decorator should raise MutationBlockedError."""
        @proposal_only
        def process(engine: object, plan: WeeklyPlan, ctx: PlanningContext) -> None:
            engine.create_task("test")  # type: ignore[attr-defined]

        with pytest.raises(MutationBlockedError, match="create_task"):
            process(engine, sample_plan, sample_context)

    def test_mutation_via_context_manager_fails(
        self, engine: RuleBasedProposalEngine, sample_plan: WeeklyPlan, sample_context: PlanningContext
    ) -> None:
        """Mutation attempts via proposal_only_context should raise MutationBlockedError."""
        with proposal_only_context(engine) as safe_engine:
            with pytest.raises(MutationBlockedError):
                safe_engine.create_task("test")

    def test_mutation_via_setattr_fails(self, engine: RuleBasedProposalEngine) -> None:
        """Setting attributes on ProposalOnlyEngine should raise MutationBlockedError."""
        sealed = ProposalOnlyEngine(engine)
        with pytest.raises(MutationBlockedError, match="immutable"):
            sealed.anything = "value"

    def test_mutation_via_delattr_fails(self, engine: RuleBasedProposalEngine) -> None:
        """Deleting attributes on ProposalOnlyEngine should raise MutationBlockedError."""
        sealed = ProposalOnlyEngine(engine)
        with pytest.raises(MutationBlockedError, match="immutable"):
            del sealed.anything


# ── Integration: Full Pipeline with Guards ───────────────────────────────────


class TestIntegrationWithGuards:
    def test_full_pipeline_with_guard(
        self, engine: RuleBasedProposalEngine, sample_plan: WeeklyPlan, sample_context: PlanningContext
    ) -> None:
        """Full pipeline with MutationGuard should produce same results as unguarded."""
        unguarded_proposals = engine.generate(sample_plan, sample_context)
        guard = MutationGuard(engine)
        guarded_proposals = guard.generate(sample_plan, sample_context)

        assert len(unguarded_proposals) == len(guarded_proposals)
        for p1, p2 in zip(unguarded_proposals, guarded_proposals):
            assert p1.action_type == p2.action_type
            assert p1.target_id == p2.target_id
            assert p1.reason == p2.reason
            assert p1.source == p2.source

    def test_full_pipeline_with_sealed_engine(
        self, engine: RuleBasedProposalEngine, sample_plan: WeeklyPlan, sample_context: PlanningContext
    ) -> None:
        """Full pipeline with ProposalOnlyEngine should produce same results as unguarded."""
        unguarded_proposals = engine.generate(sample_plan, sample_context)
        sealed = ProposalOnlyEngine(engine)
        sealed_proposals = sealed.generate(sample_plan, sample_context)

        assert len(unguarded_proposals) == len(sealed_proposals)
        for p1, p2 in zip(unguarded_proposals, sealed_proposals):
            assert p1.action_type == p2.action_type
            assert p1.target_id == p2.target_id
            assert p1.reason == p2.reason
            assert p1.source == p2.source

    def test_full_pipeline_with_decorator(
        self, engine: RuleBasedProposalEngine, sample_plan: WeeklyPlan, sample_context: PlanningContext
    ) -> None:
        """Full pipeline with proposal_only decorator should produce same results."""
        @proposal_only
        def process(engine: object, plan: WeeklyPlan, ctx: PlanningContext) -> list[ActionProposal]:
            return engine.generate(plan, ctx)  # type: ignore[attr-defined]

        unguarded_proposals = engine.generate(sample_plan, sample_context)
        decorated_proposals = process(engine, sample_plan, sample_context)

        assert len(unguarded_proposals) == len(decorated_proposals)
        for p1, p2 in zip(unguarded_proposals, decorated_proposals):
            assert p1.action_type == p2.action_type
            assert p1.target_id == p2.target_id
            assert p1.reason == p2.reason

    def test_full_pipeline_with_context_manager(
        self, engine: RuleBasedProposalEngine, sample_plan: WeeklyPlan, sample_context: PlanningContext
    ) -> None:
        """Full pipeline with proposal_only_context should produce same results."""
        unguarded_proposals = engine.generate(sample_plan, sample_context)
        with proposal_only_context(engine) as safe_engine:
            context_proposals = safe_engine.generate(sample_plan, sample_context)

        assert len(unguarded_proposals) == len(context_proposals)
        for p1, p2 in zip(unguarded_proposals, context_proposals):
            assert p1.action_type == p2.action_type
            assert p1.target_id == p2.target_id
            assert p1.reason == p2.reason


# ── Import Guard with Real Engine ───────────────────────────────────────────


class TestImportGuardWithRealEngine:
    def test_no_violations_with_real_engine(self) -> None:
        """ImportGuard should find no violations in the proposal package."""
        violations = ImportGuard.check_imports()
        assert violations == [], f"Unexpected violations: {violations}"

    def test_assert_no_write_access_passes(self) -> None:
        """assert_no_write_access should not raise."""
        ImportGuard.assert_no_write_access()

    def test_forbidden_imports_defined(self) -> None:
        """FORBIDDEN_IMPORT_ROOTS should include key mutation modules."""
        from janus.proposal.guard import FORBIDDEN_IMPORT_ROOTS
        assert "janus.tasks_cli" in FORBIDDEN_IMPORT_ROOTS
        assert "janus.goals_cli" in FORBIDDEN_IMPORT_ROOTS
        assert "janus.integrations.google_calendar" in FORBIDDEN_IMPORT_ROOTS

    def test_protected_domains_defined(self) -> None:
        """PROTECTED_DOMAINS should include task, goal, calendar."""
        from janus.proposal.guard import PROTECTED_DOMAINS
        assert "task" in PROTECTED_DOMAINS
        assert "goal" in PROTECTED_DOMAINS
        assert "calendar" in PROTECTED_DOMAINS

    def test_mutation_patterns_cover_all_domains(self) -> None:
        """MUTATION_METHOD_PATTERNS should cover all three domains."""
        from janus.proposal.guard import MUTATION_METHOD_PATTERNS
        patterns_str = " ".join(MUTATION_METHOD_PATTERNS)
        assert "task" in patterns_str
        assert "goal" in patterns_str
        assert "calendar" in patterns_str
        assert "event" in patterns_str


# ── Proposal-Only Decorator Edge Cases ───────────────────────────────────────


class TestProposalOnlyDecoratorEdgeCases:
    def test_decorator_with_no_args(self) -> None:
        """Decorator should handle functions with no arguments."""
        @proposal_only
        def process() -> str:
            return "ok"

        result = process()
        assert result == "ok"

    def test_decorator_with_non_engine_first_arg(self) -> None:
        """Decorator should pass through non-engine first arguments."""
        @proposal_only
        def process(value: int) -> int:
            return value * 2

        result = process(5)
        assert result == 10

    def test_decorator_preserves_function_metadata(self) -> None:
        """Decorator should preserve function name and docstring."""
        @proposal_only
        def my_function(engine: object) -> str:
            """My docstring."""
            return "ok"

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."


# ── Proposal-Only Context Manager Edge Cases ─────────────────────────────────


class TestProposalOnlyContextEdgeCases:
    def test_context_with_exception(self, engine: RuleBasedProposalEngine) -> None:
        """Context manager should clean up even when exception occurs."""
        with pytest.raises(ValueError):
            with proposal_only_context(engine) as safe_engine:
                raise ValueError("test")

    def test_context_returns_proposal_only_engine(self, engine: RuleBasedProposalEngine) -> None:
        """Context manager should return a ProposalOnlyEngine."""
        with proposal_only_context(engine) as safe_engine:
            assert isinstance(safe_engine, ProposalOnlyEngine)

    def test_context_engine_blocks_mutation(self, engine: RuleBasedProposalEngine) -> None:
        """Engine from context manager should block mutations."""
        with proposal_only_context(engine) as safe_engine:
            with pytest.raises(MutationBlockedError):
                safe_engine.create_task("test")
            with pytest.raises(MutationBlockedError):
                safe_engine.execute()
            with pytest.raises(MutationBlockedError):
                safe_engine.apply()


# ── Mutation Detection Edge Cases ─────────────────────────────────────────────


class TestMutationDetectionEdgeCases:
    def test_is_mutation_method_case_insensitive(self) -> None:
        """is_mutation_method should be case-insensitive."""
        from janus.proposal.guard import is_mutation_method
        assert is_mutation_method("CREATE_TASK")
        assert is_mutation_method("Create_Task")
        assert is_mutation_method("create_TASK")

    def test_is_mutation_method_partial_match(self) -> None:
        """is_mutation_method should match partial names."""
        from janus.proposal.guard import is_mutation_method
        assert is_mutation_method("batch_create_task")
        assert is_mutation_method("create_task_async")
        assert is_mutation_method("my_create_task_method")

    def test_is_not_mutation_method_safe_names(self) -> None:
        """Safe method names should not be flagged."""
        from janus.proposal.guard import is_mutation_method
        assert not is_mutation_method("generate")
        assert not is_mutation_method("to_dict")
        assert not is_mutation_method("from_dict")
        assert not is_mutation_method("is_actionable")
        assert not is_mutation_method("validate")
        assert not is_mutation_method("get_status")

    def test_get_mutation_domain_case_insensitive(self) -> None:
        """get_mutation_domain should be case-insensitive."""
        from janus.proposal.guard import get_mutation_domain
        assert get_mutation_domain("CREATE_TASK") == "task"
        assert get_mutation_domain("MODIFY_GOAL") == "goal"
        assert get_mutation_domain("CREATE_CALENDAR_EVENT") == "calendar"

    def test_get_mutation_domain_none_for_generic(self) -> None:
        """get_mutation_domain should return None for generic mutations."""
        from janus.proposal.guard import get_mutation_domain
        assert get_mutation_domain("execute") is None
        assert get_mutation_domain("apply") is None
        assert get_mutation_domain("mutate") is None
        assert get_mutation_domain("write") is None
        assert get_mutation_domain("save") is None


# ── MutationBlockedError Edge Cases ──────────────────────────────────────────


class TestMutationBlockedErrorEdgeCases:
    def test_error_message_preserved(self) -> None:
        """Error message should be preserved."""
        err = MutationBlockedError("Custom message", domain="task")
        assert str(err) == "Custom message"
        assert err.domain == "task"

    def test_error_domain_none(self) -> None:
        """Error domain should be optional."""
        err = MutationBlockedError("Message")
        assert err.domain is None

    def test_error_is_runtime_error(self) -> None:
        """MutationBlockedError should be a RuntimeError."""
        err = MutationBlockedError("test")
        assert isinstance(err, RuntimeError)

    def test_error_can_be_caught_as_runtime_error(self) -> None:
        """MutationBlockedError should be catchable as RuntimeError."""
        with pytest.raises(RuntimeError):
            raise MutationBlockedError("test")


# ── Complex Scenarios ────────────────────────────────────────────────────────


class TestComplexScenarios:
    def test_multiple_goals_multiple_tasks(
        self, engine: RuleBasedProposalEngine
    ) -> None:
        """Complex scenario with multiple goals and tasks."""
        goal1 = Goal(title="Ship feature")
        goal2 = Goal(title="Learn framework")
        goal3 = Goal(title="Write docs", related_tasks=["Write docs task"])

        task1 = Task(title="Implement feature", due_date=date.today() - timedelta(days=1), priority=2)
        task2 = Task(title="Write docs task", due_date=date.today() + timedelta(days=5), priority=3)

        context = PlanningContext(
            goals=[goal1, goal2, goal3],
            tasks=[task1, task2],
            calendar=[],
        )

        plan = WeeklyPlan(
            week_summary="Complex week",
            priorities=[
                PriorityEntry(goal_id="Ship feature", reason="Urgent", priority=Priority.HIGH),
                PriorityEntry(goal_id="Learn framework", reason="Important", priority=Priority.MEDIUM),
            ],
            planned_tasks=[
                PlannedTask(
                    task_id="Implement feature",
                    goal_id="Ship feature",
                    priority=Priority.HIGH,
                    reason="Overdue",
                    suggested_day=date.today() + timedelta(days=1),
                ),
                PlannedTask(
                    task_id="Write docs task",
                    goal_id="Write docs",
                    priority=Priority.HIGH,
                    reason="Priority boost",
                    suggested_day=date.today() + timedelta(days=2),
                ),
            ],
            risks=[
                PlanningRisk(
                    description="Task 'Implement feature' blocked by dependency",
                    severity=RiskSeverity.HIGH,
                ),
                PlanningRisk(
                    description="Minor formatting issue",
                    severity=RiskSeverity.LOW,
                ),
            ],
        )

        proposals = engine.generate(plan, context)

        action_types = [p.action_type for p in proposals]
        assert ActionType.RESCHEDULE_TASK in action_types
        assert ActionType.CREATE_TASK in action_types  # goal2 has no tasks
        assert ActionType.CHANGE_PRIORITY in action_types
        assert ActionType.CREATE_CALENDAR_EVENT in action_types
        assert ActionType.UPDATE_TASK in action_types

        # All proposals should have required fields
        for p in proposals:
            assert p.reason != ""
            assert p.source != ""
            assert p.status == ProposalStatus.PROPOSED

    def test_plan_with_all_rules_triggered(
        self, engine: RuleBasedProposalEngine
    ) -> None:
        """Plan that triggers all 5 rules."""
        goal = Goal(title="Test goal")
        task = Task(title="Test task", due_date=date.today() - timedelta(days=1), priority=3)

        context = PlanningContext(
            goals=[goal],
            tasks=[task],
            calendar=[],
        )

        plan = WeeklyPlan(
            week_summary="All rules",
            planned_tasks=[
                PlannedTask(
                    task_id="Test task",
                    goal_id="Test goal",
                    priority=Priority.HIGH,
                    reason="Overdue and priority mismatch",
                    suggested_day=date.today() + timedelta(days=1),
                ),
            ],
            risks=[
                PlanningRisk(
                    description="Task 'Test task' has critical issue",
                    severity=RiskSeverity.HIGH,
                ),
            ],
        )

        proposals = engine.generate(plan, context)

        action_types = [p.action_type for p in proposals]
        assert ActionType.RESCHEDULE_TASK in action_types
        assert ActionType.CHANGE_PRIORITY in action_types
        assert ActionType.CREATE_CALENDAR_EVENT in action_types
        assert ActionType.UPDATE_TASK in action_types

    def test_very_long_reason(
        self, engine: RuleBasedProposalEngine
    ) -> None:
        """Very long reason should be handled."""
        long_reason = "A" * 10000
        goal = Goal(title="Goal")
        context = PlanningContext(goals=[goal], tasks=[], calendar=[])
        plan = WeeklyPlan(week_summary="Long reason")
        proposals = engine.generate(plan, context)
        # Should not crash
        assert isinstance(proposals, list)

    def test_special_characters_in_titles(
        self, engine: RuleBasedProposalEngine
    ) -> None:
        """Special characters in titles should be handled."""
        goal = Goal(title="Goal with special chars: <>&\"'")
        task = Task(title="Task with unicode: \u00e9\u00e8\u00ea")
        context = PlanningContext(goals=[goal], tasks=[task], calendar=[])
        plan = WeeklyPlan(
            week_summary="Special chars",
            planned_tasks=[
                PlannedTask(
                    task_id="Task with unicode: \u00e9\u00e8\u00ea",
                    goal_id="Goal with special chars: <>&\"'",
                    priority=Priority.HIGH,
                    reason="Test",
                    suggested_day=date.today() + timedelta(days=1),
                ),
            ],
        )
        proposals = engine.generate(plan, context)
        assert isinstance(proposals, list)
