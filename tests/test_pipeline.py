"""Tests for the Planner → Agency → Policy pipeline.

Covers:
- PolicyEngine: classify() / evaluate() / check_approval()
- Pipeline: NextAction → PipelineResult (run_pipeline, enforce_pipeline)
- Full integration: Planner derive_next_action → Agency classify → Policy classify
"""

from datetime import date

import pytest

from janus.domain.planning import NextAction, derive_next_action
from janus.models.execution_mode import ExecutionMode
from janus.models.goal import Goal
from janus.models.policy import (
    ClassificationCategory,
    ImpactLevel,
    PolicyAction,
    PolicyDecision,
    RiskLevel,
)
from janus.models.support_mode import SupportMode
from janus.models.task import Task
from janus.models.task_agency import TaskAgency
from janus.services.agency_planning import AgencyContext, classify_task
from janus.services.pipeline import (
    PipelineEnforcementError,
    PipelineResult,
    _execution_mode_to_risk,
    _support_mode_to_impact,
    enforce_pipeline,
    run_pipeline,
)
from janus.services.policy_engine import PolicyEngine


# ── Helpers ──────────────────────────────────────────────────────────────────


def _task(title: str, **kwargs) -> Task:
    return Task(title=title, **kwargs)


def _goal(title: str = "Test Goal", **kwargs) -> Goal:
    return Goal(title=title, **kwargs)


def _milestone(title: str, order: int = 0, status: str = "open") -> dict:
    return {"title": title, "goal_title": "G", "status": status, "order": order}


def _context(**kwargs) -> AgencyContext:
    return AgencyContext(**kwargs)


def _agency(
    execution_mode: ExecutionMode = ExecutionMode.USER,
    support_mode: SupportMode = SupportMode.EXPLAIN,
    confidence: float = 0.5,
) -> TaskAgency:
    return TaskAgency(
        execution_mode=execution_mode,
        support_mode=support_mode,
        reason="Test classification",
        confidence=confidence,
    )


def _next_action(
    title: str = "Test action",
    kind: str = "task",
    agency: TaskAgency | None = None,
) -> NextAction:
    return NextAction(
        title=title,
        kind=kind,
        reason="Test reason",
        goal_title="Test Goal",
        agency=agency,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Mapping function tests
# ═══════════════════════════════════════════════════════════════════════════


class TestExecutionModeToRisk:
    """_execution_mode_to_risk maps ExecutionMode → RiskLevel."""

    def test_user_is_low_risk(self):
        assert _execution_mode_to_risk(ExecutionMode.USER) == RiskLevel.LOW

    def test_janus_is_medium_risk(self):
        assert _execution_mode_to_risk(ExecutionMode.JANUS) == RiskLevel.MEDIUM

    def test_collaborative_is_medium_risk(self):
        assert _execution_mode_to_risk(ExecutionMode.COLLABORATIVE) == RiskLevel.MEDIUM


class TestSupportModeToImpact:
    """_support_mode_to_impact maps SupportMode → ImpactLevel."""

    def test_explain_is_low_impact(self):
        assert _support_mode_to_impact(SupportMode.EXPLAIN) == ImpactLevel.LOW

    def test_coach_is_low_impact(self):
        assert _support_mode_to_impact(SupportMode.COACH) == ImpactLevel.LOW

    def test_scaffold_is_medium_impact(self):
        assert _support_mode_to_impact(SupportMode.SCAFFOLD) == ImpactLevel.MEDIUM

    def test_review_is_medium_impact(self):
        assert _support_mode_to_impact(SupportMode.REVIEW) == ImpactLevel.MEDIUM

    def test_execute_is_high_impact(self):
        assert _support_mode_to_impact(SupportMode.EXECUTE) == ImpactLevel.HIGH


# ═══════════════════════════════════════════════════════════════════════════
# PolicyEngine unit tests (master API)
# ═══════════════════════════════════════════════════════════════════════════


class TestPolicyEngineClassify:
    """PolicyEngine.classify() maps (action, risk, impact) → ClassificationCategory."""

    def test_low_risk_execute_is_auto_allowed(self):
        engine = PolicyEngine()
        category = engine.classify(PolicyAction.EXECUTE, RiskLevel.LOW, ImpactLevel.LOW)
        assert category == ClassificationCategory.AUTO_ALLOWED

    def test_medium_risk_execute_requires_approval(self):
        engine = PolicyEngine()
        category = engine.classify(PolicyAction.EXECUTE, RiskLevel.MEDIUM, ImpactLevel.LOW)
        assert category == ClassificationCategory.APPROVAL_REQUIRED

    def test_high_risk_high_impact_delete_is_user_only(self):
        engine = PolicyEngine()
        category = engine.classify(PolicyAction.DELETE, RiskLevel.HIGH, ImpactLevel.HIGH)
        assert category == ClassificationCategory.USER_ONLY

    def test_read_is_auto_allowed(self):
        engine = PolicyEngine()
        category = engine.classify(PolicyAction.READ, RiskLevel.LOW, ImpactLevel.LOW)
        assert category == ClassificationCategory.AUTO_ALLOWED

    def test_approve_always_requires_approval(self):
        engine = PolicyEngine()
        category = engine.classify(PolicyAction.APPROVE, RiskLevel.LOW, ImpactLevel.LOW)
        assert category == ClassificationCategory.APPROVAL_REQUIRED


class TestPolicyEngineEvaluate:
    """PolicyEngine.evaluate() returns PolicyDecision."""

    def test_low_risk_execute_allows(self):
        engine = PolicyEngine()
        decision = engine.evaluate(PolicyAction.EXECUTE, RiskLevel.LOW, ImpactLevel.LOW)
        assert decision == PolicyDecision.ALLOW

    def test_medium_risk_execute_asks(self):
        engine = PolicyEngine()
        decision = engine.evaluate(PolicyAction.EXECUTE, RiskLevel.MEDIUM, ImpactLevel.LOW)
        assert decision == PolicyDecision.ASK

    def test_high_risk_high_impact_delete_denies(self):
        engine = PolicyEngine()
        decision = engine.evaluate(PolicyAction.DELETE, RiskLevel.HIGH, ImpactLevel.HIGH)
        assert decision == PolicyDecision.DENY


class TestPolicyEngineCheckApproval:
    """PolicyEngine.check_approval() returns bool."""

    def test_low_risk_execute_is_approved(self):
        engine = PolicyEngine()
        assert engine.check_approval(PolicyAction.EXECUTE, RiskLevel.LOW, ImpactLevel.LOW) is True

    def test_medium_risk_execute_not_approved(self):
        engine = PolicyEngine()
        assert engine.check_approval(PolicyAction.EXECUTE, RiskLevel.MEDIUM, ImpactLevel.LOW) is False


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline unit tests (run_pipeline)
# ═══════════════════════════════════════════════════════════════════════════


class TestRunPipeline:
    """run_pipeline() converts NextAction → PipelineResult."""

    def test_user_explain_should_execute(self):
        """USER + EXPLAIN → low risk + low impact → auto_allowed."""
        action = _next_action(agency=_agency(ExecutionMode.USER, SupportMode.EXPLAIN))
        result = run_pipeline(action)
        assert result.should_execute is True
        assert result.requires_approval is False
        assert result.blocked is False
        assert result.category == ClassificationCategory.AUTO_ALLOWED

    def test_user_coach_should_execute(self):
        """USER + COACH → low risk + low impact → auto_allowed."""
        action = _next_action(agency=_agency(ExecutionMode.USER, SupportMode.COACH))
        result = run_pipeline(action)
        assert result.should_execute is True
        assert result.category == ClassificationCategory.AUTO_ALLOWED

    def test_janus_execute_requires_approval(self):
        """JANUS + EXECUTE → medium risk + high impact → approval_required."""
        action = _next_action(agency=_agency(ExecutionMode.JANUS, SupportMode.EXECUTE))
        result = run_pipeline(action)
        assert result.should_execute is False
        assert result.requires_approval is True
        assert result.blocked is False
        assert result.category == ClassificationCategory.APPROVAL_REQUIRED

    def test_janus_scaffold_requires_approval(self):
        """JANUS + SCAFFOLD → medium risk + medium impact → approval_required."""
        action = _next_action(agency=_agency(ExecutionMode.JANUS, SupportMode.SCAFFOLD))
        result = run_pipeline(action)
        assert result.should_execute is False
        assert result.requires_approval is True

    def test_no_agency_allows_by_default(self):
        """Milestone/project actions (no agency) → allow."""
        action = _next_action(kind="milestone", agency=None)
        result = run_pipeline(action)
        assert result.should_execute is True
        assert result.decision == PolicyDecision.ALLOW
        assert result.category == ClassificationCategory.AUTO_ALLOWED

    def test_result_carries_action_metadata(self):
        action = _next_action(title="Sync data", agency=_agency(ExecutionMode.USER, SupportMode.EXPLAIN))
        result = run_pipeline(action)
        assert result.action_title == "Sync data"
        assert result.action_kind == "task"

    def test_result_carries_agency(self):
        agency = _agency(ExecutionMode.USER, SupportMode.EXPLAIN)
        action = _next_action(agency=agency)
        result = run_pipeline(action)
        assert result.agency is agency

    def test_result_is_dataclass(self):
        action = _next_action(agency=_agency(ExecutionMode.USER, SupportMode.EXPLAIN))
        result = run_pipeline(action)
        assert isinstance(result, PipelineResult)
        assert hasattr(result, "action_title")
        assert hasattr(result, "action_kind")
        assert hasattr(result, "should_execute")
        assert hasattr(result, "requires_approval")
        assert hasattr(result, "blocked")
        assert hasattr(result, "decision")
        assert hasattr(result, "category")
        assert hasattr(result, "agency")


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline unit tests (enforce_pipeline)
# ═══════════════════════════════════════════════════════════════════════════


class TestEnforcePipeline:
    """enforce_pipeline() raises on block/approval, returns decision on allow."""

    def test_allow_returns_decision(self):
        action = _next_action(agency=_agency(ExecutionMode.USER, SupportMode.EXPLAIN))
        decision = enforce_pipeline(action)
        assert decision == PolicyDecision.ALLOW

    def test_require_approval_raises(self):
        action = _next_action(agency=_agency(ExecutionMode.JANUS, SupportMode.EXECUTE))
        with pytest.raises(PipelineEnforcementError) as exc_info:
            enforce_pipeline(action)
        assert exc_info.value.requires_approval is True
        assert "approval" in str(exc_info.value).lower()

    def test_no_agency_returns_allow(self):
        action = _next_action(agency=None)
        decision = enforce_pipeline(action)
        assert decision == PolicyDecision.ALLOW


# ═══════════════════════════════════════════════════════════════════════════
# Full integration: Planner → Agency → Policy
# ═══════════════════════════════════════════════════════════════════════════


class TestFullPipelineIntegration:
    """End-to-end: derive_next_action → classify_task → PolicyEngine."""

    def test_administrative_task_full_pipeline(self):
        """Administrative task → JANUS/EXECUTE → medium risk + high impact → approval_required."""
        goal = Goal(
            title="G",
            milestones=[_milestone("M1")],
            related_tasks=["Sync data files"],
        )
        tasks = [Task(title="Sync data files")]
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")

        # Stage 1: Planner derives next action (with agency classification)
        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        assert action is not None
        assert action.agency is not None
        assert action.agency.execution_mode == ExecutionMode.JANUS
        assert action.agency.support_mode == SupportMode.EXECUTE

        # Stage 2: Pipeline evaluates policy
        result = run_pipeline(action)
        assert result.should_execute is False
        assert result.requires_approval is True
        assert result.category == ClassificationCategory.APPROVAL_REQUIRED

    def test_learning_task_full_pipeline(self):
        """Learning task → USER/EXPLAIN → low risk + low impact → auto_allowed."""
        goal = Goal(
            title="G",
            milestones=[_milestone("M1")],
            related_tasks=["Learn Python"],
        )
        tasks = [Task(title="Learn Python")]
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")

        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        assert action is not None
        assert action.agency.execution_mode == ExecutionMode.USER
        assert action.agency.support_mode == SupportMode.EXPLAIN

        result = run_pipeline(action)
        assert result.should_execute is True
        assert result.category == ClassificationCategory.AUTO_ALLOWED

    def test_routine_task_full_pipeline(self):
        """Routine task → JANUS/EXECUTE → medium risk + high impact → approval_required."""
        goal = Goal(
            title="G",
            milestones=[_milestone("M1")],
            related_tasks=["Daily standup"],
        )
        tasks = [Task(title="Daily standup")]
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")

        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        assert action is not None
        assert action.agency.execution_mode == ExecutionMode.JANUS

        result = run_pipeline(action)
        assert result.should_execute is False
        assert result.requires_approval is True

    def test_high_complexity_full_pipeline(self):
        """High complexity task → COLLABORATIVE → medium risk → approval_required."""
        goal = Goal(
            title="G",
            milestones=[_milestone("M1")],
            related_tasks=["Design system"],
        )
        tasks = [Task(title="Design system", extra_metadata=["estimate: 8 hours"])]
        context = AgencyContext(skill_evidence_count=2, goal_health="healthy")

        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        assert action is not None
        assert action.agency.execution_mode == ExecutionMode.COLLABORATIVE

        result = run_pipeline(action)
        assert result.should_execute is False
        assert result.requires_approval is True

    def test_milestone_action_no_agency_allows(self):
        """Milestone action (no agency) → allow by default."""
        goal = Goal(
            title="G",
            milestones=[_milestone("M1")],
            related_tasks=[],
        )
        tasks: list[Task] = []
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")

        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        assert action is not None
        assert action.kind == "milestone"
        assert action.agency is None

        result = run_pipeline(action)
        assert result.should_execute is True
        assert result.category == ClassificationCategory.AUTO_ALLOWED

    def test_enforce_pipeline_raises_for_janus_execute(self):
        """enforce_pipeline raises for JANUS + EXECUTE (medium risk + high impact)."""
        goal = Goal(
            title="G",
            milestones=[_milestone("M1")],
            related_tasks=["Sync data"],
        )
        tasks = [Task(title="Sync data")]
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")

        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        assert action is not None
        assert action.agency.execution_mode == ExecutionMode.JANUS
        assert action.agency.support_mode == SupportMode.EXECUTE

        with pytest.raises(PipelineEnforcementError) as exc_info:
            enforce_pipeline(action)
        assert exc_info.value.requires_approval is True
        assert "approval" in str(exc_info.value).lower()

    def test_classify_task_directly_feeds_policy(self):
        """Direct classify_task → PolicyEngine path (without Planner)."""
        task = _task("Sync data files")
        goal = _goal()
        context = _context()

        # Stage 2: Agency classification
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.JANUS
        assert agency.support_mode == SupportMode.EXECUTE

        # Stage 3: Policy evaluation via mapping
        risk = _execution_mode_to_risk(agency.execution_mode)
        impact = _support_mode_to_impact(agency.support_mode)
        engine = PolicyEngine()
        category = engine.classify(PolicyAction.EXECUTE, risk, impact)
        assert category == ClassificationCategory.APPROVAL_REQUIRED

    def test_user_explain_full_pipeline_auto_allowed(self):
        """USER + EXPLAIN → auto_allowed (the only auto-allowed path)."""
        goal = Goal(
            title="G",
            milestones=[_milestone("M1")],
            related_tasks=["Learn Python"],
        )
        tasks = [Task(title="Learn Python")]
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")

        action = derive_next_action(goal, tasks, set(), date.today(), agency_context=context)
        assert action is not None

        result = run_pipeline(action)
        assert result.should_execute is True
        assert result.category == ClassificationCategory.AUTO_ALLOWED
        assert result.decision == PolicyDecision.ALLOW
