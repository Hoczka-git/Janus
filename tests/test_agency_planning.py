"""Tests for agency-aware planning service.

Covers the mode-selection algorithm across representative scenarios:
- Execution mode selection (USER, JANUS, COLLABORATIVE)
- Support mode selection (EXPLAIN, COACH, SCAFFOLD, REVIEW, EXECUTE)
- TaskAgency classification
- AgencyContext derivation
"""

from datetime import date

import pytest

from janus.domain.planning import derive_next_action
from janus.models.execution_mode import ExecutionMode
from janus.models.goal import Goal
from janus.models.milestone import Milestone
from janus.models.support_mode import SupportMode
from janus.models.task import Task
from janus.models.task_agency import TaskAgency
from janus.services.agency_planning import (
    AgencyContext,
    _classify_task_nature,
    _compute_confidence,
    _is_high_complexity,
    _is_review_phase,
    classify_next_action,
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


# ── Task nature classification ──────────────────────────────────────────────


class TestTaskNatureClassification:
    def test_administrative_keywords(self):
        assert _classify_task_nature(_task("Sync data files")) == "administrative"
        assert _classify_task_nature(_task("Format report")) == "administrative"
        assert _classify_task_nature(_task("Collect metrics")) == "administrative"
        assert _classify_task_nature(_task("Aggregate results")) == "administrative"
        assert _classify_task_nature(_task("Summarize findings")) == "administrative"

    def test_learning_keywords(self):
        assert _classify_task_nature(_task("Learn Python")) == "learning"
        assert _classify_task_nature(_task("Practice algorithms")) == "learning"
        assert _classify_task_nature(_task("Study ML")) == "learning"
        assert _classify_task_nature(_task("Read paper")) == "learning"
        assert _classify_task_nature(_task("Complete course")) == "learning"

    def test_routine_keywords(self):
        assert _classify_task_nature(_task("Daily standup")) == "routine"
        assert _classify_task_nature(_task("Weekly review")) == "routine"
        assert _classify_task_nature(_task("Routine maintenance")) == "routine"
        assert _classify_task_nature(_task("Check email")) == "routine"
        assert _classify_task_nature(_task("Log workout")) == "routine"

    def test_general_task(self):
        assert _classify_task_nature(_task("Design architecture")) == "general"
        assert _classify_task_nature(_task("Write code")) == "general"
        assert _classify_task_nature(_task("Fix bug")) == "general"


# ── Execution mode selection ────────────────────────────────────────────────


class TestExecutionModeSelection:
    def test_administrative_task_returns_janus(self):
        task = _task("Sync data files")
        goal = _goal()
        context = _context()
        assert select_execution_mode(task, goal, context) == ExecutionMode.JANUS

    def test_learning_task_returns_user(self):
        task = _task("Learn Python")
        goal = _goal()
        context = _context()
        assert select_execution_mode(task, goal, context) == ExecutionMode.USER

    def test_high_complexity_returns_collaborative(self):
        task = _task("Design system", extra_metadata=["estimate: 8 hours"])
        goal = _goal()
        context = _context()
        assert select_execution_mode(task, goal, context) == ExecutionMode.COLLABORATIVE

    def test_routine_task_returns_janus(self):
        task = _task("Daily standup")
        goal = _goal()
        context = _context()
        assert select_execution_mode(task, goal, context) == ExecutionMode.JANUS

    def test_default_returns_user(self):
        task = _task("Design architecture")
        goal = _goal()
        context = _context()
        assert select_execution_mode(task, goal, context) == ExecutionMode.USER

    def test_administrative_beats_learning(self):
        """Administrative keywords take priority over learning keywords."""
        task = _task("Learn to sync data")  # contains both "learn" and "sync"
        goal = _goal()
        context = _context()
        # Administrative is checked first
        assert select_execution_mode(task, goal, context) == ExecutionMode.JANUS


# ── Support mode selection ──────────────────────────────────────────────────


class TestSupportModeSelection:
    def test_no_evidence_returns_explain(self):
        task = _task("Learn Python")
        goal = _goal()
        context = _context(skill_evidence_count=0)
        assert select_support_mode(task, goal, context) == SupportMode.EXPLAIN

    def test_stalled_goal_returns_coach(self):
        task = _task("Practice algorithms")
        goal = _goal()
        context = _context(skill_evidence_count=3, goal_stalled=True)
        assert select_support_mode(task, goal, context) == SupportMode.COACH

    def test_healthy_goal_with_evidence_returns_scaffold(self):
        task = _task("Practice algorithms")
        goal = _goal()
        context = _context(skill_evidence_count=3, goal_health="healthy")
        assert select_support_mode(task, goal, context) == SupportMode.SCAFFOLD

    def test_janus_execution_returns_execute(self):
        task = _task("Sync data")
        goal = _goal()
        context = _context()
        assert select_support_mode(
            task, goal, context, execution_mode=ExecutionMode.JANUS
        ) == SupportMode.EXECUTE

    def test_review_phase_with_healthy_goal_returns_scaffold(self):
        """Per design doc, SCAFFOLD (rule 3) takes precedence over REVIEW (rule 4)."""
        task = _task("Code review", extra_metadata=["review"])
        goal = _goal()
        context = _context(skill_evidence_count=3, goal_health="healthy")
        assert select_support_mode(task, goal, context) == SupportMode.SCAFFOLD

    def test_review_phase_with_completed_goal_returns_review(self):
        """When goal is completed, rule 3 doesn't match, so rule 4 (REVIEW) is reached."""
        task = _task("Code review", extra_metadata=["review"])
        goal = _goal()
        context = _context(skill_evidence_count=3, goal_health="completed")
        assert select_support_mode(task, goal, context) == SupportMode.REVIEW

    def test_default_returns_scaffold(self):
        task = _task("Design architecture")
        goal = _goal()
        context = _context(skill_evidence_count=1, goal_health="watch")
        assert select_support_mode(task, goal, context) == SupportMode.SCAFFOLD


# ── TaskAgency classification ────────────────────────────────────────────────


class TestTaskAgencyClassification:
    def test_classify_administrative_task(self):
        task = _task("Sync data files")
        goal = _goal()
        context = _context()
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.JANUS
        assert agency.support_mode == SupportMode.EXECUTE
        assert agency.confidence > 0.0
        assert "administrative" in agency.reason.lower()

    def test_classify_learning_task_no_evidence(self):
        task = _task("Learn Python")
        goal = _goal()
        context = _context(skill_evidence_count=0)
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.USER
        assert agency.support_mode == SupportMode.EXPLAIN

    def test_classify_learning_task_with_evidence(self):
        task = _task("Practice algorithms")
        goal = _goal()
        context = _context(skill_evidence_count=5, goal_health="healthy")
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.USER
        assert agency.support_mode == SupportMode.SCAFFOLD

    def test_classify_stalled_goal(self):
        task = _task("Practice algorithms")
        goal = _goal()
        context = _context(skill_evidence_count=3, goal_stalled=True)
        agency = classify_task(task, goal, context)
        assert agency.support_mode == SupportMode.COACH

    def test_classify_deterministic(self):
        """Same inputs → same output."""
        task = _task("Learn Python")
        goal = _goal()
        context = _context(skill_evidence_count=0)
        agency1 = classify_task(task, goal, context)
        agency2 = classify_task(task, goal, context)
        assert agency1.execution_mode == agency2.execution_mode
        assert agency1.support_mode == agency2.support_mode
        assert agency1.confidence == agency2.confidence

    def test_classify_next_action_wrapper(self):
        task = _task("Sync data")
        goal = _goal()
        context = _context()
        agency = classify_next_action(task, goal, context)
        assert agency.execution_mode == ExecutionMode.JANUS
        assert agency.support_mode == SupportMode.EXECUTE


# ── AgencyContext derivation ────────────────────────────────────────────────


class TestAgencyContextDerivation:
    def test_derive_with_defaults(self):
        context = derive_agency_context()
        assert context.skill_evidence_count == 0
        assert context.goal_health == "healthy"
        assert context.goal_stalled is False
        assert context.task_completion_history == 0

    def test_derive_with_values(self):
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


# ── Confidence calculation ───────────────────────────────────────────────────


class TestConfidenceCalculation:
    def test_base_confidence(self):
        task = _task("Learn Python")
        goal = _goal()
        context = _context()
        confidence = _compute_confidence(
            task, goal, context, ExecutionMode.USER, SupportMode.EXPLAIN
        )
        assert confidence == 0.5

    def test_evidence_increases_confidence(self):
        task = _task("Learn Python")
        goal = _goal()
        context = _context(skill_evidence_count=5)
        confidence = _compute_confidence(
            task, goal, context, ExecutionMode.USER, SupportMode.SCAFFOLD
        )
        assert confidence > 0.5
        assert confidence <= 1.0

    def test_confidence_capped_at_1(self):
        task = _task("Learn Python")
        goal = _goal()
        context = _context(skill_evidence_count=100, task_completion_history=100)
        confidence = _compute_confidence(
            task, goal, context, ExecutionMode.USER, SupportMode.SCAFFOLD
        )
        assert confidence == 1.0


# ── Helper functions ─────────────────────────────────────────────────────────


class TestHelperFunctions:
    def test_is_high_complexity_with_long_estimate(self):
        task = _task("Design system", extra_metadata=["estimate: 8 hours"])
        assert _is_high_complexity(task) is True

    def test_is_high_complexity_with_short_estimate(self):
        task = _task("Fix bug", extra_metadata=["estimate: 2 hours"])
        assert _is_high_complexity(task) is False

    def test_is_high_complexity_no_metadata(self):
        task = _task("Fix bug")
        assert _is_high_complexity(task) is False

    def test_is_review_phase_with_review_metadata(self):
        task = _task("Code review", extra_metadata=["review"])
        assert _is_review_phase(task) is True

    def test_is_review_phase_without_review_metadata(self):
        task = _task("Code review")
        assert _is_review_phase(task) is False


# ── Integration scenarios ────────────────────────────────────────────────────


class TestIntegrationScenarios:
    def test_admin_task_full_pipeline(self):
        """Administrative task → JANUS + EXECUTE."""
        task = _task("Sync data files")
        goal = _goal()
        context = _context()
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.JANUS
        assert agency.support_mode == SupportMode.EXECUTE
        assert agency.confidence >= 0.5

    def test_learning_task_no_evidence_full_pipeline(self):
        """Learning task with no evidence → USER + EXPLAIN."""
        task = _task("Learn Rust")
        goal = _goal()
        context = _context(skill_evidence_count=0)
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.USER
        assert agency.support_mode == SupportMode.EXPLAIN

    def test_learning_task_with_evidence_full_pipeline(self):
        """Learning task with evidence → USER + SCAFFOLD."""
        task = _task("Practice algorithms")
        goal = _goal()
        context = _context(skill_evidence_count=5, goal_health="healthy")
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.USER
        assert agency.support_mode == SupportMode.SCAFFOLD

    def test_stalled_goal_full_pipeline(self):
        """Stalled goal with evidence → COACH."""
        task = _task("Practice algorithms")
        goal = _goal()
        context = _context(skill_evidence_count=3, goal_stalled=True)
        agency = classify_task(task, goal, context)
        assert agency.support_mode == SupportMode.COACH

    def test_high_complexity_full_pipeline(self):
        """High complexity task → COLLABORATIVE."""
        task = _task("Design distributed system", extra_metadata=["estimate: 12 hours"])
        goal = _goal()
        context = _context(skill_evidence_count=2, goal_health="healthy")
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.COLLABORATIVE

    def test_routine_task_full_pipeline(self):
        """Routine task → JANUS + EXECUTE."""
        task = _task("Daily standup")
        goal = _goal()
        context = _context()
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.JANUS
        assert agency.support_mode == SupportMode.EXECUTE


# ── derive_next_action agency wiring ─────────────────────────────────────────


def _milestone(title: str, order: int = 0, status: str = "open") -> dict:
    return {"title": title, "goal_title": "G", "status": status, "order": order}


class TestDeriveNextActionAgencyWiring:
    """Tests that agency classification is wired into derive_next_action."""

    def test_no_agency_context_returns_none_agency(self):
        """When agency_context is not provided, action.agency is None."""
        goal = Goal(title="G", milestones=[_milestone("M1")], related_tasks=["T1"])
        tasks = [Task(title="T1")]
        action = derive_next_action(goal, tasks, set(), date.today())
        assert action is not None
        assert action.kind == "task"
        assert action.agency is None

    def test_agency_context_classifies_task(self):
        """When agency_context is provided, action.agency is derived."""
        goal = Goal(title="G", milestones=[_milestone("M1")], related_tasks=["Sync data"])
        tasks = [Task(title="Sync data")]
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")
        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        assert action is not None
        assert action.agency is not None
        assert action.agency.execution_mode == ExecutionMode.JANUS
        assert action.agency.support_mode == SupportMode.EXECUTE

    def test_agency_context_with_learning_task(self):
        """Learning task with agency context → USER + EXPLAIN."""
        goal = Goal(title="G", milestones=[_milestone("M1")], related_tasks=["Learn Python"])
        tasks = [Task(title="Learn Python")]
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")
        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        assert action is not None
        assert action.agency.execution_mode == ExecutionMode.USER
        assert action.agency.support_mode == SupportMode.EXPLAIN

    def test_agency_context_with_high_complexity_task(self):
        """High complexity task with agency context → COLLABORATIVE."""
        goal = Goal(title="G", milestones=[_milestone("M1")], related_tasks=["Design system"])
        tasks = [Task(title="Design system", extra_metadata=["estimate: 8 hours"])]
        context = AgencyContext(skill_evidence_count=2, goal_health="healthy")
        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        assert action is not None
        assert action.agency.execution_mode == ExecutionMode.COLLABORATIVE

    def test_agency_context_milestone_action_has_no_agency(self):
        """Milestone/project actions don't have agency (only tasks do)."""
        goal = Goal(title="G", milestones=[_milestone("M1")], related_tasks=[])
        tasks: list[Task] = []
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")
        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        assert action is not None
        assert action.kind == "milestone"
        assert action.agency is None

    def test_agency_confidence_populated(self):
        """Agency confidence is computed and populated."""
        goal = Goal(title="G", milestones=[_milestone("M1")], related_tasks=["Sync data"])
        tasks = [Task(title="Sync data")]
        context = AgencyContext(skill_evidence_count=3, goal_health="healthy", task_completion_history=5)
        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        assert action is not None
        assert action.agency is not None
        assert action.agency.confidence > 0.5

    def test_agency_reason_populated(self):
        """Agency reason string is populated."""
        goal = Goal(title="G", milestones=[_milestone("M1")], related_tasks=["Sync data"])
        tasks = [Task(title="Sync data")]
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")
        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        assert action is not None
        assert action.agency is not None
        assert len(action.agency.reason) > 0


# ── recommend_tasks agency wiring ────────────────────────────────────────────


class TestRecommendTasksAgencyWiring:
    """Tests that agency classification is wired into recommend_tasks."""

    def test_no_agency_context_returns_none_agency(self):
        """When agency_context is not provided, recommendation.agency is None."""
        goal = Goal(title="G", milestones=[_milestone("M1")], related_tasks=["T1"])
        tasks = [Task(title="T1")]
        result = recommend_tasks([goal], tasks, set(), date.today())
        assert len(result) > 0
        assert result[0].agency is None

    def test_agency_context_classifies_task(self):
        """When agency_context is provided, recommendation.agency is derived."""
        goal = Goal(title="G", milestones=[_milestone("M1")], related_tasks=["Sync data"])
        tasks = [Task(title="Sync data")]
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")
        result = recommend_tasks([goal], tasks, set(), date.today(), agency_context=context)
        assert len(result) > 0
        assert result[0].agency is not None
        assert result[0].agency.execution_mode == ExecutionMode.JANUS
        assert result[0].agency.support_mode == SupportMode.EXECUTE

    def test_agency_context_with_learning_task(self):
        """Learning task with agency context → USER + EXPLAIN."""
        goal = Goal(title="G", milestones=[_milestone("M1")], related_tasks=["Learn Python"])
        tasks = [Task(title="Learn Python")]
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")
        result = recommend_tasks([goal], tasks, set(), date.today(), agency_context=context)
        assert len(result) > 0
        assert result[0].agency.execution_mode == ExecutionMode.USER
        assert result[0].agency.support_mode == SupportMode.EXPLAIN

    def test_agency_context_with_high_complexity_task(self):
        """High complexity task with agency context → COLLABORATIVE."""
        goal = Goal(
            title="G",
            milestones=[_milestone("M1")],
            related_tasks=["Design system"],
        )
        tasks = [Task(title="Design system", extra_metadata=["estimate: 8 hours"])]
        context = AgencyContext(skill_evidence_count=2, goal_health="healthy")
        result = recommend_tasks([goal], tasks, set(), date.today(), agency_context=context)
        assert len(result) > 0
        assert result[0].agency.execution_mode == ExecutionMode.COLLABORATIVE

    def test_agency_confidence_populated(self):
        """Agency confidence is computed and populated in recommendations."""
        goal = Goal(title="G", milestones=[_milestone("M1")], related_tasks=["Sync data"])
        tasks = [Task(title="Sync data")]
        context = AgencyContext(
            skill_evidence_count=3,
            goal_health="healthy",
            task_completion_history=5,
        )
        result = recommend_tasks([goal], tasks, set(), date.today(), agency_context=context)
        assert len(result) > 0
        assert result[0].agency is not None
        assert result[0].agency.confidence > 0.5

    def test_agency_reason_populated(self):
        """Agency reason string is populated in recommendations."""
        goal = Goal(title="G", milestones=[_milestone("M1")], related_tasks=["Sync data"])
        tasks = [Task(title="Sync data")]
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")
        result = recommend_tasks([goal], tasks, set(), date.today(), agency_context=context)
        assert len(result) > 0
        assert result[0].agency is not None
        assert len(result[0].agency.reason) > 0
