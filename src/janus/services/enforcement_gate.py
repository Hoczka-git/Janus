"""Pre-execution enforcement gate for Janus actions.

This module implements the enforcement layer that calls the PolicyEngine
classification interface before any action executes. It ensures that:

- AUTO_ALLOWED actions proceed without additional approval.
- APPROVAL_REQUIRED actions are blocked until approval is confirmed.
- USER_ONLY actions are restricted to user contexts and rejected otherwise.

The gate is applied at the execution entry point (``dispatch_completion``)
consistently for all actions, and can also be applied at other entry points
(``complete_task``, ``promote_to_vault``) via :func:`enforce_action`.

Design reference: docs/design/policy_approval_p1_design.md (Phase E)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from janus._log import emit
from janus.models.policy import (
    ClassificationCategory,
    ImpactLevel,
    PolicyAction,
    RiskLevel,
)
from janus.services.policy_engine import PolicyEngine, get_policy_engine

logger = logging.getLogger(__name__)


# ── Enforcement action taxonomy ──────────────────────────────────────────────


class EnforcementAction(StrEnum):
    """Actions that can be enforced by the gate.

    These represent the categories of operations that Janus can perform
    at execution entry points. Each maps to a PolicyAction for classification.
    """

    TASK_COMPLETION = "task_completion"
    GOAL_COMPLETION = "goal_completion"
    MILESTONE_COMPLETION = "milestone_completion"
    PROJECT_COMPLETION = "project_completion"
    KNOWLEDGE_PROMOTION = "knowledge_promotion"
    KNOWLEDGE_INGESTION = "knowledge_ingestion"
    EXTERNAL_WRITE = "external_write"
    BULK_OPERATION = "bulk_operation"
    CONFIG_CHANGE = "config_change"
    TASK_STATUS_CHANGE = "task_status_change"
    GOAL_DELETION = "goal_deletion"


# ── Enforcement result ──────────────────────────────────────────────────────


@dataclass
class EnforcementResult:
    """Result of an enforcement gate check.

    Attributes:
        allowed: Whether the action is permitted to execute.
        category: The classification category from the policy engine.
        action: The action that was evaluated.
        message: Human-readable message explaining the decision.
        context: Optional context (e.g., task title, goal name).
    """

    allowed: bool
    category: ClassificationCategory
    action: str
    message: str
    context: str = ""


class EnforcementGateError(RuntimeError):
    """Raised when the enforcement gate blocks an action.

    Carries the enforcement result so callers can surface a precise,
    actionable message.
    """

    def __init__(self, result: EnforcementResult) -> None:
        self.result = result
        super().__init__(result.message)


# ── Action → Policy mapping ──────────────────────────────────────────────────


def _action_to_policy_action(action: EnforcementAction) -> PolicyAction:
    """Map an enforcement action to a policy action."""
    mapping = {
        EnforcementAction.TASK_COMPLETION: PolicyAction.UPDATE,
        EnforcementAction.GOAL_COMPLETION: PolicyAction.UPDATE,
        EnforcementAction.MILESTONE_COMPLETION: PolicyAction.UPDATE,
        EnforcementAction.PROJECT_COMPLETION: PolicyAction.UPDATE,
        EnforcementAction.KNOWLEDGE_PROMOTION: PolicyAction.CREATE,
        EnforcementAction.KNOWLEDGE_INGESTION: PolicyAction.CREATE,
        EnforcementAction.EXTERNAL_WRITE: PolicyAction.SEND,
        EnforcementAction.BULK_OPERATION: PolicyAction.EXECUTE,
        EnforcementAction.CONFIG_CHANGE: PolicyAction.UPDATE,
        EnforcementAction.TASK_STATUS_CHANGE: PolicyAction.UPDATE,
        EnforcementAction.GOAL_DELETION: PolicyAction.DELETE,
    }
    return mapping[action]


def _default_risk_for_action(action: EnforcementAction) -> RiskLevel:
    """Default risk level for an enforcement action."""
    mapping = {
        EnforcementAction.TASK_COMPLETION: RiskLevel.LOW,
        EnforcementAction.GOAL_COMPLETION: RiskLevel.MEDIUM,
        EnforcementAction.MILESTONE_COMPLETION: RiskLevel.MEDIUM,
        EnforcementAction.PROJECT_COMPLETION: RiskLevel.MEDIUM,
        EnforcementAction.KNOWLEDGE_PROMOTION: RiskLevel.MEDIUM,
        EnforcementAction.KNOWLEDGE_INGESTION: RiskLevel.LOW,
        EnforcementAction.EXTERNAL_WRITE: RiskLevel.HIGH,
        EnforcementAction.BULK_OPERATION: RiskLevel.HIGH,
        EnforcementAction.CONFIG_CHANGE: RiskLevel.HIGH,
        EnforcementAction.TASK_STATUS_CHANGE: RiskLevel.LOW,
        EnforcementAction.GOAL_DELETION: RiskLevel.HIGH,
    }
    return mapping[action]


def _default_impact_for_action(action: EnforcementAction) -> ImpactLevel:
    """Default impact level for an enforcement action."""
    mapping = {
        EnforcementAction.TASK_COMPLETION: ImpactLevel.LOW,
        EnforcementAction.GOAL_COMPLETION: ImpactLevel.MEDIUM,
        EnforcementAction.MILESTONE_COMPLETION: ImpactLevel.MEDIUM,
        EnforcementAction.PROJECT_COMPLETION: ImpactLevel.MEDIUM,
        EnforcementAction.KNOWLEDGE_PROMOTION: ImpactLevel.MEDIUM,
        EnforcementAction.KNOWLEDGE_INGESTION: ImpactLevel.LOW,
        EnforcementAction.EXTERNAL_WRITE: ImpactLevel.HIGH,
        EnforcementAction.BULK_OPERATION: ImpactLevel.HIGH,
        EnforcementAction.CONFIG_CHANGE: ImpactLevel.HIGH,
        EnforcementAction.TASK_STATUS_CHANGE: ImpactLevel.LOW,
        EnforcementAction.GOAL_DELETION: ImpactLevel.HIGH,
    }
    return mapping[action]


# ── Context detection ────────────────────────────────────────────────────────


def _is_user_context(context: str) -> bool:
    """Check if the current context is a user context.

    A user context is one where the user is directly involved:
    - CLI commands initiated by the user (context = "cli" or "user")
    - Telegram messages from the user (context = "telegram")
    - Direct API calls with user authentication

    Non-user contexts include:
    - Automated/scheduled tasks (context starts with "automated:" or "system:")
    - Background processes
    - System-triggered events (e.g., Hermes sync listener)
    """
    if not context:
        # Empty context is treated as system context (conservative)
        return False
    if context.startswith("automated:") or context.startswith("system:"):
        return False
    if context in ("cli", "user", "telegram", "api"):
        return True
    # Default: treat unknown contexts as user contexts (fail-open for
    # explicit user interactions, fail-closed for system contexts)
    return not context.startswith("hermes") and not context.startswith("sync")


# ── Main enforcement function ───────────────────────────────────────────────


def enforce_action(
    action: EnforcementAction | str,
    context: str = "",
    risk: RiskLevel | str | None = None,
    impact: ImpactLevel | str | None = None,
    policy_engine: PolicyEngine | None = None,
) -> EnforcementResult:
    """Enforce the policy gate for an action before execution.

    This is the main entry point for the enforcement gate. It:
    1. Classifies the action using the PolicyEngine
    2. For AUTO_ALLOWED: permits execution
    3. For APPROVAL_REQUIRED: blocks execution with approval-required status
    4. For USER_ONLY: restricts to user contexts, rejects otherwise

    Args:
        action: The action to enforce.
        context: Optional context (e.g., task title, goal name, or context
            identifier like "cli", "telegram", "system").
        risk: Risk level override. If None, uses the default for the action.
        impact: Impact level override. If None, uses the default for the action.
        policy_engine: Optional policy engine instance. If None, uses the default.

    Returns:
        An EnforcementResult indicating whether the action is allowed.

    Raises:
        EnforcementGateError: If the action is blocked (APPROVAL_REQUIRED or
            USER_ONLY in non-user context).
    """
    if isinstance(action, str):
        action = EnforcementAction(action)
    if isinstance(risk, str):
        risk = RiskLevel(risk)
    if isinstance(impact, str):
        impact = ImpactLevel(impact)

    engine = policy_engine or get_policy_engine()
    policy_action = _action_to_policy_action(action)
    risk = risk or _default_risk_for_action(action)
    impact = impact or _default_impact_for_action(action)

    category = engine.classify(policy_action, risk, impact, context=context)

    if category == ClassificationCategory.AUTO_ALLOWED:
        result = EnforcementResult(
            allowed=True,
            category=category,
            action=action.value,
            message=f"Action '{action.value}' is auto-allowed.",
            context=context,
        )
    elif category == ClassificationCategory.APPROVAL_REQUIRED:
        result = EnforcementResult(
            allowed=False,
            category=category,
            action=action.value,
            message=(
                f"Action '{action.value}' requires human approval before execution. "
                f"Risk: {risk.value}, Impact: {impact.value}. "
                f"Use the appropriate approval channel to confirm this action."
            ),
            context=context,
        )
    elif category == ClassificationCategory.USER_ONLY:
        if _is_user_context(context):
            result = EnforcementResult(
                allowed=True,
                category=category,
                action=action.value,
                message=f"Action '{action.value}' is allowed in user context.",
                context=context,
            )
        else:
            result = EnforcementResult(
                allowed=False,
                category=category,
                action=action.value,
                message=(
                    f"Action '{action.value}' is restricted to user contexts. "
                    f"Current context '{context or 'system'}' is not a user context. "
                    f"This action must be initiated by the user directly."
                ),
                context=context,
            )
    else:
        # Should not happen, but fail safe
        result = EnforcementResult(
            allowed=False,
            category=category,
            action=action.value,
            message=f"Action '{action.value}' has unknown classification '{category.value}'.",
            context=context,
        )

    emit(
        logger,
        "service.enforcement_gate.enforced",
        trace_id=None,
        span_id="enforcement_gate",
        action=action.value,
        category=category.value,
        allowed=result.allowed,
        context=context,
        message=result.message,
    )

    return result


def check_action_allowed(
    action: EnforcementAction | str,
    context: str = "",
    risk: RiskLevel | str | None = None,
    impact: ImpactLevel | str | None = None,
    policy_engine: PolicyEngine | None = None,
) -> bool:
    """Check if an action is allowed without raising an exception.

    This is a convenience wrapper around :func:`enforce_action` that returns
    a boolean instead of raising an exception.

    Returns:
        True if the action is allowed, False otherwise.
    """
    try:
        result = enforce_action(action, context, risk, impact, policy_engine)
        return result.allowed
    except Exception:
        return False


def enforce_or_raise(
    action: EnforcementAction | str,
    context: str = "",
    risk: RiskLevel | str | None = None,
    impact: ImpactLevel | str | None = None,
    policy_engine: PolicyEngine | None = None,
) -> EnforcementResult:
    """Enforce the policy gate and raise an exception if blocked.

    This is a convenience wrapper around :func:`enforce_action` that raises
    :class:`EnforcementGateError` if the action is blocked.

    Returns:
        The EnforcementResult if the action is allowed.

    Raises:
        EnforcementGateError: If the action is blocked.
    """
    result = enforce_action(action, context, risk, impact, policy_engine)
    if not result.allowed:
        raise EnforcementGateError(result)
    return result
