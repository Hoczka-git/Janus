"""Policy data models for P1 Policy Enforcement & Approval Workflow.

This module defines the data structures used by the policy layer:
- PolicyVerdict: ALLOW, ASK, DENY
- RiskLevel: LOW, MEDIUM, HIGH
- PolicyRule: a single rule mapping action + context to a verdict
- PolicyDecision: the result of evaluating a policy rule
- ApprovalRequest: structured request presented to the user on ASK
- ApprovalResponse: APPROVE, DENY, DEFER
- ApprovalRecord: recorded after a user responds (P1: ephemeral)

Design reference: docs/design/policy_approval_p1_design.md §3
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class PolicyVerdict(StrEnum):
    """Verdict returned by policy evaluation.

    Members:
        ALLOW — proceed without additional approval.
        ASK   — requires explicit user approval.
        DENY  — blocked; cannot proceed even with approval.
    """

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class RiskLevel(StrEnum):
    """Risk level for an action.

    Members:
        LOW    — metric update, task status change, log entry.
        MEDIUM — goal status change, milestone completion.
        HIGH   — goal deletion, bulk state changes, external writes.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class PolicyRule:
    """A single policy rule mapping an action + context to a verdict.

    Attributes:
        rule_id: Unique rule identifier (e.g., "R1", "R2").
        action: Action class this rule applies to (e.g., "task_execution").
        context: Context filter (e.g., "execution_mode=USER").
        risk_level: Risk if this rule matches.
        verdict: ALLOW, ASK, or DENY.
        rationale: Human-readable explanation of why this rule exists.
        enforcement_point: File:line or service:function reference.
        gate_id: Associated gate (G-1..G-7) if ASK/DENY, else None.
    """

    rule_id: str
    action: str
    context: str
    risk_level: RiskLevel
    verdict: PolicyVerdict
    rationale: str
    enforcement_point: str
    gate_id: str | None = None


@dataclass
class PolicyDecision:
    """The result of evaluating a policy rule against an action.

    Attributes:
        rule_id: Which rule produced this verdict.
        verdict: ALLOW, ASK, or DENY.
        risk_level: Risk level of the matched rule.
        rationale: Why this verdict was reached.
        gate_id: Gate to invoke if ASK, else None.
        enforcement_point: Where to enforce.
    """

    rule_id: str
    verdict: PolicyVerdict
    risk_level: RiskLevel
    rationale: str
    gate_id: str | None = None
    enforcement_point: str = ""


@dataclass
class ApprovalRequest:
    """Structured approval request presented to the user on ASK verdict.

    Attributes:
        action: What is being attempted.
        context: What entities are affected.
        risk_level: LOW / MEDIUM / HIGH.
        policy_rule: Which rule produced this (e.g., "R6").
        rationale: Why approval is needed.
        what_approval_entails: What the user is approving.
        alternative: What happens if denied.
        gate_id: Associated gate, else None.
    """

    action: str
    context: str
    risk_level: RiskLevel
    policy_rule: str
    rationale: str
    what_approval_entails: str
    alternative: str
    gate_id: str | None = None


class ApprovalResponse(StrEnum):
    """User's response to an approval request.

    Members:
        APPROVE — user approves; action proceeds.
        DENY    — user denies; action is blocked.
        DEFER   — user defers; P1: cancel for now.
    """

    APPROVE = "approve"
    DENY = "deny"
    DEFER = "defer"


@dataclass
class ApprovalRecord:
    """Recorded after a user responds to an approval request.

    At P1, this is ephemeral (returned to caller, logged). Persistent
    recording is P2.

    Attributes:
        request: The original approval request.
        response: User's decision.
        decided_at: When the decision was made.
        decided_by: Who decided (always "user" at P1).
    """

    request: ApprovalRequest
    response: ApprovalResponse
    decided_at: datetime = field(default_factory=datetime.now)
    decided_by: str = "user"
