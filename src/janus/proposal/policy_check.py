"""Policy check implementation — evaluates ActionProposal content against policy rules.

This module provides a concrete implementation of the :class:`PolicyCheck`
protocol defined in ``approval_contract.py``. It is a pure, deterministic
function of the proposal content and the current policy rule set — no I/O,
no side effects, no human involvement.

The check maps an ActionProposal's action type and risk level to a
PolicyVerdict (ALLOW, ASK, DENY) using the default policy from
``janus.models.policy``.

Design reference: docs/design/policy_approval_p1_design.md §3, §5
"""

from __future__ import annotations

from janus.models.policy import (
    ImpactLevel,
    Policy,
    PolicyAction,
    PolicyDecision,
    create_default_policy,
)
from janus.models.policy_p1 import PolicyVerdict
from janus.proposal.approval_contract import PolicyCheck, PolicyCheckResult
from janus.proposal.models import ActionProposal, ActionType


# ── ActionType → PolicyAction mapping ────────────────────────────────────────

_ACTION_TYPE_TO_POLICY_ACTION: dict[ActionType, PolicyAction] = {
    ActionType.CREATE_TASK: PolicyAction.CREATE,
    ActionType.UPDATE_TASK: PolicyAction.UPDATE,
    ActionType.RESCHEDULE_TASK: PolicyAction.UPDATE,
    ActionType.CHANGE_PRIORITY: PolicyAction.UPDATE,
    ActionType.CREATE_CALENDAR_EVENT: PolicyAction.CREATE,
}


# ── PolicyDecision → PolicyVerdict mapping ───────────────────────────────────

_DECISION_TO_VERDICT: dict[PolicyDecision, PolicyVerdict] = {
    PolicyDecision.ALLOW: PolicyVerdict.ALLOW,
    PolicyDecision.ASK: PolicyVerdict.ASK,
    PolicyDecision.DENY: PolicyVerdict.DENY,
}


class ProposalPolicyCheck:
    """Concrete implementation of the PolicyCheck protocol.

    Evaluates an ActionProposal against the default policy and returns
    a :class:`PolicyCheckResult`. The check is deterministic and side-effect free.

    The evaluation maps the proposal's action type to a PolicyAction,
    uses the proposal's risk level directly, and assumes ImpactLevel.LOW
    (single-entity operations). The default policy from
    ``janus.models.policy`` determines the verdict.

    Usage::

        checker = ProposalPolicyCheck()
        result = checker.check(proposal)
        if result.passed:
            # proceed without approval
            ...
    """

    def __init__(self, policy: Policy | None = None) -> None:
        """Initialize the policy check.

        Args:
            policy: The policy to evaluate against. If None, uses the
                default policy from ``janus.models.policy``.
        """
        self._policy = policy if policy is not None else create_default_policy()

    def check(self, proposal: ActionProposal) -> PolicyCheckResult:
        """Evaluate a proposal against policy rules.

        Args:
            proposal: The ActionProposal to evaluate. The implementation
                inspects the proposal's ``action_type``, ``risk``,
                ``parameters``, and ``metadata`` to make its determination.

        Returns:
            A :class:`PolicyCheckResult`:
            - ``passed=True`` — the proposal may proceed without human approval.
            - ``passed=False`` — the proposal requires human approval via the
              ApprovalGate or is blocked.
        """
        policy_action = _ACTION_TYPE_TO_POLICY_ACTION.get(
            proposal.action_type, PolicyAction.UPDATE
        )
        decision = self._policy.evaluate(
            action=policy_action,
            risk=proposal.risk,
            impact=ImpactLevel.LOW,
        )
        verdict = _DECISION_TO_VERDICT[decision]
        if verdict == PolicyVerdict.ALLOW:
            return PolicyCheckResult(passed=True)
        return PolicyCheckResult(
            passed=False,
            reason=f"Policy verdict: {verdict.value}",
        )
