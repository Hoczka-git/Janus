"""Policy-specific exceptions for P1 Policy Enforcement & Approval Workflow.

Design reference: docs/design/policy_approval_p1_design.md §7.4
"""

from __future__ import annotations


class PolicyDenialError(RuntimeError):
    """Raised when a policy evaluation returns a DENY verdict.

    The action is blocked and cannot proceed even with approval.
    The ``rationale`` attribute carries the human-readable reason.
    """

    def __init__(self, rationale: str, gate_id: str | None = None) -> None:
        self.rationale = rationale
        self.gate_id = gate_id
        msg = f"Policy denial: {rationale}"
        if gate_id:
            msg += f" (gate: {gate_id})"
        super().__init__(msg)


class PolicyApprovalRequired(RuntimeError):
    """Raised when a policy evaluation returns an ASK verdict.

    The action requires explicit user approval before proceeding.
    The ``request`` attribute carries the structured ApprovalRequest.
    """

    def __init__(self, request: "ApprovalRequest") -> None:
        self.request = request
        super().__init__(
            f"Policy approval required: {request.rationale} "
            f"(rule: {request.policy_rule})"
        )


# Forward reference for type checking
from janus.models.policy import ApprovalRequest  # noqa: E402
