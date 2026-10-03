"""Approval workflow — wires the approval gate and policy check together.

This module provides the orchestrator that bridges the ActionProposal model
with the approval gate and policy check, following the boundary rules
defined in ``approval_contract.py``.

Pipeline::

    ActionProposal -> PolicyCheck -> (ALLOW | ASK -> ApprovalGate | DENY) -> ApprovalContext

The workflow is pure logic — it does not mutate the proposal or record
decisions. It only reads from the gate and returns the combined context.

Design reference: docs/design/policy_approval_p1_design.md S3, S5
"""

from __future__ import annotations

from janus.models.policy_p1 import PolicyVerdict
from janus.proposal.approval_contract import (
    ApprovalContext,
    ApprovalGate,
    PolicyCheck,
)
from janus.proposal.models import ActionProposal


class ApprovalWorkflow:
    """Orchestrates the approval gate and policy check for an ActionProposal.

    This is the wiring layer that:

    1. Runs ``PolicyCheck.check(proposal)`` first.
    2. If ``ALLOW``: returns :class:`ApprovalContext` without invoking the gate.
    3. If ``ASK``: checks the :class:`ApprovalGate` for an existing decision.
    4. If ``DENY``: returns :class:`ApprovalContext` without invoking the gate.

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

        The policy check runs first. Based on its verdict:

        - ``ALLOW``: the proposal may proceed without human approval.
          The gate is not invoked.
        - ``ASK``: the gate is checked for an existing decision. If a
          decision has been recorded, it is included in the context.
        - ``DENY``: the proposal is blocked. The gate is not invoked.

        Args:
            proposal: The ActionProposal to evaluate.

        Returns:
            An :class:`ApprovalContext` with the policy verdict and, if
            applicable, the approval decision from the gate.
        """
        verdict = self._policy_check.check(proposal)

        if verdict in (PolicyVerdict.ALLOW, PolicyVerdict.DENY):
            return ApprovalContext(
                proposal=proposal,
                policy_verdict=verdict,
            )

        # ASK — check the gate for an existing decision
        status = self._approval_gate.check_approval(proposal.proposal_id)
        decision = self._approval_gate.get_decision(proposal.proposal_id)

        return ApprovalContext(
            proposal=proposal,
            policy_verdict=verdict,
            approval_status=status,
            decision=decision,
        )
