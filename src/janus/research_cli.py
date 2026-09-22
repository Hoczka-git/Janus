"""CLI command handlers for 'janus research' subcommands."""
import sys

from janus.services.research_artifacts import (
    load_artifact,
    load_all_artifacts,
)
from janus.services.artifact_linking import link_artifact_to_goal
from janus.services.curation_gate import (
    create_curation_proposal,
    approve_proposal,
    reject_proposal,
    defer_proposal,
    get_proposal,
    list_proposals,
    promote_to_vault,
)
from janus.services.curation_gate_error import CurationGateError
from janus.services.knowledge_pipeline import (
    validate_artifact,
    generate_summary,
    emit_knowledge_gaps_as_attention,
)


def print_research_help() -> None:
    """Print help for the 'janus research' command."""
    print("Usage: janus research <command> [options]")
    print()
    print("Commands:")
    print("  add <path>              Create artifact from a markdown file")
    print("  show <slug>             Display artifact with findings")
    print("  list                    List all artifacts")
    print("  link <slug> --goal <title>  Link artifact to a goal")
    print("  promote-finding <slug> <idx> --decision <adr>  Link a finding to a decision")
    print("  propose <slug>          Create a curation proposal for a research artifact")
    print("  approve <proposal-id>   Approve a curation proposal for vault promotion")
    print("  reject <proposal-id>    Reject a curation proposal")
    print("  defer <proposal-id>     Defer a curation proposal")
    print("  promote <proposal-id>   Promote an approved proposal to the Obsidian vault")
    print("  show-proposal <proposal-id>  Show a curation proposal's status")
    print("  list-proposals          List curation proposals (optionally --state)")
    print()
    print("Examples:")
    print("  janus research add research/report.md")
    print("  janus research show 2026-08-31-glue-report")
    print("  janus research list")
    print('  janus research link 2026-08-31-glue-report --goal "GLUE biotech research"')
    print('  janus research promote-finding 2026-08-31-glue-report 1 --decision 005')
    print('  janus research propose 2026-08-31-glue-report')
    print('  janus research approve cp-a1b2c3d4')
    print('  janus research promote cp-a1b2c3d4')


def handle_research_add(args: list[str]) -> None:
    """janus research add <path>

    Create a research artifact from a markdown file.
    The file must be a valid research artifact markdown (frontmatter + sections).
    """
    if not args:
        print("Error: file path required", file=sys.stderr)
        print("Usage: janus research add <path>", file=sys.stderr)
        sys.exit(1)
    if args[0] in ("-h", "--help"):
        print("Usage: janus research add <path>")
        print()
        print("Create a research artifact from a markdown file.")
        print()
        print("Options:")
        print("  -h, --help  Show this help message")
        return

    path = args[0]
    import os
    if not os.path.exists(path):
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    from janus.integrations.markdown_research import RESEARCH_DIR, _parse_artifact_content
    from janus.services.research_artifacts import create_artifact_via_ingest

    # Route through the canonical ADR-005 ingestion gate instead of calling
    # save_artifact directly — this adds validation / normalization / dedup.
    file_path = __import__("pathlib").Path(path)
    body = file_path.read_text(encoding="utf-8")
    try:
        result = create_artifact_via_ingest(body, title=file_path.stem)
    except Exception as exc:
        print(f"Error: failed to ingest artifact: {exc}", file=sys.stderr)
        sys.exit(1)

    # The ingestion gate normalizes the body and persists via create_artifact
    # / update_artifact (which use atomic_io).  Re-read the persisted artifact
    # to report its title, slug and findings to the user.
    from janus.services.research_artifacts import load_artifact
    from janus.integrations.markdown_research import _slugify
    artifact = _parse_artifact_content(body)
    slug = _slugify(artifact.title)
    try:
        persisted = load_artifact(slug)
    except ValueError:
        persisted = artifact
    created_path = RESEARCH_DIR / f"{slug}.md"
    print(f"Created research artifact: {persisted.title}")
    print(f"  Slug: {slug}")
    print(f"  Findings: {len(persisted.findings)}")


def handle_research_show(args: list[str]) -> None:
    """janus research show <slug>

    Display a research artifact with its findings, sources, and links.
    """
    if not args or args[0] in ("-h", "--help"):
        print("Usage: janus research show <slug>")
        print()
        print("Display a research artifact with its findings.")
        return

    slug = args[0]
    try:
        artifact = load_artifact(slug)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"JANUS — RESEARCH ARTIFACT")
    print("=" * 60)
    print(f"  Title:  {artifact.title}")
    print(f"  Type:   {artifact.artifact_type}")
    print(f"  Target: {artifact.target or '(none)'}")
    print(f"  Version: {artifact.version}")
    if artifact.created_at:
        print(f"  Created: {artifact.created_at.isoformat()}")
    if artifact.updated_at:
        print(f"  Updated: {artifact.updated_at.isoformat()}")
    if artifact.summary:
        print(f"\n  Summary:\n    {artifact.summary}")
    if artifact.conclusions:
        print(f"\n  Conclusions:\n    {artifact.conclusions}")

    if artifact.findings:
        print(f"\n  Findings ({len(artifact.findings)}):")
        for i, f in enumerate(artifact.findings):
            icon = {"wyzszy": "+", "sredni": "o", "niski": "!"}.get(f.confidence, "?")
            print(f"    [{icon}] Finding {i+1}: {f.statement}")
            if f.topic:
                print(f"        Topic: {f.topic}")
            print(f"        Confidence: {f.confidence}")
            if f.sources:
                print(f"        Sources ({len(f.sources)}):")
                for src in f.sources:
                    print(f"          - {src.url}")
                    if src.title:
                        print(f"            Title: {src.title}")
                    if src.accessed_at:
                        print(f"            Accessed: {src.accessed_at.isoformat()}")
            if f.decision_numbers:
                print(f"        Decisions: {', '.join(f.decision_numbers)}")
    else:
        print("\n  No findings.")

    if artifact.linked_goal_titles:
        print(f"\n  Linked goals:")
        for gt in artifact.linked_goal_titles:
            print(f"    - {gt}")
    if artifact.decision_numbers:
        print(f"\n  Decision numbers: {', '.join(artifact.decision_numbers)}")


def handle_research_list(args: list[str]) -> None:
    """janus research list

    List all research artifacts.
    """
    if args and args[0] in ("-h", "--help"):
        print("Usage: janus research list")
        print()
        print("List all research artifacts.")
        return

    artifacts = load_all_artifacts()
    if not artifacts:
        print("No research artifacts.")
        return

    print(f"Research artifacts ({len(artifacts)}):")
    print("=" * 60)
    for art in artifacts:
        print(f"  {art.title}")
        print(f"    Type: {art.artifact_type}, Target: {art.target or '(none)'}")
        print(f"    Findings: {len(art.findings)}")
        if art.linked_goal_titles:
            print(f"    Goals: {', '.join(art.linked_goal_titles)}")
        if art.decision_numbers:
            print(f"    Decisions: {', '.join(art.decision_numbers)}")
        print()


def handle_research_link(args: list[str]) -> None:
    """janus research link <slug> --goal <goal_title>

    Link a research artifact to a goal (bidirectional).
    """
    if not args or args[0] in ("-h", "--help"):
        print("Usage: janus research link <slug> --goal <goal_title>")
        print()
        print("Link a research artifact to a goal (bidirectional).")
        return

    slug = args[0]
    goal_title = None
    i = 1
    while i < len(args):
        if args[i] == "--goal" and i + 1 < len(args):
            goal_title = args[i + 1]
            i += 2
        else:
            i += 1

    if not goal_title:
        print("Error: --goal <title> is required", file=sys.stderr)
        sys.exit(1)

    try:
        artifact = load_artifact(slug)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        link_artifact_to_goal(artifact.title, goal_title, artifact)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Linked artifact '{artifact.title}' to goal '{goal_title}'")


def handle_research_promote_finding(args: list[str]) -> None:
    """janus research promote-finding <slug> <finding_index> --decision <adr>

    Link a finding (by zero-based index) to a decision.
    """
    if not args or args[0] in ("-h", "--help"):
        print("Usage: janus research promote-finding <slug> <finding_index> --decision <adr>")
        print()
        print("Link a finding to a decision (bidirectional).")
        print("  <finding_index>  Zero-based index into the artifact's findings list")
        print("  --decision <adr>  ADR number (e.g. '005')")
        return

    slug = args[0]
    try:
        finding_index = int(args[1])
    except (IndexError, ValueError):
        print("Error: finding_index (integer) is required", file=sys.stderr)
        sys.exit(1)

    adr_number = None
    i = 2
    while i < len(args):
        if args[i] == "--decision" and i + 1 < len(args):
            adr_number = args[i + 1]
            i += 2
        else:
            i += 1

    if not adr_number:
        print("Error: --decision <adr> is required", file=sys.stderr)
        sys.exit(1)

    try:
        artifact = load_artifact(slug)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if finding_index < 0 or finding_index >= len(artifact.findings):
        print(
            f"Error: finding index {finding_index} out of range "
            f"(artifact has {len(artifact.findings)} findings)",
            file=sys.stderr,
        )
        sys.exit(1)

    from janus.services.decisions import link_finding_to_decision
    link_finding_to_decision(adr_number, artifact.title, finding_index)
    print(
        f"Linked finding {finding_index} of '{artifact.title}' to decision {adr_number}"
    )


# ── Curation gate commands ───────────────────────────────────────────────────

def handle_research_propose(args: list[str]) -> None:
    """janus research propose <slug> [--approver <name>] [--note <note>]

    Run the knowledge pipeline (validation + summary generation) on a research
    artifact and create a CurationProposal in pending_approval state.
    """
    if not args or args[0] in ("-h", "--help"):
        print("Usage: janus research propose <slug> [--approver <name>] [--note <note>]")
        print()
        print("Create a curation proposal for a research artifact.")
        print("  Runs validation + summary generation, then gates the summary.")
        return

    slug = args[0]
    try:
        artifact = load_artifact(slug)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Step 1: validate
    warnings = validate_artifact(artifact)
    # Step 2: generate summary
    summary = generate_summary(artifact)
    # Step 3: create curation proposal (pending_approval)
    proposal = create_curation_proposal(
        summary,
        warnings=[
            {"category": w.category, "message": w.message,
             "finding_index": w.finding_index}
            for w in warnings
        ],
    )

    print(f"Created curation proposal: cp-{proposal.proposal_id}")
    print(f"  Artifact: {artifact.title}")
    print(f"  State: {proposal.approval_state}")
    print(f"  Warnings: {len(proposal.warnings)}")
    print(f"  Knowledge gaps: {len(summary.knowledge_gaps)}")
    print(f"  Entities: {', '.join(summary.entities) if summary.entities else '(none)'}")


def handle_research_approve(args: list[str]) -> None:
    """janus research approve <proposal-id> [--approver <name>] [--note <note>]"""
    if not args or args[0] in ("-h", "--help"):
        print("Usage: janus research approve <proposal-id> [--approver <name>] [--note <note>]")
        return

    proposal_id = args[0]
    approver = ""
    note = ""
    i = 1
    while i < len(args):
        if args[i] == "--approver" and i + 1 < len(args):
            approver = args[i + 1]
            i += 2
        elif args[i] == "--note" and i + 1 < len(args):
            note = args[i + 1]
            i += 2
        else:
            i += 1

    try:
        proposal = approve_proposal(proposal_id, approver=approver, note=note)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Approved proposal cp-{proposal.proposal_id}")
    print(f"  State: {proposal.approval_state}")
    if proposal.approver:
        print(f"  Approver: {proposal.approver}")
    print(f"  Now run: janus research promote {proposal.proposal_id}")


def handle_research_reject(args: list[str]) -> None:
    """janus research reject <proposal-id> [--approver <name>] [--note <note>]"""
    if not args or args[0] in ("-h", "--help"):
        print("Usage: janus research reject <proposal-id> [--approver <name>] [--note <note>]")
        return

    proposal_id = args[0]
    approver = ""
    note = ""
    i = 1
    while i < len(args):
        if args[i] == "--approver" and i + 1 < len(args):
            approver = args[i + 1]
            i += 2
        elif args[i] == "--note" and i + 1 < len(args):
            note = args[i + 1]
            i += 2
        else:
            i += 1

    try:
        proposal = reject_proposal(proposal_id, approver=approver, note=note)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Rejected proposal cp-{proposal.proposal_id}")
    print(f"  State: {proposal.approval_state}")
    if proposal.decision_note:
        print(f"  Note: {proposal.decision_note}")


def handle_research_defer(args: list[str]) -> None:
    """janus research defer <proposal-id> [--approver <name>] [--note <note>]"""
    if not args or args[0] in ("-h", "--help"):
        print("Usage: janus research defer <proposal-id> [--approver <name>] [--note <note>]")
        return

    proposal_id = args[0]
    approver = ""
    note = ""
    i = 1
    while i < len(args):
        if args[i] == "--approver" and i + 1 < len(args):
            approver = args[i + 1]
            i += 2
        elif args[i] == "--note" and i + 1 < len(args):
            note = args[i + 1]
            i += 2
        else:
            i += 1

    try:
        proposal = defer_proposal(proposal_id, approver=approver, note=note)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Deferred proposal cp-{proposal.proposal_id}")
    print(f"  State: {proposal.approval_state}")


def handle_research_promote(args: list[str]) -> None:
    """janus research promote <proposal-id>

    Promote an approved curation proposal to the Obsidian vault.
    Raises CurationGateError if the proposal is not approved.
    """
    if not args or args[0] in ("-h", "--help"):
        print("Usage: janus research promote <proposal-id>")
        print()
        print("Promote an approved curation proposal to the Obsidian vault.")
        print("  The proposal must be in 'approved' state (use 'janus research approve' first).")
        return

    proposal_id = args[0]
    try:
        vault_path = promote_to_vault(proposal_id)
    except CurationGateError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Promoted proposal cp-{proposal_id} to vault:")
    print(f"  {vault_path}")


def handle_research_show_proposal(args: list[str]) -> None:
    """janus research show-proposal <proposal-id>"""
    if not args or args[0] in ("-h", "--help"):
        print("Usage: janus research show-proposal <proposal-id>")
        return

    proposal_id = args[0]
    try:
        proposal = get_proposal(proposal_id)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"CURATION PROPOSAL: cp-{proposal.proposal_id}")
    print("=" * 60)
    print(f"  State: {proposal.approval_state}")
    print(f"  Summary: {proposal.summary.title}")
    print(f"  Target: {proposal.summary.target}")
    print(f"  Warnings: {len(proposal.warnings)}")
    for w in proposal.warnings:
        print(f"    - [{w['category']}] {w['message']}")
    print(f"  Knowledge gaps: {len(proposal.summary.knowledge_gaps)}")
    if proposal.approver:
        print(f"  Approver: {proposal.approver}")
    if proposal.decision_note:
        print(f"  Note: {proposal.decision_note}")
    if proposal.vault_path:
        print(f"  Vault: {proposal.vault_path}")
    print(f"  Created: {proposal.created_at.isoformat() if proposal.created_at else 'unknown'}")
    print(f"  Updated: {proposal.updated_at.isoformat() if proposal.updated_at else 'unknown'}")


def handle_research_list_proposals(args: list[str]) -> None:
    """janus research list-proposals [--state <state>]"""
    state = None
    if args and args[0] in ("-h", "--help"):
        print("Usage: janus research list-proposals [--state <state>]")
        print()
        print("List all curation proposals, optionally filtered by state.")
        print(f"  States: {', '.join(('pending_approval', 'approved', 'rejected', 'deferred', 'vaulted'))}")
        return

    i = 0
    while i < len(args):
        if args[i] == "--state" and i + 1 < len(args):
            state = args[i + 1]
            i += 2
        else:
            i += 1

    items = list_proposals(state)
    if not items:
        print("No curation proposals.")
        return

    print(f"Curation proposals ({len(items)}):")
    print("=" * 60)
    for p in items:
        icon = {"pending_approval": "o", "approved": "v", "rejected": "x",
                "deferred": "-", "vaulted": "+"}.get(p.approval_state, "?")
        print(f"  [{icon}] cp-{p.proposal_id}  {p.approval_state}")
        print(f"    Summary: {p.summary.title}")
        print(f"    Warnings: {len(p.warnings)}")
        print()
