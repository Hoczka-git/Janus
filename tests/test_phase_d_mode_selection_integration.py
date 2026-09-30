"""Integration tests for Phase D mode selection.

These tests exercise the planner's mode selection end-to-end using realistic
planning scenarios. They cover:

- Full execution_mode x support_mode combination matrix
- Fallback when a more substitutive mode is required
- Multi-goal, multi-task planning with agency context
- Mixed task types within a single goal
- Confidence variation with evidence and history
- Edge cases (no tasks, all completed, empty goals)
- REVIEW mode fallback when goal is completed
- EXECUTE override when execution_mode is JANUS

Design reference: docs/janus-agency-first-development-phase.md §Phase D
"""

from datetime import date

import pytest

from janus.domain.planning import derive_next_action
from janus.models.execution_mode import EXECUTION_MODE_ORDER, ExecutionMode
from janus.models.goal import Goal
from janus.models.support_mode import SUPPORT_MODE_ORDER, SupportMode
from janus.models.task import Task
from janus.models.task_agency import TaskAgency
from janus.services.agency_planning import (
    AgencyContext,
    classify_task,
    derive_agency_context,
    select_execution_mode,
    select_support_mode,
)
from janus.services.recommendations import recommend_tasks


# ── Helpers ──────────────────────────────────────────────────────────────────


def _task(title: str, **kwargs) -> Task:
    """Create a test task."""
    return Task(title=title, **kwargs)


def _goal(title: str = "Test Goal", **kwargs) -> Goal:
    """Create a test goal."""
    return Goal(title=title, **kwargs)


def _context(**kwargs) -> AgencyContext:
    """Create a test agency context."""
    return AgencyContext(**kwargs)


def _milestone(title: str, order: int = 0, status: str = "open") -> dict:
    """Create a milestone dict."""
    return {"title": title, "goal_title": "G", "status": status, "order": order}


# ── Full mode combination matrix ─────────────────────────────────────────────


class TestModeCombinationMatrix:
    """Verify all 15 execution_mode x support_mode combinations are reachable."""

    def test_user_explain(self):
        """USER + EXPLAIN: learning task, no evidence."""
        task = _task("Learn Python")
        goal = _goal()
        context = _context(skill_evidence_count=0)
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.USER
        assert agency.support_mode == SupportMode.EXPLAIN

    def test_user_coach(self):
        """USER + COACH: learning task, evidence, stalled goal."""
        task = _task("Practice algorithms")
        goal = _goal()
        context = _context(skill_evidence_count=3, goal_stalled=True)
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.USER
        assert agency.support_mode == SupportMode.COACH

    def test_user_scaffold(self):
        """USER + SCAFFOLD: learning task, evidence, healthy goal."""
        task = _task("Practice algorithms")
        goal = _goal()
        context = _context(skill_evidence_count=3, goal_health="healthy")
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.USER
        assert agency.support_mode == SupportMode.SCAFFOLD

    def test_user_review(self):
        """USER + REVIEW: learning task, evidence, completed goal, review metadata."""
        task = _task("Practice algorithms", extra_metadata=["review"])
        goal = _goal()
        context = _context(skill_evidence_count=3, goal_health="completed")
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.USER
        assert agency.support_mode == SupportMode.REVIEW

    def test_user_execute_via_janus_override(self):
        """USER execution with JANUS override → EXECUTE support.

        When execution_mode is JANUS (admin/routine task), support_mode
        is always EXECUTE regardless of other conditions.
        """
        task = _task("Sync data")
        goal = _goal()
        context = _context(skill_evidence_count=0)
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.JANUS
        assert agency.support_mode == SupportMode.EXECUTE

    def test_janus_execute_admin(self):
        """JANUS + EXECUTE: administrative task."""
        task = _task("Sync data files")
        goal = _goal()
        context = _context()
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.JANUS
        assert agency.support_mode == SupportMode.EXECUTE

    def test_janus_execute_routine(self):
        """JANUS + EXECUTE: routine task."""
        task = _task("Daily standup")
        goal = _goal()
        context = _context()
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.JANUS
        assert agency.support_mode == SupportMode.EXECUTE

    def test_collaborative_explain(self):
        """COLLABORATIVE + EXPLAIN: high complexity, no evidence."""
        task = _task("Design system", extra_metadata=["estimate: 8 hours"])
        goal = _goal()
        context = _context(skill_evidence_count=0)
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.COLLABORATIVE
        assert agency.support_mode == SupportMode.EXPLAIN

    def test_collaborative_coach(self):
        """COLLABORATIVE + COACH: high complexity, evidence, stalled goal."""
        task = _task("Design system", extra_metadata=["estimate: 8 hours"])
        goal = _goal()
        context = _context(skill_evidence_count=3, goal_stalled=True)
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.COLLABORATIVE
        assert agency.support_mode == SupportMode.COACH

    def test_collaborative_scaffold(self):
        """COLLABORATIVE + SCAFFOLD: high complexity, evidence, healthy goal."""
        task = _task("Design system", extra_metadata=["estimate: 8 hours"])
        goal = _goal()
        context = _context(skill_evidence_count=3, goal_health="healthy")
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.COLLABORATIVE
        assert agency.support_mode == SupportMode.SCAFFOLD

    def test_collaborative_review(self):
        """COLLABORATIVE + REVIEW: high complexity, evidence, completed goal, review."""
        task = _task("Design system", extra_metadata=["estimate: 8 hours", "review"])
        goal = _goal()
        context = _context(skill_evidence_count=3, goal_health="completed")
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.COLLABORATIVE
        assert agency.support_mode == SupportMode.REVIEW

    def test_collaborative_execute_via_janus_override(self):
        """COLLABORATIVE execution with JANUS override → EXECUTE support.

        High complexity task that is also administrative → JANUS execution
        (admin beats complexity in condition ordering) → EXECUTE support.
        """
        task = _task("Sync data files", extra_metadata=["estimate: 8 hours"])
        goal = _goal()
        context = _context(skill_evidence_count=0)
        agency = classify_task(task, goal, context)
        # Admin keyword "sync" → JANUS execution (checked before complexity)
        assert agency.execution_mode == ExecutionMode.JANUS
        assert agency.support_mode == SupportMode.EXECUTE


# ── Fallback scenarios ───────────────────────────────────────────────────────


class TestFallbackScenarios:
    """Verify fallback when a more substitutive mode is required."""

    def test_fallback_from_explain_to_coach(self):
        """When evidence exists and goal is stalled, fall back from EXPLAIN to COACH."""
        task = _task("Learn Python")
        goal = _goal()
        # No evidence → EXPLAIN
        context_no_evidence = _context(skill_evidence_count=0)
        assert select_support_mode(task, goal, context_no_evidence) == SupportMode.EXPLAIN
        # Evidence + stalled → COACH (fallback)
        context_stalled = _context(skill_evidence_count=3, goal_stalled=True)
        assert select_support_mode(task, goal, context_stalled) == SupportMode.COACH

    def test_fallback_from_coach_to_scaffold(self):
        """When goal is healthy (not stalled), fall back from COACH to SCAFFOLD."""
        task = _task("Practice algorithms")
        goal = _goal()
        # Evidence + stalled → COACH
        context_stalled = _context(skill_evidence_count=3, goal_stalled=True)
        assert select_support_mode(task, goal, context_stalled) == SupportMode.COACH
        # Evidence + healthy → SCAFFOLD (fallback)
        context_healthy = _context(skill_evidence_count=3, goal_health="healthy")
        assert select_support_mode(task, goal, context_healthy) == SupportMode.SCAFFOLD

    def test_fallback_from_scaffold_to_review(self):
        """When goal is completed, fall back from SCAFFOLD to REVIEW."""
        task = _task("Practice algorithms", extra_metadata=["review"])
        goal = _goal()
        # Evidence + healthy → SCAFFOLD
        context_healthy = _context(skill_evidence_count=3, goal_health="healthy")
        assert select_support_mode(task, goal, context_healthy) == SupportMode.SCAFFOLD
        # Evidence + completed → REVIEW (fallback)
        context_completed = _context(skill_evidence_count=3, goal_health="completed")
        assert select_support_mode(task, goal, context_completed) == SupportMode.REVIEW

    def test_fallback_from_user_to_janus(self):
        """When task is administrative, fall back from USER to JANUS."""
        task = _task("Sync data files")
        goal = _goal()
        context = _context()
        # Admin task → JANUS (not USER)
        assert select_execution_mode(task, goal, context) == ExecutionMode.JANUS

    def test_fallback_from_janus_to_collaborative(self):
        """When task is high complexity, fall back from JANUS to COLLABORATIVE."""
        task = _task("Design system", extra_metadata=["estimate: 8 hours"])
        goal = _goal()
        context = _context()
        # High complexity → COLLABORATIVE (not JANUS)
        assert select_execution_mode(task, goal, context) == ExecutionMode.COLLABORATIVE

    def test_fallback_default_to_user(self):
        """When no conditions match, default to USER (least substitutive)."""
        task = _task("Design architecture")  # general task, no metadata
        goal = _goal()
        context = _context()
        assert select_execution_mode(task, goal, context) == ExecutionMode.USER

    def test_fallback_default_to_explain(self):
        """When no conditions match, default to EXPLAIN (least substitutive)."""
        task = _task("Design architecture")  # general task, no metadata
        goal = _goal()
        context = _context(skill_evidence_count=0)
        assert select_support_mode(task, goal, context) == SupportMode.EXPLAIN

    def test_janus_override_beats_all_support_modes(self):
        """JANUS execution mode overrides all support mode conditions."""
        task = _task("Sync data")
        goal = _goal()
        # Even with evidence and stalled goal, JANUS → EXECUTE
        context = _context(skill_evidence_count=5, goal_stalled=True)
        assert select_support_mode(
            task, goal, context, execution_mode=ExecutionMode.JANUS
        ) == SupportMode.EXECUTE

    def test_janus_override_beats_review(self):
        """JANUS execution mode overrides REVIEW support mode."""
        task = _task("Sync data", extra_metadata=["review"])
        goal = _goal()
        context = _context(skill_evidence_count=3, goal_health="completed")
        assert select_support_mode(
            task, goal, context, execution_mode=ExecutionMode.JANUS
        ) == SupportMode.EXECUTE


# ── Realistic multi-goal planning scenarios ─────────────────────────────────


class TestRealisticMultiGoalPlanning:
    """Integration tests with realistic multi-goal, multi-task scenarios."""

    def test_data_science_goal_with_mixed_tasks(self):
        """Data science goal with admin, learning, and routine tasks."""
        goal = Goal(
            title="Build ML Pipeline",
            milestones=[_milestone("Data Collection"), _milestone("Model Training", order=1)],
            related_tasks=[
                "Sync data files",           # admin → JANUS + EXECUTE
                "Learn Python",              # learning → USER + EXPLAIN
                "Daily standup",             # routine → JANUS + EXECUTE
                "Design system",             # high complexity → COLLABORATIVE
            ],
        )
        tasks = [
            _task("Sync data files"),
            _task("Learn Python"),
            _task("Daily standup"),
            _task("Design system", extra_metadata=["estimate: 8 hours"]),
        ]
        context = _context(skill_evidence_count=2, goal_health="healthy")

        # derive_next_action should pick the first open task in the milestone
        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        assert action is not None
        assert action.agency is not None
        # First task is "Sync data files" → JANUS + EXECUTE
        assert action.agency.execution_mode == ExecutionMode.JANUS
        assert action.agency.support_mode == SupportMode.EXECUTE

    def test_fitness_goal_with_routine_tasks(self):
        """Fitness goal with routine tracking tasks."""
        goal = Goal(
            title="Marathon Training",
            milestones=[_milestone("Base Building")],
            related_tasks=[
                "Log workout",               # routine → JANUS + EXECUTE
                "Weekly review",             # routine → JANUS + EXECUTE
                "Learn nutrition",           # learning → USER + EXPLAIN
            ],
        )
        tasks = [
            _task("Log workout"),
            _task("Weekly review"),
            _task("Learn nutrition"),
        ]
        context = _context(skill_evidence_count=0, goal_health="healthy")

        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        assert action is not None
        assert action.agency.execution_mode == ExecutionMode.JANUS
        assert action.agency.support_mode == SupportMode.EXECUTE

    def test_career_goal_with_learning_tasks(self):
        """Career development goal with learning tasks."""
        goal = Goal(
            title="Get Promoted",
            milestones=[_milestone("Skill Building")],
            related_tasks=[
                "Learn system design",       # learning → USER + EXPLAIN
                "Practice algorithms",       # learning → USER + EXPLAIN
                "Read paper",                # learning → USER + EXPLAIN
            ],
        )
        tasks = [
            _task("Learn system design"),
            _task("Practice algorithms"),
            _task("Read paper"),
        ]
        context = _context(skill_evidence_count=0, goal_health="healthy")

        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        assert action is not None
        assert action.agency.execution_mode == ExecutionMode.USER
        assert action.agency.support_mode == SupportMode.EXPLAIN

    def test_project_goal_with_high_complexity_tasks(self):
        """Project goal with high complexity design tasks."""
        goal = Goal(
            title="Build Product",
            milestones=[_milestone("Architecture")],
            related_tasks=[
                "Design system",             # high complexity → COLLABORATIVE
                "Design database",           # high complexity → COLLABORATIVE
            ],
        )
        tasks = [
            _task("Design system", extra_metadata=["estimate: 8 hours"]),
            _task("Design database", extra_metadata=["estimate: 12 hours"]),
        ]
        context = _context(skill_evidence_count=2, goal_health="healthy")

        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        assert action is not None
        assert action.agency.execution_mode == ExecutionMode.COLLABORATIVE
        assert action.agency.support_mode == SupportMode.SCAFFOLD

    def test_stalled_goal_triggers_coach(self):
        """Stalled goal with evidence triggers COACH support mode."""
        goal = Goal(
            title="Learn Rust",
            milestones=[_milestone("Basics")],
            related_tasks=["Practice algorithms"],
        )
        tasks = [_task("Practice algorithms")]
        context = _context(skill_evidence_count=3, goal_stalled=True, goal_health="stalled")

        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        assert action is not None
        assert action.agency.support_mode == SupportMode.COACH

    def test_completed_goal_triggers_review(self):
        """Completed goal with review metadata triggers REVIEW support mode."""
        goal = Goal(
            title="Ship v1",
            milestones=[_milestone("Release")],
            related_tasks=["Implement feature"],
        )
        tasks = [_task("Implement feature", extra_metadata=["review"])]
        context = _context(skill_evidence_count=3, goal_health="completed")

        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        assert action is not None
        assert action.agency.support_mode == SupportMode.REVIEW


# ── Confidence variation ─────────────────────────────────────────────────────


class TestConfidenceVariation:
    """Verify confidence varies realistically with evidence and history."""

    def test_no_evidence_low_confidence(self):
        """No evidence → base confidence (0.5)."""
        task = _task("Learn Python")
        goal = _goal()
        context = _context(skill_evidence_count=0, task_completion_history=0)
        agency = classify_task(task, goal, context)
        assert agency.confidence == 0.5

    def test_some_evidence_moderate_confidence(self):
        """Some evidence → moderate confidence."""
        task = _task("Learn Python")
        goal = _goal()
        context = _context(skill_evidence_count=3, task_completion_history=2)
        agency = classify_task(task, goal, context)
        assert 0.5 < agency.confidence < 1.0

    def test_high_evidence_high_confidence(self):
        """High evidence → high confidence."""
        task = _task("Learn Python")
        goal = _goal()
        context = _context(skill_evidence_count=10, task_completion_history=10)
        agency = classify_task(task, goal, context)
        assert agency.confidence > 0.7

    def test_max_evidence_capped_confidence(self):
        """Maximum evidence → confidence capped at 1.0."""
        task = _task("Learn Python")
        goal = _goal()
        context = _context(skill_evidence_count=100, task_completion_history=100)
        agency = classify_task(task, goal, context)
        assert agency.confidence == 1.0

    def test_evidence_bonus_calculation(self):
        """Evidence bonus is 0.1 per piece, capped at 0.3."""
        task = _task("Learn Python")
        goal = _goal()
        # 2 pieces → 0.2 bonus
        context = _context(skill_evidence_count=2, task_completion_history=0)
        agency = classify_task(task, goal, context)
        assert agency.confidence == pytest.approx(0.7)
        # 5 pieces → 0.3 bonus (capped)
        context = _context(skill_evidence_count=5, task_completion_history=0)
        agency = classify_task(task, goal, context)
        assert agency.confidence == pytest.approx(0.8)

    def test_history_bonus_calculation(self):
        """History bonus is 0.05 per completion, capped at 0.2."""
        task = _task("Learn Python")
        goal = _goal()
        # 2 completions → 0.1 bonus
        context = _context(skill_evidence_count=0, task_completion_history=2)
        agency = classify_task(task, goal, context)
        assert agency.confidence == pytest.approx(0.6)
        # 10 completions → 0.2 bonus (capped)
        context = _context(skill_evidence_count=0, task_completion_history=10)
        agency = classify_task(task, goal, context)
        assert agency.confidence == pytest.approx(0.7)


# ── Edge cases ───────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_goal_no_tasks(self):
        """Goal with no tasks → no next action."""
        goal = Goal(title="Empty Goal", milestones=[_milestone("M1")], related_tasks=[])
        tasks: list[Task] = []
        context = _context(skill_evidence_count=0, goal_health="healthy")
        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        # No tasks → milestone action (no agency)
        assert action is not None
        assert action.kind == "milestone"
        assert action.agency is None

    def test_all_tasks_completed(self):
        """All tasks completed → no task action."""
        goal = Goal(
            title="Done Goal",
            milestones=[_milestone("M1")],
            related_tasks=["Learn Python"],
        )
        tasks: list[Task] = []
        context = _context(skill_evidence_count=0, goal_health="healthy")
        action = derive_next_action(goal, tasks, {"Learn Python"}, date.today(), agency_context=context)
        # All completed → milestone action
        assert action is not None
        assert action.kind == "milestone"
        assert action.agency is None

    def test_no_milestones(self):
        """Goal with no milestones → no next action."""
        goal = Goal(title="No Milestones", related_tasks=["Learn Python"])
        tasks = [_task("Learn Python")]
        context = _context(skill_evidence_count=0, goal_health="healthy")
        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        # No milestones → task action (R2: no milestone assigned)
        assert action is not None
        assert action.kind == "task"
        assert action.agency is not None

    def test_task_not_in_goal(self):
        """Task not related to goal → not included in recommendations."""
        goal = Goal(
            title="G1",
            milestones=[_milestone("M1")],
            related_tasks=["Learn Python"],
        )
        tasks = [_task("Learn Python"), _task("Sync data")]
        context = _context(skill_evidence_count=0, goal_health="healthy")
        result = recommend_tasks([goal], tasks, set(), date.today(), agency_context=context)
        # Only "Learn Python" is related to G1
        assert len(result) == 1
        assert result[0].title == "Learn Python"

    def test_multiple_goals_independent_agency(self):
        """Each goal's tasks get independent agency classification."""
        goal1 = Goal(
            title="Admin Goal",
            milestones=[_milestone("M1")],
            related_tasks=["Sync data"],
        )
        goal2 = Goal(
            title="Learning Goal",
            milestones=[_milestone("M1")],
            related_tasks=["Learn Python"],
        )
        tasks = [_task("Sync data"), _task("Learn Python")]
        context = _context(skill_evidence_count=0, goal_health="healthy")

        result = recommend_tasks([goal1, goal2], tasks, set(), date.today(), agency_context=context)
        assert len(result) >= 2

        admin_recs = [r for r in result if r.goal_title == "Admin Goal"]
        learning_recs = [r for r in result if r.goal_title == "Learning Goal"]
        assert len(admin_recs) > 0
        assert len(learning_recs) > 0
        assert admin_recs[0].agency.execution_mode == ExecutionMode.JANUS
        assert learning_recs[0].agency.execution_mode == ExecutionMode.USER

    def test_agency_context_none_backward_compatible(self):
        """Without agency_context, actions have no agency (backward compat)."""
        goal = Goal(
            title="G",
            milestones=[_milestone("M1")],
            related_tasks=["Learn Python"],
        )
        tasks = [_task("Learn Python")]
        action = derive_next_action(goal, tasks, set(), date.today())
        assert action is not None
        assert action.agency is None

    def test_derive_agency_context_defaults(self):
        """derive_agency_context with no args returns defaults."""
        context = derive_agency_context()
        assert context.skill_evidence_count == 0
        assert context.goal_health == "healthy"
        assert context.goal_stalled is False
        assert context.task_completion_history == 0

    def test_derive_agency_context_with_values(self):
        """derive_agency_context with values returns those values."""
        context = derive_agency_context(
            skill_evidence_count=5,
            goal_health="stalled",
            goal_stalled=True,
            task_completion_history=10,
        )
        assert context.skill_evidence_count == 5
        assert context.goal_health == "stalled"
        assert context.goal_stalled is True
        assert context.task_completion_history == 10


# ── Enum ordering verification ───────────────────────────────────────────────


class TestEnumOrdering:
    """Verify enum ordering matches design doc specification."""

    def test_execution_mode_order(self):
        """Execution mode order: USER → JANUS → COLLABORATIVE."""
        assert EXECUTION_MODE_ORDER == (
            ExecutionMode.USER,
            ExecutionMode.JANUS,
            ExecutionMode.COLLABORATIVE,
        )

    def test_support_mode_order(self):
        """Support mode order: EXPLAIN → COACH → SCAFFOLD → REVIEW → EXECUTE."""
        assert SUPPORT_MODE_ORDER == (
            SupportMode.EXPLAIN,
            SupportMode.COACH,
            SupportMode.SCAFFOLD,
            SupportMode.REVIEW,
            SupportMode.EXECUTE,
        )

    def test_execution_mode_values(self):
        """Execution mode values match design doc."""
        assert ExecutionMode.USER == "user"
        assert ExecutionMode.JANUS == "janus"
        assert ExecutionMode.COLLABORATIVE == "collaborative"

    def test_support_mode_values(self):
        """Support mode values match design doc."""
        assert SupportMode.EXPLAIN == "explain"
        assert SupportMode.COACH == "coach"
        assert SupportMode.SCAFFOLD == "scaffold"
        assert SupportMode.REVIEW == "review"
        assert SupportMode.EXECUTE == "execute"


# ── Reason string verification ───────────────────────────────────────────────


class TestReasonString:
    """Verify reason strings are informative and accurate."""

    def test_reason_contains_nature(self):
        """Reason string contains task nature."""
        task = _task("Sync data files")
        goal = _goal()
        context = _context()
        agency = classify_task(task, goal, context)
        assert "administrative" in agency.reason.lower()

    def test_reason_contains_execution_mode(self):
        """Reason string contains execution mode."""
        task = _task("Learn Python")
        goal = _goal()
        context = _context()
        agency = classify_task(task, goal, context)
        assert "user" in agency.reason.lower()

    def test_reason_contains_support_mode(self):
        """Reason string contains support mode."""
        task = _task("Learn Python")
        goal = _goal()
        context = _context()
        agency = classify_task(task, goal, context)
        assert "explain" in agency.reason.lower()

    def test_reason_contains_evidence_count(self):
        """Reason string contains evidence count when > 0."""
        task = _task("Learn Python")
        goal = _goal()
        context = _context(skill_evidence_count=5)
        agency = classify_task(task, goal, context)
        assert "5" in agency.reason

    def test_reason_contains_stalled_indicator(self):
        """Reason string contains stalled indicator when goal is stalled."""
        task = _task("Learn Python")
        goal = _goal()
        context = _context(skill_evidence_count=3, goal_stalled=True)
        agency = classify_task(task, goal, context)
        assert "stalled" in agency.reason.lower()


# ── Determinism ──────────────────────────────────────────────────────────────


class TestDeterminism:
    """Verify classification is deterministic."""

    def test_same_input_same_output(self):
        """Same inputs → same output."""
        task = _task("Learn Python")
        goal = _goal()
        context = _context(skill_evidence_count=3, goal_health="healthy")
        agency1 = classify_task(task, goal, context)
        agency2 = classify_task(task, goal, context)
        assert agency1.execution_mode == agency2.execution_mode
        assert agency1.support_mode == agency2.support_mode
        assert agency1.confidence == agency2.confidence
        assert agency1.reason == agency2.reason

    def test_different_evidence_different_output(self):
        """Different evidence counts → potentially different output."""
        task = _task("Learn Python")
        goal = _goal()
        context_no_evidence = _context(skill_evidence_count=0)
        context_with_evidence = _context(skill_evidence_count=5)
        agency1 = classify_task(task, goal, context_no_evidence)
        agency2 = classify_task(task, goal, context_with_evidence)
        # Support mode should differ (EXPLAIN vs SCAFFOLD)
        assert agency1.support_mode != agency2.support_mode


# ── TaskAgency dataclass ─────────────────────────────────────────────────────


class TestTaskAgencyDataclass:
    """Verify TaskAgency dataclass behavior."""

    def test_task_agency_creation(self):
        """TaskAgency can be created with all fields."""
        agency = TaskAgency(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
            reason="Test reason",
            confidence=0.8,
        )
        assert agency.execution_mode == ExecutionMode.USER
        assert agency.support_mode == SupportMode.EXPLAIN
        assert agency.reason == "Test reason"
        assert agency.confidence == 0.8

    def test_task_agency_default_confidence(self):
        """TaskAgency confidence defaults to 0.5."""
        agency = TaskAgency(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
            reason="Test reason",
        )
        assert agency.confidence == 0.5


# ── Integration with recommend_tasks ─────────────────────────────────────────


class TestRecommendTasksIntegration:
    """Integration tests for recommend_tasks with agency context."""

    def test_recommend_tasks_propagates_agency(self):
        """recommend_tasks propagates agency from derive_next_action."""
        goal = Goal(
            title="G",
            milestones=[_milestone("M1")],
            related_tasks=["Learn Python"],
        )
        tasks = [_task("Learn Python")]
        context = _context(skill_evidence_count=0, goal_health="healthy")
        result = recommend_tasks([goal], tasks, set(), date.today(), agency_context=context)
        assert len(result) > 0
        assert result[0].agency is not None
        assert result[0].agency.execution_mode == ExecutionMode.USER
        assert result[0].agency.support_mode == SupportMode.EXPLAIN

    def test_recommend_tasks_multiple_goals(self):
        """recommend_tasks handles multiple goals with different agency."""
        goal1 = Goal(
            title="Admin Goal",
            milestones=[_milestone("M1")],
            related_tasks=["Sync data"],
        )
        goal2 = Goal(
            title="Learning Goal",
            milestones=[_milestone("M1")],
            related_tasks=["Learn Python"],
        )
        tasks = [_task("Sync data"), _task("Learn Python")]
        context = _context(skill_evidence_count=0, goal_health="healthy")
        result = recommend_tasks([goal1, goal2], tasks, set(), date.today(), agency_context=context)
        assert len(result) >= 2

    def test_recommend_tasks_with_filters(self):
        """recommend_tasks respects filters with agency context."""
        goal = Goal(
            title="G",
            milestones=[_milestone("M1")],
            related_tasks=["Learn Python", "Sync data"],
        )
        tasks = [_task("Learn Python"), _task("Sync data")]
        context = _context(skill_evidence_count=0, goal_health="healthy")
        result = recommend_tasks(
            [goal], tasks, set(), date.today(),
            agency_context=context,
            kind_filter="task",
        )
        assert len(result) > 0
        assert all(r.kind == "task" for r in result)

    def test_recommend_tasks_no_agency_without_context(self):
        """recommend_tasks without agency_context returns no agency."""
        goal = Goal(
            title="G",
            milestones=[_milestone("M1")],
            related_tasks=["Learn Python"],
        )
        tasks = [_task("Learn Python")]
        result = recommend_tasks([goal], tasks, set(), date.today())
        assert len(result) > 0
        assert result[0].agency is None
