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
from janus.models.policy import PolicyDecision
from janus.models.task_agency import TaskAgency
from janus.services.policy_engine import EnforcementGate, PolicyEngine

logger = logging.getLogger(__name__)


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
        agency: The TaskAgency classification from the Agency stage.
    """

    action_title: str
    action_kind: str
    should_execute: bool
    requires_approval: bool
    blocked: bool
    decision: PolicyDecision
    agency: TaskAgency | None


def run_pipeline(
    action: NextAction,
    *,
    engine: PolicyEngine | None = None,
    gate: EnforcementGate | None = None,
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
        gate: optional custom EnforcementGate instance.

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
            decision=PolicyDecision(
                rule_id="R-NO-AGENCY",
                verdict="allow",
                risk_level="low",
                rationale="No agency classification; defaulting to allow",
                enforcement_point="pre_execution",
            ),
            agency=None,
        )

    # Run the policy engine
    policy_engine = engine if engine is not None else PolicyEngine()
    decision = policy_engine.evaluate(action.agency)

    should_execute = decision.verdict == "allow"
    requires_approval = decision.verdict == "require_approval"
    blocked = decision.verdict == "block"

    return PipelineResult(
        action_title=action.title,
        action_kind=action.kind,
        should_execute=should_execute,
        requires_approval=requires_approval,
        blocked=blocked,
        decision=decision,
        agency=action.agency,
    )


def enforce_pipeline(
    action: NextAction,
    *,
    gate: EnforcementGate | None = None,
) -> PolicyDecision:
    """Run the pipeline and enforce the policy decision.

    Unlike :func:`run_pipeline` (which returns a result object), this
    function raises :class:`PolicyEnforcementError` when the policy
    blocks or requires approval. It is the "strict" variant intended
    for use as a pre-execution gate.

    Args:
        action: The next action from the Planner.
        gate: Optional custom EnforcementGate instance.

    Returns:
        The PolicyDecision (always "allow" when returned).

    Raises:
        PolicyEnforcementError: When the policy blocks the action
            or requires approval.
    """
    enforcement_gate = gate if gate is not None else EnforcementGate()

    # If no agency classification, allow by default
    if action.agency is None:
        return PolicyDecision(
            rule_id="R-NO-AGENCY",
            verdict="allow",
            risk_level="low",
            rationale="No agency classification; defaulting to allow",
            enforcement_point="pre_execution",
        )

    return enforcement_gate.enforce(action.agency)
