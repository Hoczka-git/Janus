"""Policy decision models for the closed-loop execution pipeline.

These dataclasses define the data contracts for the Policy stage
(Stage 3) of the Planner → Agency → Policy → Hermes → Evidence →
Verification → State Update → Planner loop.

Per the architecture spec (docs/design/closed_loop_architecture_spec.md),
the Policy stage consumes the Agency classification (TaskAgency) and
produces a PolicyDecision that determines whether the action is allowed,
requires approval, or is blocked.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ── PolicyDecision ───────────────────────────────────────────────────────────

@dataclass
class PolicyDecision:
    """The outcome of a policy evaluation for a single action.

    Attributes:
        rule_id: Identifier of the rule that produced this decision
            (e.g. "R1"–"R16" per the P1 design).
        verdict: One of "allow", "require_approval", "block".
        risk_level: One of "low", "medium", "high", "critical".
        rationale: Human-readable explanation of the decision.
        gate_id: Optional linkage to a verification gate (G-1..G-7).
        enforcement_point: Where the rule is enforced (e.g. "pre_execution").
    """

    rule_id: str
    verdict: str                          # "allow" | "require_approval" | "block"
    risk_level: str                       # "low" | "medium" | "high" | "critical"
    rationale: str
    gate_id: str | None = None
    enforcement_point: str | None = None


# ── PolicyRule ───────────────────────────────────────────────────────────────

@dataclass
class PolicyRule:
    """A single policy rule with its enforcement criteria.

    Attributes:
        rule_id: Unique rule identifier (R1–R16).
        action: Which action this rule governs.
        context: Rule-specific context parameters.
        risk_level: Inherent risk level of the action.
        verdict: Default verdict when the rule matches.
        rationale: Human-readable explanation.
        enforcement_point: Where the rule is enforced.
        gate_id: Optional verification gate linkage.
    """

    rule_id: str
    action: str
    context: dict = field(default_factory=dict)
    risk_level: str = "low"
    verdict: str = "allow"
    rationale: str = ""
    enforcement_point: str | None = None
    gate_id: str | None = None


# ── ApprovalRequest ──────────────────────────────────────────────────────────

@dataclass
class ApprovalRequest:
    """A request for human approval when policy requires it.

    Attributes:
        action: The action requiring approval.
        context: Contextual information for the approver.
        risk_level: Risk level of the action.
        requested_approver: Who should approve.
        escalation_path: Ordered list of escalation contacts.
        deadline: Optional ISO-8601 deadline for the approval.
    """

    action: str
    context: dict = field(default_factory=dict)
    risk_level: str = "medium"
    requested_approver: str = "user"
    escalation_path: list[str] = field(default_factory=list)
    deadline: str | None = None
