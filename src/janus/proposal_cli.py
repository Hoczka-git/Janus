"""CLI command handlers for 'janus proposal' and 'janus execution'.

Provides the workflow:
    list proposals -> inspect proposal -> approve/reject -> execute -> inspect result

Usage:
    janus proposal list
    janus proposal show <proposal-id>
    janus proposal approve <proposal-id>
    janus proposal reject <proposal-id>
    janus proposal execute <proposal-id>
    janus execution show <execution-id>
    janus execution list
"""

from __future__ import annotations

import sys

from janus.execution.models import ExecutionStatus
from janus.execution.proposal_service import ProposalService
from janus.execution.service import ExecutionService
from janus.proposal.models import ProposalStatus


def print_proposal_help() -> None:
    """Print help for the 'janus proposal' command."""
    print("Usage: janus proposal <subcommand> [options]")
    print("")
    print("Manage action proposals.")
    print("")
    print("Subcommands:")
    print("  list       List all proposals")
    print("  show       Show a specific proposal")
    print("  approve    Approve a proposal")
    print("  reject     Reject a proposal")
    print("  execute    Execute an approved proposal")
    print("")
    print("Options:")
    print("  -h, --help  Show this help message")


def print_execution_help() -> None:
    """Print help for the 'janus execution' command."""
    print("Usage: janus execution <subcommand> [options]")
    print("")
    print("Inspect execution results.")
    print("")
    print("Subcommands:")
    print("  list       List all execution results")
    print("  show       Show a specific execution result")
    print("")
    print("Options:")
    print("  -h, --help  Show this help message")


def handle_proposal_list(args: list[str]) -> None:
    """List all proposals.

    Usage:
        janus proposal list
    """
    if args and args[0] in ("-h", "--help"):
        print_proposal_help()
        return

    service = ProposalService()
    proposals = service.list_proposals()

    if not proposals:
        print("No proposals found.")
        return

    print("ACTION PROPOSALS")
    print("-" * 60)
    for p in proposals:
        target = p.target_id or "-"
        print(f"[{p.proposal_id}] {p.action_type.value}")
        print(f"  Target: {target}")
        print(f"  Status: {p.status.value}")
        print(f"  Risk: {p.risk.value}")
        print(f"  Reason: {p.reason}")
        print()


def handle_proposal_show(args: list[str]) -> None:
    """Show a specific proposal.

    Usage:
        janus proposal show <proposal-id>
    """
    if not args or args[0] in ("-h", "--help"):
        print("Usage: janus proposal show <proposal-id>")
        return

    proposal_id = args[0]
    service = ProposalService()
    proposal = service.get_proposal(proposal_id)

    if proposal is None:
        print(f"Proposal not found: {proposal_id}", file=sys.stderr)
        sys.exit(1)

    print(f"Proposal: {proposal.proposal_id}")
    print(f"Action: {proposal.action_type.value}")
    print(f"Target: {proposal.target_id or '-'}")
    print(f"Status: {proposal.status.value}")
    print(f"Risk: {proposal.risk.value}")
    print(f"Source: {proposal.source}")
    print(f"Reason: {proposal.reason}")
    print(f"Created: {proposal.created_at}")
    print(f"Updated: {proposal.updated_at}")

    if proposal.parameters:
        print("Parameters:")
        for key, value in proposal.parameters.items():
            print(f"  {key}: {value}")

    if proposal.metadata:
        print("Metadata:")
        for key, value in proposal.metadata.items():
            print(f"  {key}: {value}")


def handle_proposal_approve(args: list[str]) -> None:
    """Approve a proposal.

    Usage:
        janus proposal approve <proposal-id>
    """
    if not args or args[0] in ("-h", "--help"):
        print("Usage: janus proposal approve <proposal-id>")
        return

    proposal_id = args[0]
    service = ProposalService()
    proposal = service.update_status(proposal_id, ProposalStatus.APPROVED)

    if proposal is None:
        print(f"Proposal not found: {proposal_id}", file=sys.stderr)
        sys.exit(1)

    print(f"Proposal {proposal_id} approved.")
    print(f"Action: {proposal.action_type.value}")
    print(f"Target: {proposal.target_id or '-'}")


def handle_proposal_reject(args: list[str]) -> None:
    """Reject a proposal.

    Usage:
        janus proposal reject <proposal-id>
    """
    if not args or args[0] in ("-h", "--help"):
        print("Usage: janus proposal reject <proposal-id>")
        return

    proposal_id = args[0]
    service = ProposalService()
    proposal = service.update_status(proposal_id, ProposalStatus.REJECTED)

    if proposal is None:
        print(f"Proposal not found: {proposal_id}", file=sys.stderr)
        sys.exit(1)

    print(f"Proposal {proposal_id} rejected.")


def handle_proposal_execute(args: list[str]) -> None:
    """Execute an approved proposal.

    Usage:
        janus proposal execute <proposal-id>
    """
    if not args or args[0] in ("-h", "--help"):
        print("Usage: janus proposal execute <proposal-id>")
        return

    proposal_id = args[0]

    # Load proposal
    proposal_service = ProposalService()
    proposal = proposal_service.get_proposal(proposal_id)

    if proposal is None:
        print(f"Proposal not found: {proposal_id}", file=sys.stderr)
        sys.exit(1)

    # Execute
    execution_service = ExecutionService()
    result = execution_service.execute(proposal)

    # Update proposal status
    if result.is_success:
        proposal_service.update_status(proposal_id, ProposalStatus.EXECUTED)

    # Print result
    print(f"Execution: {result.execution_id}")
    print(f"Proposal: {result.proposal_id}")
    print(f"Action: {result.action_type.value}")
    print(f"Target: {result.target_id or '-'}")
    print(f"Status: {result.status.value}")

    if result.error:
        print(f"Error: {result.error}")

    if result.result_details:
        print("Details:")
        for key, value in result.result_details.items():
            print(f"  {key}: {value}")


def handle_execution_list(args: list[str]) -> None:
    """List all execution results.

    Usage:
        janus execution list
    """
    if args and args[0] in ("-h", "--help"):
        print_execution_help()
        return

    service = ExecutionService()
    executions = service.list_executions()

    if not executions:
        print("No executions found.")
        return

    print("EXECUTION RESULTS")
    print("-" * 60)
    for e in executions:
        target = e.target_id or "-"
        print(f"[{e.execution_id}] {e.action_type.value}")
        print(f"  Proposal: {e.proposal_id}")
        print(f"  Target: {target}")
        print(f"  Status: {e.status.value}")
        if e.error:
            print(f"  Error: {e.error}")
        print()


def handle_execution_show(args: list[str]) -> None:
    """Show a specific execution result.

    Usage:
        janus execution show <execution-id>
    """
    if not args or args[0] in ("-h", "--help"):
        print("Usage: janus execution show <execution-id>")
        return

    execution_id = args[0]
    service = ExecutionService()
    result = service.get_execution(execution_id)

    if result is None:
        print(f"Execution not found: {execution_id}", file=sys.stderr)
        sys.exit(1)

    print(f"Execution: {result.execution_id}")
    print(f"Proposal: {result.proposal_id}")
    print(f"Action: {result.action_type.value}")
    print(f"Target: {result.target_id or '-'}")
    print(f"Status: {result.status.value}")
    print(f"Timestamp: {result.timestamp}")

    if result.error:
        print(f"Error: {result.error}")

    if result.result_details:
        print("Details:")
        for key, value in result.result_details.items():
            print(f"  {key}: {value}")
