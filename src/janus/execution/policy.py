"""Policy gate for the Execution Engine V1.

This module implements the policy layer between approval and execution.
It verifies that a proposal is valid, approved, and safe to execute.

The policy gate checks:
1. The proposal exists
2. The proposal is valid
3. The proposal has an explicit approval
4. The proposal has not already been executed
5. The requested action type is allowed
6. Required parameters are present
7. The target exists where required

A policy failure prevents execution and produces an explicit result.

Design reference: docs/design/action_proposal_engine_v1.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from janus.execution.models import PolicyDecision
from janus.proposal.models import ActionProposal, ActionType, ProposalStatus


# Supported action types for V1 execution
SUPPORTED_ACTION_TYPES: frozenset[ActionType] = frozenset({
    ActionType.CREATE_TASK,
    ActionType.UPDATE_TASK,
    ActionType.RESCHEDULE_TASK,
})

# Required parameters per action type
REQUIRED_PARAMETERS: dict[ActionType, tuple[str, ...]] = {
    ActionType.CREATE_TASK: ("title",),
    ActionType.UPDATE_TASK: ("risk_description",),
    ActionType.RESCHEDULE_TASK: ("new_due_date",),
}


class PolicyGate:
    """Policy gate that validates proposals before execution.

    This is a pure-logic component: it does not perform I/O. The
    idempotency check (whether a proposal has already been executed)
    is delegated to the caller via the ``is_executed`` callback.
    """

    def __init__(
        self,
        is_executed: Any = None,
    ) -> None:
        """Initialize the policy gate.

        Args:
            is_executed: Optional callable that takes a proposal_id and
                returns True if the proposal has already been executed.
        """
        self._is_executed = is_executed

    def evaluate(self, proposal: ActionProposal) -> PolicyDecision:
        """Evaluate whether a proposal is allowed to execute.

        Args:
            proposal: The proposal to evaluate.

        Returns:
            A PolicyDecision indicating whether execution is allowed.
        """
        # 1. Proposal exists
        if not proposal:
            return PolicyDecision(
                allowed=False,
                reason="Proposal is None",
            )

        # 2. Proposal is valid (has required fields)
        if not proposal.proposal_id:
            return PolicyDecision(
                allowed=False,
                reason="Proposal has no ID",
                proposal_id=proposal.proposal_id,
            )

        if not proposal.reason:
            return PolicyDecision(
                allowed=False,
                reason="Proposal has no reason",
                proposal_id=proposal.proposal_id,
            )

        # 3. Proposal has explicit approval
        if proposal.status != ProposalStatus.APPROVED:
            return PolicyDecision(
                allowed=False,
                reason=f"Proposal status is {proposal.status.value}, not APPROVED",
                proposal_id=proposal.proposal_id,
            )

        # 4. Proposal has not already been executed
        if self._is_executed and self._is_executed(proposal.proposal_id):
            return PolicyDecision(
                allowed=False,
                reason="Proposal has already been executed",
                proposal_id=proposal.proposal_id,
            )

        # 5. Action type is allowed
        if proposal.action_type not in SUPPORTED_ACTION_TYPES:
            return PolicyDecision(
                allowed=False,
                reason=f"Action type {proposal.action_type.value} is not supported",
                proposal_id=proposal.proposal_id,
            )

        # 6. Required parameters are present
        required = REQUIRED_PARAMETERS.get(proposal.action_type, ())
        missing = [p for p in required if p not in proposal.parameters]
        if missing:
            return PolicyDecision(
                allowed=False,
                reason=f"Missing required parameters: {', '.join(missing)}",
                proposal_id=proposal.proposal_id,
            )

        # 7. Target exists where required (for UPDATE_TASK and RESCHEDULE_TASK)
        if proposal.action_type in (ActionType.UPDATE_TASK, ActionType.RESCHEDULE_TASK):
            if not proposal.target_id:
                return PolicyDecision(
                    allowed=False,
                    reason=f"Action type {proposal.action_type.value} requires a target_id",
                    proposal_id=proposal.proposal_id,
                )

        return PolicyDecision(
            allowed=True,
            reason="Policy check passed",
            proposal_id=proposal.proposal_id,
        )
