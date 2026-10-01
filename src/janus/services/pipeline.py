"""Pipeline orchestration: Planner → Agency → Policy.

This module is the integration glue that connects the three upstream
stages of the closed-loop execution pipeline:

1. **Planner** (:mod:`janus.domain.planning`) — derives the next action
   and, when ``AgencyContext`` is provided, classifies it via the Agency.
2. **Agency** (:mod:`janus.services.agency_planning`) — produces a
   :class:`TaskAgency` classification (execution_mode + support_mode).
3. **Policy** (:mod:`janus.services.policy_engine`) — evaluates the
   classification and produces a :class:`PolicyDecision`.

The pipeline consumes a :class:`NextAction` (which already carries the
``agency`` classification from the Planner stage) and produces a
:class:`PipelineResult` that tells the caller whether to proceed with
execution, request approval, or block.

Usage::

    from janus.services.pipeline import run_pipeline

    result = run_pipeline(next_action)
    if result.should_execute:
        # dispatch to Hermes
    elif result.requires_approval:
        # gate on human approval
    else:
        # blocked
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from janus.domain.planning import NextAction
from janus.models.execution_mode import ExecutionMode
from janus.models.policy import (
    ClassificationCategory,
    ImpactLevel,
    PolicyDecision,
    PolicyAction,
    RiskLevel,
)
from janus.models.support_mode import SupportMode
from janus.models.task_agency import TaskAgency
from janus.services.policy_engine import PolicyEngine

logger = logging.getLogger(__name__)


# ── TaskAgency → Policy tuple mapping ────────────────────────────────────────

def _execution_mode_to_risk(mode: ExecutionMode) -> RiskLevel:
    """Map execution mode to risk level.

    USER execution is low risk (user acts, Janus assists).
    JANUS and COLLABORATIVE execution are medium risk (Janus involved).
    """
    if mode == ExecutionMode.USER:
        return RiskLevel.LOW
    return RiskLevel.MEDIUM


def _support_mode_to_impact(mode: SupportMode) -> ImpactLevel:
    """Map support mode to impact level.

    EXPLAIN and COACH are low impact (user still does the work).
    SCAFFOLD and REVIEW are medium impact (Janus provides structure).
    EXECUTE is high impact (Janus does the work).
    """
    if mode in (SupportMode.EXPLAIN, SupportMode.COACH):
        return ImpactLevel.LOW
    if mode in (SupportMode.SCAFFOLD, SupportMode.REVIEW):
        return ImpactLevel.MEDIUM
    return ImpactLevel.HIGH


# ── PipelineResult ──────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    """The outcome of running the Planner → Agency → Policy pipeline.

    Attributes:
        action_title: The title of the action that was evaluated.
        action_kind: The kind of action ("task", "milestone", "project").
        should_execute: Whether the action can proceed to execution.
        requires_approval: Whether the action requires human approval.
        blocked: Whether the action is blocked by policy.
        decision: The PolicyDecision from the Policy stage.
        category: The ClassificationCategory from the Policy stage.
        agency: The TaskAgency classification from the Agency stage.
    """

    action_title: str
    action_kind: str
    should_execute: bool
    requires_approval: bool
    blocked: bool
    decision: PolicyDecision
    category: ClassificationCategory
    agency: TaskAgency | None


# ── Pipeline functions ──────────────────────────────────────────────────────

def run_pipeline(
    action: NextAction,
    *,
    engine: PolicyEngine | None = None,
) -> PipelineResult:
    """Run the Planner → Agency → Policy pipeline for a single action.

    This is the main entry point for the pipeline. It takes a
    :class:`NextAction` (produced by the Planner, with agency
    classification already attached) and runs it through the Policy
    engine to determine whether the action can proceed.

    If the action has no agency classification (e.g. milestone or
    project actions), the pipeline returns a default "allow" result
    without consulting the Policy engine.

    Args:
        action: The next action from the Planner.
        engine: Optional custom PolicyEngine instance.

    Returns:
        A PipelineResult indicating the outcome.
    """
    # If no agency classification, allow by default (milestone/project
    # actions don't have agency — only tasks do).
    if action.agency is None:
        return PipelineResult(
            action_title=action.title,
            action_kind=action.kind,
            should_execute=True,
            requires_approval=False,
            blocked=False,
            decision=PolicyDecision.ALLOW,
            category=ClassificationCategory.AUTO_ALLOWED,
            agency=None,
        )

    # Map TaskAgency → Policy tuple
    risk = _execution_mode_to_risk(action.agency.execution_mode)
    impact = _support_mode_to_impact(action.agency.support_mode)

    # Run the policy engine
    policy_engine = engine if engine is not None else PolicyEngine()
    category = policy_engine.classify(
        PolicyAction.EXECUTE, risk, impact, context=action.title
    )
    decision = policy_engine.evaluate(
        PolicyAction.EXECUTE, risk, impact, context=action.title
    )

    should_execute = category == ClassificationCategory.AUTO_ALLOWED
    requires_approval = category == ClassificationCategory.APPROVAL_REQUIRED
    blocked = category == ClassificationCategory.USER_ONLY

    return PipelineResult(
        action_title=action.title,
        action_kind=action.kind,
        should_execute=should_execute,
        requires_approval=requires_approval,
        blocked=blocked,
        decision=decision,
        category=category,
        agency=action.agency,
    )


class PipelineEnforcementError(Exception):
    """Raised when the pipeline blocks or gates an action.

    Attributes:
        action: The action that was blocked.
        reason: Human-readable explanation.
        risk_level: Risk level of the action.
        requires_approval: Whether the action requires human approval
            (True) vs. is outright blocked (False).
    """

    def __init__(
        self,
        action: str,
        reason: str,
        risk_level: str = "medium",
        requires_approval: bool = False,
    ) -> None:
        self.action = action
        self.reason = reason
        self.risk_level = risk_level
        self.requires_approval = requires_approval
        super().__init__(
            f"Pipeline enforcement failed for {action}: {reason} "
            f"(risk={risk_level}, requires_approval={requires_approval})"
        )


def enforce_pipeline(
    action: NextAction,
    *,
    engine: PolicyEngine | None = None,
) -> PolicyDecision:
    """Run the pipeline and enforce the policy decision.

    Unlike :func:`run_pipeline` (which returns a result object), this
    function raises :class:`PipelineEnforcementError` when the policy
    blocks or requires approval. It is the "strict" variant intended
    for use as a pre-execution gate.

    Args:
        action: The next action from the Planner.
        engine: Optional custom PolicyEngine instance.

    Returns:
        The PolicyDecision (always ALLOW when returned).

    Raises:
        PipelineEnforcementError: When the policy blocks the action
            or requires approval.
    """
    # If no agency classification, allow by default
    if action.agency is None:
        return PolicyDecision.ALLOW

    # Map TaskAgency → Policy tuple
    risk = _execution_mode_to_risk(action.agency.execution_mode)
    impact = _support_mode_to_impact(action.agency.support_mode)

    policy_engine = engine if engine is not None else PolicyEngine()
    decision = policy_engine.evaluate(
        PolicyAction.EXECUTE, risk, impact, context=action.title
    )

    if decision == PolicyDecision.DENY:
        raise PipelineEnforcementError(
            action=action.title,
            reason=f"Policy denied execution of {action.title!r}",
            risk_level=risk.value,
        )
    if decision == PolicyDecision.ASK:
        raise PipelineEnforcementError(
            action=action.title,
            reason=f"Policy requires approval for {action.title!r}",
            risk_level=risk.value,
            requires_approval=True,
        )
    return decision
