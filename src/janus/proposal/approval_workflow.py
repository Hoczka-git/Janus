"""Approval workflow — wires the approval gate and policy check together.

This module provides the orchestrator that bridges the ActionProposal model
with the approval gate and policy check, following the boundary rules
defined in ``approval_contract.py``.

Pipeline::

    ActionProposal -> PolicyCheck -> (passed | failed -> ApprovalGate) -> ApprovalContext

The workflow is pure logic — it does not mutate the proposal or record
decisions. It only reads from the gate and returns the combined context.

Design reference: docs/design/policy_approval_p1_design.md S3, S5
"""

from __future__ import annotations

from janus.proposal.approval_contract import (
    ApprovalContext,
    ApprovalGate,
    PolicyCheck,
    PolicyCheckResult,
)
from janus.proposal.models import ActionProposal


class ApprovalWorkflow:
    """Orchestrates the approval gate and policy check for an ActionProposal.

    This is the wiring layer that:

    1. Runs ``PolicyCheck.check(proposal)`` first.
    2. If ``passed=True``: returns :class:`ApprovalContext` without invoking the gate.
    3. If ``passed=False``: checks the :class:`ApprovalGate` for an existing decision.

    The workflow is pure logic — it does not mutate the proposal or record
    decisions. It only reads from the gate and returns the combined context.

    Usage::

        workflow = ApprovalWorkflow(gate, checker)
        context = workflow.evaluate(proposal)
        if context.is_approved:
            # safe to proceed
            ...

    Attributes:
        approval_gate: The gate that records and retrieves human decisions.
        policy_check: The check that evaluates proposal content against policy.
    """

    def __init__(
        self,
        approval_gate: ApprovalGate,
        policy_check: PolicyCheck,
    ) -> None:
        self._approval_gate = approval_gate
        self._policy_check = policy_check

    @property
    def approval_gate(self) -> ApprovalGate:
        """The approval gate used by this workflow."""
        return self._approval_gate

    @property
    def policy_check(self) -> PolicyCheck:
        """The policy check used by this workflow."""
        return self._policy_check

    def evaluate(self, proposal: ActionProposal) -> ApprovalContext:
        """Evaluate an ActionProposal through the approval workflow.

        The policy check runs first. Based on its result:

        - ``passed=True``: the proposal may proceed without human approval.
          The gate is not invoked.
        - ``passed=False``: the gate is checked for an existing decision. If a
          decision has been recorded, it is included in the context.

        Args:
            proposal: The ActionProposal to evaluate.

        Returns:
            An :class:`ApprovalContext` with the policy result and, if
            applicable, the approval decision from the gate.
        """
        result = self._policy_check.check(proposal)

        if result.passed:
            return ApprovalContext(
                proposal=proposal,
                policy_result=result,
            )

        # Not passed — check the gate for an existing decision
        status = self._approval_gate.check_approval(proposal.proposal_id)
        decision = self._approval_gate.get_decision(proposal.proposal_id)

        return ApprovalContext(
            proposal=proposal,
            policy_result=result,
            approval_status=status,
            decision=decision,
        )
