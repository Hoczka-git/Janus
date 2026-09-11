"""CLI command handlers for 'janus research' subcommands."""
import sys

from janus.services.research_artifacts import (
    load_artifact,
    load_all_artifacts,
)
from janus.services.artifact_linking import link_artifact_to_goal


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
    print()
    print("Examples:")
    print("  janus research add research/report.md")
    print("  janus research show 2026-08-31-glue-report")
    print("  janus research list")
    print('  janus research link 2026-08-31-glue-report --goal "GLUE biotech research"')
    print('  janus research promote-finding 2026-08-31-glue-report 1 --decision 005')


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

    from janus.integrations.markdown_research import RESEARCH_DIR, _parse_artifact
    from janus.integrations.markdown_research import save_artifact as _save_artifact, _slugify

    # Parse the file into a ResearchArtifact
    file_path = __import__("pathlib").Path(path)
    try:
        artifact = _parse_artifact(file_path)
    except Exception as exc:
        print(f"Error: failed to parse artifact: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        created_path = _save_artifact(artifact)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Created research artifact: {artifact.title}")
    print(f"  Slug: {created_path.stem}")
    print(f"  Findings: {len(artifact.findings)}")


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
            icon = {"wyzszy": "✓", "sredni": "○", "niski": "!"}.get(f.confidence, "?")
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
