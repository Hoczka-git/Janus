"""Policy engine — the Agency → Policy bridge in the closed-loop pipeline.

The PolicyEngine consumes the :class:`TaskAgency` classification produced
by the Agency stage and produces a :class:`PolicyDecision` that determines
whether the action is allowed, requires approval, or is blocked.

This module implements the Phase E policy model (the one actually present
on this branch) rather than the P1 design (16 rules, 7 gates). The Phase E
model is execution-mode-driven: the policy decision is derived from the
agency classification's ``execution_mode`` and ``support_mode``.

Design reference: docs/design/closed_loop_architecture_spec.md §Stage 3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from janus.models.execution_mode import ExecutionMode
from janus.models.policy import PolicyDecision, PolicyRule
from janus.models.support_mode import SupportMode
from janus.models.task_agency import TaskAgency

logger = logging.getLogger(__name__)


# ── Policy rules ─────────────────────────────────────────────────────────────

#: Default policy rules for the Phase E model.
#:
#: The rules are ordered by precedence. The first matching rule wins.
#: Each rule maps an (execution_mode, support_mode) pair to a verdict.
DEFAULT_RULES: list[PolicyRule] = [
    # USER execution → always allowed (user acts, Janus assists)
    PolicyRule(
        rule_id="R-USER",
        action="execute",
        risk_level="low",
        verdict="allow",
        rationale="User-executed actions are always allowed",
        enforcement_point="pre_execution",
    ),
    # COLLABORATIVE execution → always allowed (user + Janus together)
    PolicyRule(
        rule_id="R-COLLAB",
        action="execute",
        risk_level="medium",
        verdict="allow",
        rationale="Collaborative actions are allowed with user involvement",
        enforcement_point="pre_execution",
    ),
    # JANUS execution + EXECUTE support → allow (Janus executes, user reviews)
    PolicyRule(
        rule_id="R-JANUS-EXEC",
        action="execute",
        risk_level="medium",
        verdict="allow",
        rationale="Janus-executed actions with EXECUTE support are allowed",
        enforcement_point="pre_execution",
    ),
    # JANUS execution + non-EXECUTE support → require approval
    PolicyRule(
        rule_id="R-JANUS-REVIEW",
        action="execute",
        risk_level="high",
        verdict="require_approval",
        rationale="Janus-executed actions with non-EXECUTE support require approval",
        enforcement_point="pre_execution",
    ),
]


# ── PolicyEngine ─────────────────────────────────────────────────────────────

class PolicyEngine:
    """Evaluate policy rules against an agency classification.

    The engine is the single entry point for the Agency → Policy
    connection. It takes a :class:`TaskAgency` (produced by
    :func:`janus.services.agency_planning.classify_task`) and returns
    a :class:`PolicyDecision`.

    Usage::

        engine = PolicyEngine()
        decision = engine.evaluate(agency)
        if decision.verdict == "allow":
            # proceed with execution
        elif decision.verdict == "require_approval":
            # gate on human approval
        else:
            # block execution
    """

    def __init__(self, rules: list[PolicyRule] | None = None) -> None:
        """Initialize with optional custom rules (defaults to DEFAULT_RULES)."""
        self._rules = rules if rules is not None else DEFAULT_RULES

    def evaluate(self, agency: TaskAgency) -> PolicyDecision:
        """Evaluate policy rules against an agency classification.

        Iterates through the rules in order and returns the first
        matching decision. If no rule matches, returns a default
        "allow" decision (fail-open for unknown classifications).

        Args:
            agency: The agency classification from the Agency stage.

        Returns:
            A PolicyDecision with the verdict and rationale.
        """
        for rule in self._rules:
            if self._rule_matches(rule, agency):
                return PolicyDecision(
                    rule_id=rule.rule_id,
                    verdict=rule.verdict,
                    risk_level=rule.risk_level,
                    rationale=rule.rationale,
                    gate_id=rule.gate_id,
                    enforcement_point=rule.enforcement_point,
                )

        # Fail-open: unknown classification → allow with low confidence
        logger.warning(
            "No policy rule matched for execution_mode=%s, support_mode=%s",
            agency.execution_mode,
            agency.support_mode,
        )
        return PolicyDecision(
            rule_id="R-DEFAULT",
            verdict="allow",
            risk_level="low",
            rationale=(
                f"No specific rule for {agency.execution_mode.value}/"
                f"{agency.support_mode.value}; defaulting to allow"
            ),
            enforcement_point="pre_execution",
        )

    def _rule_matches(self, rule: PolicyRule, agency: TaskAgency) -> bool:
        """Check if a rule matches the given agency classification.

        Custom rules (with context specifying execution_mode/support_mode)
        are checked first. Default rules match by rule_id.
        """
        # Custom rules: match by context if specified
        if rule.context:
            em_match = rule.context.get("execution_mode")
            sm_match = rule.context.get("support_mode")
            if em_match is not None and agency.execution_mode != em_match:
                return False
            if sm_match is not None and agency.support_mode != sm_match:
                return False
            return True

        # Default rules: match by rule_id
        if rule.rule_id == "R-USER":
            return agency.execution_mode == ExecutionMode.USER
        if rule.rule_id == "R-COLLAB":
            return agency.execution_mode == ExecutionMode.COLLABORATIVE
        if rule.rule_id == "R-JANUS-EXEC":
            return (
                agency.execution_mode == ExecutionMode.JANUS
                and agency.support_mode == SupportMode.EXECUTE
            )
        if rule.rule_id == "R-JANUS-REVIEW":
            return (
                agency.execution_mode == ExecutionMode.JANUS
                and agency.support_mode != SupportMode.EXECUTE
            )
        return False


# ── Enforcement gate ─────────────────────────────────────────────────────────

class EnforcementGate:
    """Pre-execution enforcement gate.

    Wraps the PolicyEngine and provides a single ``enforce()`` method
    that callers can invoke before dispatching an action to Hermes.
    Raises :class:`PolicyEnforcementError` when the policy blocks
    or requires approval.
    """

    def __init__(self, engine: PolicyEngine | None = None) -> None:
        self._engine = engine if engine is not None else PolicyEngine()

    def enforce(self, agency: TaskAgency) -> PolicyDecision:
        """Enforce policy for an agency classification.

        Args:
            agency: The agency classification.

        Returns:
            The PolicyDecision (always "allow" when returned).

        Raises:
            PolicyEnforcementError: When the policy blocks the action
                or requires approval.
        """
        decision = self._engine.evaluate(agency)

        if decision.verdict == "block":
            raise PolicyEnforcementError(
                action=agency.execution_mode.value,
                reason=decision.rationale,
                risk_level=decision.risk_level,
            )
        if decision.verdict == "require_approval":
            raise PolicyEnforcementError(
                action=agency.execution_mode.value,
                reason=decision.rationale,
                risk_level=decision.risk_level,
                requires_approval=True,
            )
        return decision


class PolicyEnforcementError(Exception):
    """Raised when the enforcement gate blocks or gates an action.

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
            f"Policy enforcement failed for {action}: {reason} "
            f"(risk={risk_level}, requires_approval={requires_approval})"
        )
