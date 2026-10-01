"""Policy model for Janus — Phase E: Policy & Approval engine.

This module defines the Policy domain model: a configurable rule schema
that maps (action, risk, impact) tuples to ALLOW/ASK/DENY decisions,
plus the ClassificationCategory enum that maps those decisions to the
three enforcement categories consumed by the enforcement layer.

The model is pure-logic — it does not perform I/O. Persistence is
handled by the policy engine service.

Design reference: docs/design/policy_approval_p1_design.md (Phase E)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar


# ── Enums ────────────────────────────────────────────────────────────────────


class PolicyAction(StrEnum):
    """Actions that can be governed by policy rules.

    These represent the categories of operations Janus can perform.
    """

    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    EXECUTE = "execute"
    SEND = "send"
    CREATE = "create"
    UPDATE = "update"
    APPROVE = "approve"
    DELEGATE = "delegate"


class RiskLevel(StrEnum):
    """Risk level of an action.

    LOW       — minimal potential for harm (e.g., reading own data).
    MEDIUM    — moderate potential for harm (e.g., writing to vault).
    HIGH      — significant potential for harm (e.g., deleting data).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ImpactLevel(StrEnum):
    """Impact level of an action — scope of effect.

    LOW       — affects a single entity or small scope.
    MEDIUM    — affects a moderate scope (e.g., a project).
    HIGH      — affects a large scope (e.g., system-wide).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PolicyDecision(StrEnum):
    """Decision returned by policy evaluation.

    ALLOW — the action may proceed without human approval.
    ASK   — the action requires human approval before proceeding.
    DENY  — the action is prohibited.
    """

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class ClassificationCategory(StrEnum):
    """Classification category for the enforcement layer.

    AUTO_ALLOWED      — the action may proceed without human approval.
    APPROVAL_REQUIRED — the action requires human approval before proceeding.
    USER_ONLY         — the action is restricted to user contexts (DENY for Janus).
    """

    AUTO_ALLOWED = "auto_allowed"
    APPROVAL_REQUIRED = "approval_required"
    USER_ONLY = "user_only"


# ── Policy rule ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PolicyRule:
    """A single policy rule mapping (action, risk, impact) → decision.

    Rules are evaluated in order; the first matching rule wins.
    A rule with ``risk=None`` or ``impact=None`` acts as a wildcard
    for that dimension.

    Attributes:
        action: The action this rule governs.
        risk: Risk level constraint (None = wildcard).
        impact: Impact level constraint (None = wildcard).
        decision: The decision to return when this rule matches.
        description: Human-readable explanation of the rule.
        priority: Lower numbers = higher priority (evaluated first).
    """

    action: PolicyAction
    risk: RiskLevel | None
    impact: ImpactLevel | None
    decision: PolicyDecision
    description: str = ""
    priority: int = 100

    def matches(
        self,
        action: PolicyAction,
        risk: RiskLevel,
        impact: ImpactLevel,
    ) -> bool:
        """Check if this rule matches the given (action, risk, impact) tuple."""
        if self.action != action:
            return False
        if self.risk is not None and self.risk != risk:
            return False
        if self.impact is not None and self.impact != impact:
            return False
        return True


# ── Policy ───────────────────────────────────────────────────────────────────


@dataclass
class Policy:
    """A collection of policy rules with evaluation logic.

    Rules are sorted by priority (ascending) at construction time.
    The first matching rule determines the decision. If no rule
    matches, the default decision is returned.

    Attributes:
        rules: The policy rules (sorted by priority).
        default_decision: Decision when no rule matches.
        name: Human-readable name for this policy set.
    """

    rules: list[PolicyRule] = field(default_factory=list)
    default_decision: PolicyDecision = PolicyDecision.ASK
    name: str = "default"

    # Valid risk/impact orderings for escalation logic
    _RISK_ORDER: ClassVar[dict[RiskLevel, int]] = {
        RiskLevel.LOW: 0,
        RiskLevel.MEDIUM: 1,
        RiskLevel.HIGH: 2,
    }
    _IMPACT_ORDER: ClassVar[dict[ImpactLevel, int]] = {
        ImpactLevel.LOW: 0,
        ImpactLevel.MEDIUM: 1,
        ImpactLevel.HIGH: 2,
    }

    def __post_init__(self) -> None:
        # Sort rules by priority (ascending), then by specificity
        # (more specific rules first — those with fewer wildcards).
        self.rules.sort(key=lambda r: (r.priority, -self._specificity(r)))

    @staticmethod
    def _specificity(rule: PolicyRule) -> int:
        """Count non-wildcard dimensions (higher = more specific)."""
        score = 0
        if rule.risk is not None:
            score += 1
        if rule.impact is not None:
            score += 1
        return score

    def evaluate(
        self,
        action: PolicyAction,
        risk: RiskLevel,
        impact: ImpactLevel,
    ) -> PolicyDecision:
        """Evaluate the policy for a given (action, risk, impact) tuple.

        Returns the decision from the first matching rule, or the
        default decision if no rule matches.
        """
        for rule in self.rules:
            if rule.matches(action, risk, impact):
                return rule.decision
        return self.default_decision

    def add_rule(self, rule: PolicyRule) -> None:
        """Add a rule and re-sort."""
        self.rules.append(rule)
        self.rules.sort(key=lambda r: (r.priority, -self._specificity(r)))

    def remove_rule(self, rule: PolicyRule) -> bool:
        """Remove a rule. Returns True if the rule was found and removed."""
        try:
            self.rules.remove(rule)
            return True
        except ValueError:
            return False

    def is_allowed(self, action: PolicyAction, risk: RiskLevel, impact: ImpactLevel) -> bool:
        """Convenience: returns True if evaluation yields ALLOW."""
        return self.evaluate(action, risk, impact) == PolicyDecision.ALLOW

    def is_denied(self, action: PolicyAction, risk: RiskLevel, impact: ImpactLevel) -> bool:
        """Convenience: returns True if evaluation yields DENY."""
        return self.evaluate(action, risk, impact) == PolicyDecision.DENY

    def requires_approval(self, action: PolicyAction, risk: RiskLevel, impact: ImpactLevel) -> bool:
        """Convenience: returns True if evaluation yields ASK."""
        return self.evaluate(action, risk, impact) == PolicyDecision.ASK


# ── Policy decision record (audit log entry) ─────────────────────────────────


@dataclass
class PolicyDecisionRecord:
    """An audit record of a policy evaluation.

    Captures the context and outcome of a single policy decision
    for auditing and debugging purposes.

    Attributes:
        action: The action that was evaluated.
        risk: The risk level of the action.
        impact: The impact level of the action.
        decision: The decision returned by the policy.
        rule_description: Description of the rule that matched (if any).
        timestamp: When the decision was made.
        context: Optional context (e.g., task title, goal name).
    """

    action: PolicyAction
    risk: RiskLevel
    impact: ImpactLevel
    decision: PolicyDecision
    rule_description: str = ""
    timestamp: str = ""
    context: str = ""


# ── Default policy factory ───────────────────────────────────────────────────


def create_default_policy() -> Policy:
    """Create a sensible default policy.

    The default policy is conservative:
    - READ actions are generally ALLOWED (low risk).
    - WRITE/CREATE/UPDATE actions require ASK for medium+ risk.
    - DELETE actions require ASK for medium+ risk, DENY for high risk + high impact.
    - SEND/EXECUTE actions require ASK for medium+ risk.
    - APPROVE/DELEGATE actions always require ASK.
    """
    rules = [
        # READ: generally allowed
        PolicyRule(
            action=PolicyAction.READ,
            risk=None,
            impact=None,
            decision=PolicyDecision.ALLOW,
            description="Read actions are generally allowed",
            priority=100,
        ),
        # WRITE: allow low risk, ask medium+
        PolicyRule(
            action=PolicyAction.WRITE,
            risk=RiskLevel.LOW,
            impact=None,
            decision=PolicyDecision.ALLOW,
            description="Low-risk writes are allowed",
            priority=50,
        ),
        PolicyRule(
            action=PolicyAction.WRITE,
            risk=None,
            impact=None,
            decision=PolicyDecision.ASK,
            description="Medium+ risk writes require approval",
            priority=60,
        ),
        # CREATE: allow low risk, ask medium+
        PolicyRule(
            action=PolicyAction.CREATE,
            risk=RiskLevel.LOW,
            impact=None,
            decision=PolicyDecision.ALLOW,
            description="Low-risk creates are allowed",
            priority=50,
        ),
        PolicyRule(
            action=PolicyAction.CREATE,
            risk=None,
            impact=None,
            decision=PolicyDecision.ASK,
            description="Medium+ risk creates require approval",
            priority=60,
        ),
        # UPDATE: allow low risk, ask medium+
        PolicyRule(
            action=PolicyAction.UPDATE,
            risk=RiskLevel.LOW,
            impact=None,
            decision=PolicyDecision.ALLOW,
            description="Low-risk updates are allowed",
            priority=50,
        ),
        PolicyRule(
            action=PolicyAction.UPDATE,
            risk=None,
            impact=None,
            decision=PolicyDecision.ASK,
            description="Medium+ risk updates require approval",
            priority=60,
        ),
        # DELETE: deny high+high, ask otherwise
        PolicyRule(
            action=PolicyAction.DELETE,
            risk=RiskLevel.HIGH,
            impact=ImpactLevel.HIGH,
            decision=PolicyDecision.DENY,
            description="High-risk high-impact deletes are denied",
            priority=10,
        ),
        PolicyRule(
            action=PolicyAction.DELETE,
            risk=None,
            impact=None,
            decision=PolicyDecision.ASK,
            description="All deletes require approval",
            priority=60,
        ),
        # SEND: ask medium+
        PolicyRule(
            action=PolicyAction.SEND,
            risk=RiskLevel.LOW,
            impact=None,
            decision=PolicyDecision.ALLOW,
            description="Low-risk sends are allowed",
            priority=50,
        ),
        PolicyRule(
            action=PolicyAction.SEND,
            risk=None,
            impact=None,
            decision=PolicyDecision.ASK,
            description="Medium+ risk sends require approval",
            priority=60,
        ),
        # EXECUTE: ask medium+
        PolicyRule(
            action=PolicyAction.EXECUTE,
            risk=RiskLevel.LOW,
            impact=None,
            decision=PolicyDecision.ALLOW,
            description="Low-risk executions are allowed",
            priority=50,
        ),
        PolicyRule(
            action=PolicyAction.EXECUTE,
            risk=None,
            impact=None,
            decision=PolicyDecision.ASK,
            description="Medium+ risk executions require approval",
            priority=60,
        ),
        # APPROVE: always ask
        PolicyRule(
            action=PolicyAction.APPROVE,
            risk=None,
            impact=None,
            decision=PolicyDecision.ASK,
            description="Approval actions always require human approval",
            priority=10,
        ),
        # DELEGATE: always ask
        PolicyRule(
            action=PolicyAction.DELEGATE,
            risk=None,
            impact=None,
            decision=PolicyDecision.ASK,
            description="Delegation actions always require human approval",
            priority=10,
        ),
    ]
    return Policy(rules=rules, default_decision=PolicyDecision.ASK, name="default")
