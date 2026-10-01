"""CLI approval prompt formatter for P1 Policy Enforcement & Approval Workflow.

Design reference: docs/design/policy_approval_p1_design.md §7.5
"""

from __future__ import annotations

from janus.models.policy import ApprovalRequest


def format_approval_prompt(request: ApprovalRequest) -> str:
    """Format an ApprovalRequest as a human-readable CLI prompt.

    Args:
        request: The approval request to format.

    Returns:
        A formatted multi-line string suitable for CLI display.
    """
    lines = [
        "",
        "=" * 60,
        "  POLICY APPROVAL REQUIRED",
        "=" * 60,
        "",
        f"  Action:   {request.action}",
        f"  Context:  {request.context}",
        f"  Risk:     {request.risk_level.value.upper()}",
        f"  Rule:     {request.policy_rule}",
        "",
        f"  Reason:   {request.rationale}",
        "",
        f"  Approving:  {request.what_approval_entails}",
        f"  If denied:  {request.alternative}",
        "",
        "-" * 60,
    ]
    return "\n".join(lines)
