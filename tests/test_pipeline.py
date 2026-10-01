"""Tests for the Planner → Agency → Policy pipeline.

Covers:
- PolicyEngine: classification → PolicyDecision mapping
- EnforcementGate: enforce() → allow / require_approval / block
- Pipeline: NextAction → PipelineResult (run_pipeline, enforce_pipeline)
- Full integration: Planner derive_next_action → Agency classify → Policy evaluate
"""

from datetime import date

import pytest

from janus.domain.planning import NextAction, derive_next_action
from janus.models.execution_mode import ExecutionMode
from janus.models.goal import Goal
from janus.models.milestone import Milestone
from janus.models.policy import PolicyDecision, PolicyRule
from janus.models.support_mode import SupportMode
from janus.models.task import Task
from janus.models.task_agency import TaskAgency
from janus.services.agency_planning import AgencyContext, classify_task
from janus.services.pipeline import PipelineResult, enforce_pipeline, run_pipeline
from janus.services.policy_engine import (
    EnforcementGate,
    PolicyEnforcementError,
    PolicyEngine,
)


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
# PolicyEngine unit tests
# ═══════════════════════════════════════════════════════════════════════════


class TestPolicyEngine:
    """PolicyEngine.evaluate() maps TaskAgency → PolicyDecision."""

    def test_user_execution_allows(self):
        engine = PolicyEngine()
        agency = _agency(ExecutionMode.USER, SupportMode.EXPLAIN)
        decision = engine.evaluate(agency)
        assert decision.verdict == "allow"
        assert decision.risk_level == "low"
        assert decision.rule_id == "R-USER"

    def test_collaborative_execution_allows(self):
        engine = PolicyEngine()
        agency = _agency(ExecutionMode.COLLABORATIVE, SupportMode.SCAFFOLD)
        decision = engine.evaluate(agency)
        assert decision.verdict == "allow"
        assert decision.rule_id == "R-COLLAB"

    def test_janus_execute_allows(self):
        engine = PolicyEngine()
        agency = _agency(ExecutionMode.JANUS, SupportMode.EXECUTE)
        decision = engine.evaluate(agency)
        assert decision.verdict == "allow"
        assert decision.rule_id == "R-JANUS-EXEC"

    def test_janus_non_execute_requires_approval(self):
        engine = PolicyEngine()
        for support_mode in (
            SupportMode.EXPLAIN,
            SupportMode.COACH,
            SupportMode.SCAFFOLD,
            SupportMode.REVIEW,
        ):
            agency = _agency(ExecutionMode.JANUS, support_mode)
            decision = engine.evaluate(agency)
            assert decision.verdict == "require_approval", (
                f"Expected require_approval for JANUS/{support_mode.value}, "
                f"got {decision.verdict}"
            )
            assert decision.rule_id == "R-JANUS-REVIEW"

    def test_unknown_classification_fails_open(self):
        """Unknown classification → default allow (fail-open)."""
        engine = PolicyEngine(rules=[])  # no rules
        agency = _agency(ExecutionMode.JANUS, SupportMode.EXECUTE)
        decision = engine.evaluate(agency)
        assert decision.verdict == "allow"
        assert decision.rule_id == "R-DEFAULT"

    def test_custom_rules_override_default(self):
        """Custom rules take precedence over defaults."""
        custom_rules = [
            PolicyRule(
                rule_id="R-CUSTOM",
                action="execute",
                context={"execution_mode": ExecutionMode.USER},
                risk_level="critical",
                verdict="block",
                rationale="Custom block rule",
            )
        ]
        engine = PolicyEngine(rules=custom_rules)
        agency = _agency(ExecutionMode.USER, SupportMode.EXPLAIN)
        decision = engine.evaluate(agency)
        assert decision.verdict == "block"
        assert decision.rule_id == "R-CUSTOM"

    def test_decision_has_enforcement_point(self):
        engine = PolicyEngine()
        agency = _agency(ExecutionMode.USER, SupportMode.EXPLAIN)
        decision = engine.evaluate(agency)
        assert decision.enforcement_point == "pre_execution"

    def test_decision_has_rationale(self):
        engine = PolicyEngine()
        agency = _agency(ExecutionMode.USER, SupportMode.EXPLAIN)
        decision = engine.evaluate(agency)
        assert len(decision.rationale) > 0


# ═══════════════════════════════════════════════════════════════════════════
# EnforcementGate unit tests
# ═══════════════════════════════════════════════════════════════════════════


class TestEnforcementGate:
    """EnforcementGate.enforce() raises PolicyEnforcementError on block/approval."""

    def test_allow_returns_decision(self):
        gate = EnforcementGate()
        agency = _agency(ExecutionMode.USER, SupportMode.EXPLAIN)
        decision = gate.enforce(agency)
        assert decision.verdict == "allow"

    def test_require_approval_raises(self):
        gate = EnforcementGate()
        agency = _agency(ExecutionMode.JANUS, SupportMode.SCAFFOLD)
        with pytest.raises(PolicyEnforcementError) as exc_info:
            gate.enforce(agency)
        assert exc_info.value.requires_approval is True
        assert "require approval" in str(exc_info.value)

    def test_block_raises(self):
        custom_rules = [
            PolicyRule(
                rule_id="R-BLOCK",
                action="execute",
                context={"execution_mode": ExecutionMode.USER},
                risk_level="critical",
                verdict="block",
                rationale="Blocked",
            )
        ]
        gate = EnforcementGate(engine=PolicyEngine(rules=custom_rules))
        agency = _agency(ExecutionMode.USER, SupportMode.EXPLAIN)
        with pytest.raises(PolicyEnforcementError) as exc_info:
            gate.enforce(agency)
        assert exc_info.value.requires_approval is False
        assert "Blocked" in str(exc_info.value)

    def test_error_has_risk_level(self):
        gate = EnforcementGate()
        agency = _agency(ExecutionMode.JANUS, SupportMode.SCAFFOLD)
        with pytest.raises(PolicyEnforcementError) as exc_info:
            gate.enforce(agency)
        assert exc_info.value.risk_level == "high"


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline unit tests (run_pipeline)
# ═══════════════════════════════════════════════════════════════════════════


class TestRunPipeline:
    """run_pipeline() converts NextAction → PipelineResult."""

    def test_user_action_should_execute(self):
        action = _next_action(agency=_agency(ExecutionMode.USER, SupportMode.EXPLAIN))
        result = run_pipeline(action)
        assert result.should_execute is True
        assert result.requires_approval is False
        assert result.blocked is False
        assert result.decision.verdict == "allow"

    def test_janus_execute_should_execute(self):
        action = _next_action(agency=_agency(ExecutionMode.JANUS, SupportMode.EXECUTE))
        result = run_pipeline(action)
        assert result.should_execute is True
        assert result.decision.verdict == "allow"

    def test_janus_scaffold_requires_approval(self):
        action = _next_action(agency=_agency(ExecutionMode.JANUS, SupportMode.SCAFFOLD))
        result = run_pipeline(action)
        assert result.should_execute is False
        assert result.requires_approval is True
        assert result.blocked is False

    def test_no_agency_allows_by_default(self):
        """Milestone/project actions (no agency) → allow."""
        action = _next_action(kind="milestone", agency=None)
        result = run_pipeline(action)
        assert result.should_execute is True
        assert result.decision.rule_id == "R-NO-AGENCY"

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


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline unit tests (enforce_pipeline)
# ═══════════════════════════════════════════════════════════════════════════


class TestEnforcePipeline:
    """enforce_pipeline() raises on block/approval, returns decision on allow."""

    def test_allow_returns_decision(self):
        action = _next_action(agency=_agency(ExecutionMode.USER, SupportMode.EXPLAIN))
        decision = enforce_pipeline(action)
        assert decision.verdict == "allow"

    def test_require_approval_raises(self):
        action = _next_action(agency=_agency(ExecutionMode.JANUS, SupportMode.SCAFFOLD))
        with pytest.raises(PolicyEnforcementError):
            enforce_pipeline(action)

    def test_no_agency_returns_allow(self):
        action = _next_action(agency=None)
        decision = enforce_pipeline(action)
        assert decision.verdict == "allow"


# ═══════════════════════════════════════════════════════════════════════════
# Full integration: Planner → Agency → Policy
# ═══════════════════════════════════════════════════════════════════════════


class TestFullPipelineIntegration:
    """End-to-end: derive_next_action → classify_task → PolicyEngine."""

    def test_administrative_task_full_pipeline(self):
        """Administrative task → JANUS/EXECUTE → allow."""
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
        assert result.should_execute is True
        assert result.decision.verdict == "allow"

    def test_learning_task_full_pipeline(self):
        """Learning task → USER/EXPLAIN → allow."""
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

    def test_routine_task_full_pipeline(self):
        """Routine task → JANUS/EXECUTE → allow."""
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
        assert result.should_execute is True

    def test_high_complexity_full_pipeline(self):
        """High complexity task → COLLABORATIVE → allow."""
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
        assert result.should_execute is True

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
        assert result.decision.rule_id == "R-NO-AGENCY"

    def test_enforce_pipeline_blocks_janus_non_execute(self):
        """enforce_pipeline raises for JANUS + non-EXECUTE support.

        Note: The real Agency always produces EXECUTE support for JANUS
        execution (select_support_mode returns EXECUTE immediately). This
        test constructs the TaskAgency directly to verify the Policy
        engine's handling of the JANUS + non-EXECUTE combination.
        """
        agency = _agency(ExecutionMode.JANUS, SupportMode.SCAFFOLD)
        action = _next_action(agency=agency)

        with pytest.raises(PolicyEnforcementError) as exc_info:
            enforce_pipeline(action)
        assert exc_info.value.requires_approval is True

    def test_classify_task_directly_feeds_policy(self):
        """Direct classify_task → PolicyEngine path (without Planner)."""
        task = _task("Sync data files")
        goal = _goal()
        context = _context()

        # Stage 2: Agency classification
        agency = classify_task(task, goal, context)
        assert agency.execution_mode == ExecutionMode.JANUS
        assert agency.support_mode == SupportMode.EXECUTE

        # Stage 3: Policy evaluation
        engine = PolicyEngine()
        decision = engine.evaluate(agency)
        assert decision.verdict == "allow"

    def test_pipeline_result_is_dataclass(self):
        """PipelineResult is a proper dataclass with expected fields."""
        action = _next_action(agency=_agency(ExecutionMode.USER, SupportMode.EXPLAIN))
        result = run_pipeline(action)
        assert isinstance(result, PipelineResult)
        assert hasattr(result, "action_title")
        assert hasattr(result, "action_kind")
        assert hasattr(result, "should_execute")
        assert hasattr(result, "requires_approval")
        assert hasattr(result, "blocked")
        assert hasattr(result, "decision")
        assert hasattr(result, "agency")


# ═══════════════════════════════════════════════════════════════════════════
# PolicyDecision model tests
# ═══════════════════════════════════════════════════════════════════════════


class TestPolicyDecisionModel:
    """PolicyDecision dataclass contract."""

    def test_decision_fields(self):
        decision = PolicyDecision(
            rule_id="R1",
            verdict="allow",
            risk_level="low",
            rationale="Test",
            gate_id="G-1",
            enforcement_point="pre_execution",
        )
        assert decision.rule_id == "R1"
        assert decision.verdict == "allow"
        assert decision.risk_level == "low"
        assert decision.gate_id == "G-1"
        assert decision.enforcement_point == "pre_execution"

    def test_decision_optional_fields_default(self):
        decision = PolicyDecision(
            rule_id="R1",
            verdict="allow",
            risk_level="low",
            rationale="Test",
        )
        assert decision.gate_id is None
        assert decision.enforcement_point is None


class TestPolicyRuleModel:
    """PolicyRule dataclass contract."""

    def test_rule_fields(self):
        rule = PolicyRule(
            rule_id="R1",
            action="execute",
            risk_level="medium",
            verdict="allow",
            rationale="Test rule",
            enforcement_point="pre_execution",
        )
        assert rule.rule_id == "R1"
        assert rule.action == "execute"
        assert rule.risk_level == "medium"
        assert rule.verdict == "allow"

    def test_rule_context_defaults_empty(self):
        rule = PolicyRule(rule_id="R1", action="execute")
        assert rule.context == {}
