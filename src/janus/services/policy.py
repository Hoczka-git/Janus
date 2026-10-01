"""Policy evaluation engine for P1 Policy Enforcement & Approval Workflow.

This module contains:
- POLICY_RULES: the 16 P1 rules as data
- evaluate_policy(): evaluates rules against an action, returns the most restrictive verdict
- build_approval_request(): constructs an ApprovalRequest from a PolicyDecision
- present_approval_request(): presents the request to the user via CLI
- record_approval(): logs the approval decision (P1: execution log only)

Design reference: docs/design/policy_approval_p1_design.md §4, §7.2
"""

from __future__ import annotations

import logging
from typing import Optional

from janus.models.policy import (
    ApprovalRecord,
    ApprovalRequest,
    ApprovalResponse,
    PolicyDecision,
    PolicyRule,
    PolicyVerdict,
    RiskLevel,
)
from janus.models.task_agency import TaskAgency

logger = logging.getLogger(__name__)

# ── P1 Policy Rule Table (design §4) ─────────────────────────────────────────
#
# Rules are evaluated in order; most restrictive verdict wins (DENY > ASK > ALLOW).
# If no rules match, the default is DENY (safe fallback, design §8.7).

POLICY_RULES: list[PolicyRule] = [
    # R1: Task execution (user-mode) — ALLOW
    PolicyRule(
        rule_id="R1",
        action="task_execution",
        context="execution_mode=USER",
        risk_level=RiskLevel.LOW,
        verdict=PolicyVerdict.ALLOW,
        rationale="User-mode task execution is low-risk and does not require approval.",
        enforcement_point="janus.services.tasks:complete_task",
    ),
    # R2: Task execution (Janus-mode) — ALLOW
    PolicyRule(
        rule_id="R2",
        action="task_execution",
        context="execution_mode=JANUS",
        risk_level=RiskLevel.LOW,
        verdict=PolicyVerdict.ALLOW,
        rationale="Janus-mode task execution with EXECUTE support is low-risk.",
        enforcement_point="janus.services.tasks:complete_task",
    ),
    # R3: Task execution (collaborative) — ASK
    PolicyRule(
        rule_id="R3",
        action="task_execution",
        context="execution_mode=COLLABORATIVE",
        risk_level=RiskLevel.MEDIUM,
        verdict=PolicyVerdict.ASK,
        rationale="Collaborative task execution requires user approval.",
        enforcement_point="janus.services.tasks:complete_task",
    ),
    # R4: Janus assistive (explain/coach/scaffold) — ALLOW
    PolicyRule(
        rule_id="R4",
        action="task_execution",
        context="support_mode=EXPLAIN,COACH,SCAFFOLD",
        risk_level=RiskLevel.LOW,
        verdict=PolicyVerdict.ALLOW,
        rationale="Assistive modes (explain/coach/scaffold) do not change state.",
        enforcement_point="janus.services.tasks:complete_task",
    ),
    # R5: Janus review of user work — ASK
    PolicyRule(
        rule_id="R5",
        action="task_execution",
        context="support_mode=REVIEW",
        risk_level=RiskLevel.MEDIUM,
        verdict=PolicyVerdict.ASK,
        rationale="Review of user work requires approval.",
        enforcement_point="janus.services.tasks:complete_task",
    ),
    # R6: Goal completion — ASK
    PolicyRule(
        rule_id="R6",
        action="goal_completion",
        context="",
        risk_level=RiskLevel.MEDIUM,
        verdict=PolicyVerdict.ASK,
        rationale="Goal completion requires structural gates and user approval.",
        enforcement_point="janus.services.goals:complete_goal",
        gate_id="G-2",
    ),
    # R7: Knowledge artifact promotion — ASK
    PolicyRule(
        rule_id="R7",
        action="knowledge_promotion",
        context="",
        risk_level=RiskLevel.MEDIUM,
        verdict=PolicyVerdict.ASK,
        rationale="Knowledge artifact promotion requires curation approval.",
        enforcement_point="janus.services.curation_gate:promote_to_vault",
        gate_id="G-3",
    ),
    # R8: External system read — ALLOW
    PolicyRule(
        rule_id="R8",
        action="external_read",
        context="",
        risk_level=RiskLevel.LOW,
        verdict=PolicyVerdict.ALLOW,
        rationale="External system reads do not change state.",
        enforcement_point="janus.services.*",
    ),
    # R9: External system write (state-changing) — ASK
    PolicyRule(
        rule_id="R9",
        action="external_write",
        context="",
        risk_level=RiskLevel.HIGH,
        verdict=PolicyVerdict.ASK,
        rationale="External system writes are high-risk and require approval.",
        enforcement_point="janus.services.*",
        gate_id="G-4",
    ),
    # R10: Goal deletion — DENY (via ASK + confirmation)
    PolicyRule(
        rule_id="R10",
        action="goal_deletion",
        context="",
        risk_level=RiskLevel.HIGH,
        verdict=PolicyVerdict.DENY,
        rationale="Goal deletion is blocked; use set_goal_state with confirmation.",
        enforcement_point="janus.services.goals:set_goal_state",
        gate_id="G-5",
    ),
    # R11: Bulk state changes — ASK
    PolicyRule(
        rule_id="R11",
        action="bulk_state_change",
        context="",
        risk_level=RiskLevel.HIGH,
        verdict=PolicyVerdict.ASK,
        rationale="Bulk state changes require user confirmation.",
        enforcement_point="janus.services.*",
        gate_id="G-6",
    ),
    # R12: Policy-relevant config change — ASK
    PolicyRule(
        rule_id="R12",
        action="config_change",
        context="",
        risk_level=RiskLevel.HIGH,
        verdict=PolicyVerdict.ASK,
        rationale="Policy-relevant config changes require approval.",
        enforcement_point="janus.services.*",
        gate_id="G-7",
    ),
    # R13: Task status change (routine) — ALLOW
    PolicyRule(
        rule_id="R13",
        action="task_status_change",
        context="",
        risk_level=RiskLevel.LOW,
        verdict=PolicyVerdict.ALLOW,
        rationale="Routine task status changes (todo→in_progress→blocked) are low-risk.",
        enforcement_point="janus.services.tasks:set_task_state",
    ),
    # R14: Task completion (git repo) — ASK
    PolicyRule(
        rule_id="R14",
        action="task_completion",
        context="git_repo",
        risk_level=RiskLevel.MEDIUM,
        verdict=PolicyVerdict.ASK,
        rationale="Task completion in a git repo requires ADR-004 gates.",
        enforcement_point="janus.services.tasks:complete_task",
        gate_id="G-1",
    ),
    # R15: Task completion (non-git) — ALLOW
    PolicyRule(
        rule_id="R15",
        action="task_completion",
        context="non_git",
        risk_level=RiskLevel.LOW,
        verdict=PolicyVerdict.ALLOW,
        rationale="Task completion outside a git repo is low-risk.",
        enforcement_point="janus.services.tasks:complete_task",
    ),
    # R16: Evidence-less goal completion — DENY
    PolicyRule(
        rule_id="R16",
        action="goal_completion",
        context="no_evidence",
        risk_level=RiskLevel.HIGH,
        verdict=PolicyVerdict.DENY,
        rationale="Goal completion without evidence records is blocked.",
        enforcement_point="janus.services.goals:complete_goal",
        gate_id="G-2",
    ),
]


def _rule_matches(rule: PolicyRule, action: str, context: str | None) -> bool:
    """Check if a rule matches the given action and context.

    A rule matches when:
    - The rule's action equals the incoming action (exact match), AND
    - The rule's context is empty (matches any) or is a case-insensitive
      substring of the incoming context string.

    For comma-separated rule contexts (e.g., "support_mode=EXPLAIN,COACH,SCAFFOLD"),
    each alternative is checked independently — if any alternative is a substring
    of the incoming context, the rule matches.
    """
    if rule.action != action:
        return False
    if not rule.context:
        return True
    if context is None:
        return False
    # Handle comma-separated alternatives in rule context
    # e.g., "support_mode=EXPLAIN,COACH,SCAFFOLD" → check each alternative
    context_lower = context.lower()
    for alternative in rule.context.split(","):
        alternative = alternative.strip()
        if alternative.lower() in context_lower:
            return True
    return False


def evaluate_policy(
    action: str,
    context: str | None = None,
    risk_level: RiskLevel | None = None,
    task_agency: TaskAgency | None = None,
) -> PolicyDecision:
    """Evaluate all policy rules against an action and return the most restrictive verdict.

    Iterates through POLICY_RULES, collects all matching rules, and returns
    the most restrictive verdict (DENY > ASK > ALLOW).

    If no rules match, returns a DENY verdict (safe fallback, design §8.7).
    If ``task_agency`` is None and the action requires classification,
    falls back to a conservative default (MEDIUM risk, ASK).

    Args:
        action: The action being attempted (e.g., "task_execution").
        context: Additional context string (e.g., "execution_mode=USER").
        risk_level: Risk level of the action, if known.
        task_agency: Agency classification for the task, if available.

    Returns:
        A PolicyDecision with the most restrictive verdict.
    """
    # Build context string from task_agency if provided
    full_context = context or ""
    if task_agency is not None:
        agency_ctx = f"execution_mode={task_agency.execution_mode.value}"
        if task_agency.support_mode:
            agency_ctx += f",support_mode={task_agency.support_mode.value}"
        full_context = f"{full_context},{agency_ctx}" if full_context else agency_ctx

    # If task_agency is None and the action is task_execution with no context,
    # fall back to a conservative ASK verdict (design §8.2).
    if task_agency is None and action == "task_execution" and not full_context:
        logger.info(
            "task_agency is None for task_execution with no context — defaulting to ASK"
        )
        return PolicyDecision(
            rule_id="DEFAULT",
            verdict=PolicyVerdict.ASK,
            risk_level=RiskLevel.MEDIUM,
            rationale="Task classification unavailable; defaulting to ASK (conservative).",
        )

    # Collect all matching rules
    matching_rules: list[PolicyRule] = []
    for rule in POLICY_RULES:
        if _rule_matches(rule, action, full_context):
            matching_rules.append(rule)

    # If no rules match, return DENY (safe fallback)
    if not matching_rules:
        logger.warning(
            "No policy rules matched action=%r context=%r — defaulting to DENY",
            action,
            full_context,
        )
        return PolicyDecision(
            rule_id="DEFAULT",
            verdict=PolicyVerdict.DENY,
            risk_level=risk_level or RiskLevel.MEDIUM,
            rationale="No matching policy rules; defaulting to DENY (safe fallback).",
        )

    # Most restrictive verdict wins: DENY > ASK > ALLOW
    verdict_order = {PolicyVerdict.DENY: 0, PolicyVerdict.ASK: 1, PolicyVerdict.ALLOW: 2}
    most_restrictive = min(matching_rules, key=lambda r: verdict_order[r.verdict])

    # If task_agency is None and the action is task_execution, fall back to ASK
    # only when no context information is available. If context is provided
    # (e.g., "execution_mode=USER"), we have enough information to make a
    # decision and should not upgrade.
    if task_agency is None and action == "task_execution" and not full_context:
        logger.info(
            "task_agency is None for task_execution — upgrading to ASK"
        )
        return PolicyDecision(
            rule_id=most_restrictive.rule_id,
            verdict=PolicyVerdict.ASK,
            risk_level=RiskLevel.MEDIUM,
            rationale="Task classification unavailable; defaulting to ASK (conservative).",
            gate_id=most_restrictive.gate_id,
            enforcement_point=most_restrictive.enforcement_point,
        )

    return PolicyDecision(
        rule_id=most_restrictive.rule_id,
        verdict=most_restrictive.verdict,
        risk_level=most_restrictive.risk_level,
        rationale=most_restrictive.rationale,
        gate_id=most_restrictive.gate_id,
        enforcement_point=most_restrictive.enforcement_point,
    )


def build_approval_request(
    decision: PolicyDecision,
    action: str,
    context: str,
) -> ApprovalRequest:
    """Construct an ApprovalRequest from a PolicyDecision.

    Args:
        decision: The policy decision that triggered the approval.
        action: The action being attempted.
        context: What entities are affected.

    Returns:
        An ApprovalRequest ready to present to the user.
    """
    return ApprovalRequest(
        action=action,
        context=context,
        risk_level=decision.risk_level,
        policy_rule=decision.rule_id,
        rationale=decision.rationale,
        what_approval_entails=f"Approving will allow the '{action}' action to proceed.",
        alternative="Denying will block the action. Deferring will cancel it for now.",
        gate_id=decision.gate_id,
    )


def present_approval_request(request: ApprovalRequest) -> ApprovalResponse:
    """Present an approval request to the user via CLI and return their response.

    At P1, this is a simple CLI prompt. The user responds with:
    - 'approve' → APPROVE
    - 'deny' → DENY
    - 'defer' → DEFER

    In non-interactive mode (e.g., tests, CI), `input()` raises OSError.
    In that case, the request is auto-approved so that non-interactive
    callers are not blocked by the policy layer.

    Args:
        request: The approval request to present.

    Returns:
        The user's ApprovalResponse.
    """
    from janus.cli.approval import format_approval_prompt

    prompt = format_approval_prompt(request)
    print(prompt)

    while True:
        try:
            response = input("Response [approve/deny/defer]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nDeferred.")
            return ApprovalResponse.DEFER
        except OSError:
            # Non-interactive mode (e.g., tests, CI) — auto-approve
            # so that non-interactive callers are not blocked.
            print("\nAuto-approved (non-interactive mode).")
            return ApprovalResponse.APPROVE

        if response in ("approve", "a"):
            return ApprovalResponse.APPROVE
        elif response in ("deny", "d"):
            return ApprovalResponse.DENY
        elif response in ("defer", "def", ""):
            return ApprovalResponse.DEFER
        else:
            print("Invalid response. Please enter 'approve', 'deny', or 'defer'.")


def record_approval(record: ApprovalRecord) -> None:
    """Log an approval decision (P1: execution log only).

    At P1, this logs the decision to the structured logger. Persistent
    recording is P2.

    Args:
        record: The approval record to log.
    """
    from janus._log import emit

    emit(
        logger,
        "service.policy.approval_recorded",
        trace_id=None,
        span_id="service",
        operation="record_approval",
        action=record.request.action,
        policy_rule=record.request.policy_rule,
        response=record.response.value,
        decided_by=record.decided_by,
        message=f"Approval recorded: {record.request.action} → {record.response.value}",
    )
