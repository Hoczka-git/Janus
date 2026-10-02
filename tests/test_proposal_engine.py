"""Tests for the RuleBasedProposalEngine — WeeklyPlan to ActionProposal transformation."""

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
    ProposalStatus,
    RuleBasedProposalEngine,
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


# ── Empty plan tests ─────────────────────────────────────────────────────────


class TestEmptyPlan:
    def test_empty_plan_returns_no_proposals(
        self, engine: RuleBasedProposalEngine, empty_plan: WeeklyPlan, empty_context: PlanningContext
    ) -> None:
        proposals = engine.generate(empty_plan, empty_context)
        assert proposals == []

    def test_empty_context_returns_no_proposals(
        self, engine: RuleBasedProposalEngine, empty_plan: WeeklyPlan
    ) -> None:
        context = PlanningContext(goals=[], tasks=[], calendar=[])
        proposals = engine.generate(empty_plan, context)
        assert proposals == []


# ── Rule 1: Overdue tasks -> RESCHEDULE_TASK ─────────────────────────────────


class TestOverdueTaskRule:
    def test_overdue_task_generates_reschedule(
        self, engine: RuleBasedProposalEngine, overdue_task: Task
    ) -> None:
        context = PlanningContext(
            goals=[Goal(title="Fix bugs")],
            tasks=[overdue_task],
            calendar=[],
        )
        plan = WeeklyPlan(
            week_summary="Fix overdue items",
            planned_tasks=[
                PlannedTask(
                    task_id=overdue_task.title,
                    goal_id="Fix bugs",
                    priority=Priority.HIGH,
                    reason="Overdue",
                    suggested_day=date.today() + timedelta(days=1),
                ),
            ],
        )
        proposals = engine.generate(plan, context)

        reschedule_proposals = [p for p in proposals if p.action_type == ActionType.RESCHEDULE_TASK]
        assert len(reschedule_proposals) == 1
        p = reschedule_proposals[0]
        assert p.target_id == overdue_task.title
        assert p.parameters["new_due_date"] == (date.today() + timedelta(days=1)).isoformat()
        assert overdue_task.due_date is not None
        assert p.parameters["old_due_date"] == overdue_task.due_date.isoformat()
        assert "overdue" in p.reason.lower()
        assert p.source == "rule:overdue"
        assert p.risk == RiskLevel.MEDIUM
        assert p.status == ProposalStatus.PROPOSED

    def test_non_overdue_task_no_reschedule(
        self, engine: RuleBasedProposalEngine, sample_task: Task, sample_goal: Goal
    ) -> None:
        context = PlanningContext(goals=[sample_goal], tasks=[sample_task], calendar=[])
        plan = WeeklyPlan(
            week_summary="Normal week",
            planned_tasks=[
                PlannedTask(
                    task_id=sample_task.title,
                    goal_id=sample_goal.title,
                    priority=Priority.MEDIUM,
                    reason="Normal",
                    suggested_day=date.today() + timedelta(days=2),
                ),
            ],
        )
        proposals = engine.generate(plan, context)
        reschedule_proposals = [p for p in proposals if p.action_type == ActionType.RESCHEDULE_TASK]
        assert len(reschedule_proposals) == 0


# ── Rule 2: Goals without tasks -> CREATE_TASK ───────────────────────────────


class TestMissingTaskRule:
    def test_goal_without_tasks_generates_create_task(
        self, engine: RuleBasedProposalEngine
    ) -> None:
        goal = Goal(title="Learn Rust")
        context = PlanningContext(goals=[goal], tasks=[], calendar=[])
        plan = WeeklyPlan(week_summary="Learn new things")

        proposals = engine.generate(plan, context)

        assert len(proposals) == 1
        p = proposals[0]
        assert p.action_type == ActionType.CREATE_TASK
        assert p.target_id == "Learn Rust"
        assert p.parameters["title"] == "Work on: Learn Rust"
        assert p.parameters["goal_id"] == "Learn Rust"
        assert "no tasks" in p.reason.lower()
        assert p.source == "rule:missing_task"
        assert p.risk == RiskLevel.LOW

    def test_goal_with_tasks_no_create_task(
        self, engine: RuleBasedProposalEngine, sample_goal: Goal, sample_task: Task
    ) -> None:
        sample_goal.related_tasks = [sample_task.title]
        context = PlanningContext(goals=[sample_goal], tasks=[sample_task], calendar=[])
        plan = WeeklyPlan(week_summary="Normal week")

        proposals = engine.generate(plan, context)
        create_proposals = [p for p in proposals if p.action_type == ActionType.CREATE_TASK]
        assert len(create_proposals) == 0


# ── Rule 3: Priority mismatch -> CHANGE_PRIORITY ─────────────────────────────


class TestPriorityMismatchRule:
    def test_priority_mismatch_generates_change_priority(
        self, engine: RuleBasedProposalEngine, sample_goal: Goal
    ) -> None:
        task = Task(title="Low priority task", priority=3)
        context = PlanningContext(goals=[sample_goal], tasks=[task], calendar=[])
        plan = WeeklyPlan(
            week_summary="Re-prioritize",
            planned_tasks=[
                PlannedTask(
                    task_id="Low priority task",
                    goal_id=sample_goal.title,
                    priority=Priority.HIGH,
                    reason="Needs to be high",
                    suggested_day=date.today() + timedelta(days=1),
                ),
            ],
        )
        proposals = engine.generate(plan, context)

        change_proposals = [p for p in proposals if p.action_type == ActionType.CHANGE_PRIORITY]
        assert len(change_proposals) == 1
        p = change_proposals[0]
        assert p.target_id == "Low priority task"
        assert p.parameters["new_priority"] == 1  # HIGH -> 1
        assert p.parameters["old_priority"] == 3
        assert p.source == "rule:priority_mismatch"

    def test_matching_priority_no_change(
        self, engine: RuleBasedProposalEngine, sample_goal: Goal
    ) -> None:
        task = Task(title="Already high priority", priority=1)
        context = PlanningContext(goals=[sample_goal], tasks=[task], calendar=[])
        plan = WeeklyPlan(
            week_summary="Keep priorities",
            planned_tasks=[
                PlannedTask(
                    task_id="Already high priority",
                    goal_id=sample_goal.title,
                    priority=Priority.HIGH,
                    reason="Already high",
                    suggested_day=date.today() + timedelta(days=1),
                ),
            ],
        )
        proposals = engine.generate(plan, context)
        change_proposals = [p for p in proposals if p.action_type == ActionType.CHANGE_PRIORITY]
        assert len(change_proposals) == 0


# ── Rule 4: Planned tasks -> CREATE_CALENDAR_EVENT ───────────────────────────


class TestCalendarEntryRule:
    def test_planned_task_generates_calendar_event(
        self, engine: RuleBasedProposalEngine, sample_goal: Goal
    ) -> None:
        task = Task(title="Team meeting", due_date=date.today() + timedelta(days=5))
        context = PlanningContext(goals=[sample_goal], tasks=[task], calendar=[])
        plan = WeeklyPlan(
            week_summary="Schedule meetings",
            planned_tasks=[
                PlannedTask(
                    task_id="Team meeting",
                    goal_id=sample_goal.title,
                    priority=Priority.MEDIUM,
                    reason="Weekly sync",
                    suggested_day=date.today() + timedelta(days=2),
                ),
            ],
        )
        proposals = engine.generate(plan, context)

        cal_proposals = [p for p in proposals if p.action_type == ActionType.CREATE_CALENDAR_EVENT]
        assert len(cal_proposals) == 1
        p = cal_proposals[0]
        assert p.target_id == "Team meeting"
        assert p.parameters["date"] == (date.today() + timedelta(days=2)).isoformat()
        assert p.source == "rule:calendar_entry"

    def test_existing_calendar_event_no_duplicate(
        self, engine: RuleBasedProposalEngine, sample_goal: Goal
    ) -> None:
        meeting_day = date.today() + timedelta(days=2)
        task = Task(title="Team meeting", due_date=date.today() + timedelta(days=5))
        event = Event(
            title="Team meeting",
            start=datetime.combine(meeting_day, datetime.min.time()),
            end=datetime.combine(meeting_day, datetime.min.time()) + timedelta(hours=1),
        )
        context = PlanningContext(goals=[sample_goal], tasks=[task], calendar=[event])
        plan = WeeklyPlan(
            week_summary="Schedule meetings",
            planned_tasks=[
                PlannedTask(
                    task_id="Team meeting",
                    goal_id=sample_goal.title,
                    priority=Priority.MEDIUM,
                    reason="Weekly sync",
                    suggested_day=meeting_day,
                ),
            ],
        )
        proposals = engine.generate(plan, context)
        cal_proposals = [p for p in proposals if p.action_type == ActionType.CREATE_CALENDAR_EVENT]
        assert len(cal_proposals) == 0


# ── Rule 5: High-severity risks -> UPDATE_TASK ───────────────────────────────


class TestRiskRule:
    def test_high_severity_risk_generates_update_task(
        self, engine: RuleBasedProposalEngine, sample_goal: Goal, sample_task: Task
    ) -> None:
        context = PlanningContext(goals=[sample_goal], tasks=[sample_task], calendar=[])
        plan = WeeklyPlan(
            week_summary="Risky week",
            planned_tasks=[
                PlannedTask(
                    task_id=sample_task.title,
                    goal_id=sample_goal.title,
                    priority=Priority.HIGH,
                    reason="Important",
                    suggested_day=date.today() + timedelta(days=1),
                ),
            ],
            risks=[
                PlanningRisk(
                    description=f"Task '{sample_task.title}' has a critical dependency that may block progress",
                    severity=RiskSeverity.HIGH,
                ),
            ],
        )
        proposals = engine.generate(plan, context)

        update_proposals = [p for p in proposals if p.action_type == ActionType.UPDATE_TASK]
        assert len(update_proposals) == 1
        p = update_proposals[0]
        assert p.target_id == sample_task.title
        assert p.risk == RiskLevel.HIGH
        assert p.source == "rule:risk"
        assert "critical dependency" in p.reason.lower()

    def test_low_severity_risk_no_update(
        self, engine: RuleBasedProposalEngine, sample_goal: Goal, sample_task: Task
    ) -> None:
        context = PlanningContext(goals=[sample_goal], tasks=[sample_task], calendar=[])
        plan = WeeklyPlan(
            week_summary="Normal week",
            planned_tasks=[
                PlannedTask(
                    task_id=sample_task.title,
                    goal_id=sample_goal.title,
                    priority=Priority.MEDIUM,
                    reason="Normal",
                    suggested_day=date.today() + timedelta(days=1),
                ),
            ],
            risks=[
                PlanningRisk(description="Minor formatting issue", severity=RiskSeverity.LOW),
            ],
        )
        proposals = engine.generate(plan, context)
        update_proposals = [p for p in proposals if p.action_type == ActionType.UPDATE_TASK]
        assert len(update_proposals) == 0


# ── Deduplication ────────────────────────────────────────────────────────────


class TestDeduplication:
    def test_no_duplicate_proposals(
        self, engine: RuleBasedProposalEngine, sample_goal: Goal, sample_task: Task
    ) -> None:
        context = PlanningContext(goals=[sample_goal], tasks=[sample_task], calendar=[])
        plan = WeeklyPlan(
            week_summary="Test dedup",
            planned_tasks=[
                PlannedTask(
                    task_id=sample_task.title,
                    goal_id=sample_goal.title,
                    priority=Priority.HIGH,
                    reason="Important",
                    suggested_day=date.today() + timedelta(days=1),
                ),
            ],
        )
        proposals = engine.generate(plan, context)

        # Check no duplicate (action_type, target_id) pairs
        seen: set[tuple[ActionType, str | None]] = set()
        for p in proposals:
            key = (p.action_type, p.target_id)
            assert key not in seen, f"Duplicate proposal: {key}"
            seen.add(key)


# ── Protocol conformance ─────────────────────────────────────────────────────


class TestProtocolConformance:
    def test_engine_satisfies_protocol(self, engine: RuleBasedProposalEngine) -> None:
        assert isinstance(engine, ActionProposalEngine)

    def test_generate_returns_list_of_proposals(
        self, engine: RuleBasedProposalEngine, sample_plan: WeeklyPlan, sample_context: PlanningContext
    ) -> None:
        proposals = engine.generate(sample_plan, sample_context)
        assert isinstance(proposals, list)
        assert all(isinstance(p, ActionProposal) for p in proposals)


# ── No side effects ──────────────────────────────────────────────────────────


class TestNoSideEffects:
    def test_generate_does_not_modify_plan(
        self, engine: RuleBasedProposalEngine, sample_plan: WeeklyPlan, sample_context: PlanningContext
    ) -> None:
        original_summary = sample_plan.week_summary
        original_tasks = list(sample_plan.planned_tasks)
        original_priorities = list(sample_plan.priorities)

        engine.generate(sample_plan, sample_context)

        assert sample_plan.week_summary == original_summary
        assert sample_plan.planned_tasks == original_tasks
        assert sample_plan.priorities == original_priorities

    def test_generate_does_not_modify_context(
        self, engine: RuleBasedProposalEngine, sample_plan: WeeklyPlan, sample_context: PlanningContext
    ) -> None:
        original_goals = list(sample_context.goals)
        original_tasks = list(sample_context.tasks)
        original_calendar = list(sample_context.calendar)

        engine.generate(sample_plan, sample_context)

        assert sample_context.goals == original_goals
        assert sample_context.tasks == original_tasks
        assert sample_context.calendar == original_calendar

    def test_generate_does_not_modify_tasks(
        self, engine: RuleBasedProposalEngine, sample_goal: Goal
    ) -> None:
        task = Task(title="Test task", priority=2, due_date=date.today() + timedelta(days=3))
        context = PlanningContext(goals=[sample_goal], tasks=[task], calendar=[])
        plan = WeeklyPlan(
            week_summary="Test",
            planned_tasks=[
                PlannedTask(
                    task_id="Test task",
                    goal_id=sample_goal.title,
                    priority=Priority.HIGH,
                    reason="Test",
                    suggested_day=date.today() + timedelta(days=1),
                ),
            ],
        )

        engine.generate(plan, context)

        assert task.priority == 2  # unchanged
        assert task.due_date == date.today() + timedelta(days=3)  # unchanged


# ── Serialization ────────────────────────────────────────────────────────────


class TestSerialization:
    def test_proposals_serializable(
        self, engine: RuleBasedProposalEngine, sample_plan: WeeklyPlan, sample_context: PlanningContext
    ) -> None:
        proposals = engine.generate(sample_plan, sample_context)
        for p in proposals:
            d = p.to_dict()
            assert d["action_type"] == p.action_type.value
            assert d["target_id"] == p.target_id
            assert d["reason"] == p.reason
            assert d["source"] == p.source
            assert d["risk"] == p.risk.value
            assert d["status"] == p.status.value

            # Round-trip
            p2 = ActionProposal.from_dict(d)
            assert p2.action_type == p.action_type
            assert p2.target_id == p.target_id
            assert p2.reason == p.reason
            assert p2.source == p.source
            assert p2.risk == p.risk
            assert p2.status == p.status


# ── Integration: Full pipeline ───────────────────────────────────────────────


class TestFullPipeline:
    def test_complex_plan_generates_multiple_proposals(self, engine: RuleBasedProposalEngine) -> None:
        """A complex plan with multiple issues should generate multiple proposals."""
        goal1 = Goal(title="Ship feature")
        goal2 = Goal(title="Learn new framework")
        task1 = Task(title="Implement feature", due_date=date.today() - timedelta(days=1), priority=2)
        task2 = Task(title="Write docs", due_date=date.today() + timedelta(days=5), priority=3)

        context = PlanningContext(
            goals=[goal1, goal2],
            tasks=[task1, task2],
            calendar=[],
        )
        plan = WeeklyPlan(
            week_summary="Complex week with multiple issues",
            priorities=[
                PriorityEntry(goal_id="Ship feature", reason="Urgent", priority=Priority.HIGH),
                PriorityEntry(goal_id="Learn new framework", reason="Important", priority=Priority.MEDIUM),
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
                    task_id="Write docs",
                    goal_id="Ship feature",
                    priority=Priority.HIGH,
                    reason="Needs priority boost",
                    suggested_day=date.today() + timedelta(days=2),
                ),
            ],
            risks=[
                PlanningRisk(
                    description="Task 'Implement feature' blocked by external dependency",
                    severity=RiskSeverity.HIGH,
                ),
            ],
        )

        proposals = engine.generate(plan, context)

        # Should have: RESCHEDULE (overdue), CREATE_TASK (goal2 has no tasks),
        # CHANGE_PRIORITY (task2), CREATE_CALENDAR_EVENT (task1), CREATE_CALENDAR_EVENT (task2),
        # UPDATE_TASK (high risk)
        action_types = [p.action_type for p in proposals]
        assert ActionType.RESCHEDULE_TASK in action_types
        assert ActionType.CREATE_TASK in action_types
        assert ActionType.CHANGE_PRIORITY in action_types
        assert ActionType.CREATE_CALENDAR_EVENT in action_types
        assert ActionType.UPDATE_TASK in action_types

        # All proposals should have required fields
        for p in proposals:
            assert p.reason != ""
            assert p.source != ""
            assert p.status == ProposalStatus.PROPOSED
            assert p.proposal_id == ""  # default
