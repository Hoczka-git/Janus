"""CLI command handlers for 'janus decision' subcommands.

Provides write/read access to the ADR decision chain:
- propose: create a new ADR from a markdown file
- link-finding: link a research artifact finding to a decision
- link-goal: link a decision to a goal
"""
import sys
from pathlib import Path

from janus.models.decision import Decision, VALID_DECISION_STATUSES
from janus.services.decisions import (
    create_decision,
    link_decision_to_goal,
    link_finding_to_decision as _link_finding_to_decision,
    get_decision,
    load_decisions,
)


def print_decision_help() -> None:
    """Print help for the 'janus decision' command."""
    print("Usage: janus decision <command> [options]")
    print()
    print("Commands:")
    print("  propose <path>           Create an ADR from a YAML/markdown file")
    print("  link-finding <adr> <slug> <idx>   Link a finding (by index) to a decision")
    print("  link-goal <adr> <goal-title>      Link a decision to a goal")
    print("  list                     List all ADR decisions")
    print("  show <adr>               Show a single decision by ADR number")
    print()
    print("Examples:")
    print("  janus decision propose docs/decisions/005-my-decision.md")
    print('  janus decision link-finding 005 my-research-slug 1')
    print('  janus decision link-goal 005 "GLUE biotech research"')
    print("  janus decision list")
    print("  janus decision show 005")


def handle_decision_list(args: list[str]) -> None:
    """janus decision list — List all ADR decisions."""
    decisions = load_decisions()
    if not decisions:
        print("No decisions found.")
        return
    print(f"Decisions ({len(decisions)}):")
    print("=" * 60)
    for d in decisions:
        print(f"  ADR-{d.adr_number}: {d.title}")
        print(f"    Status: {d.status}")
        if d.goal_titles:
            print(f"    Goals: {', '.join(d.goal_titles)}")
        if d.finding_sources:
            print(f"    Informed by: {', '.join(d.finding_sources)}")
        print()


def handle_decision_show(args: list[str]) -> None:
    """janus decision show <adr> — Show a single decision by ADR number."""
    if not args or args[0] in ("-h", "--help"):
        print("Usage: janus decision show <adr-number>")
        print()
        print("Display a single ADR decision by its number (e.g. '005' or '5').")
        return
    adr_number = args[0]
    try:
        d = get_decision(adr_number)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"ADR-{d.adr_number}: {d.title}")
    print(f"  Status: {d.status}")
    if d.supersedes_adr:
        print(f"  Supersedes: ADR-{d.supersedes_adr}")
    if d.created_at:
        print(f"  Created: {d.created_at.isoformat()}")
    if d.updated_at:
        print(f"  Updated: {d.updated_at.isoformat()}")
    if d.context:
        print(f"\n  Context:\n    {d.context}")
    if d.decision:
        print(f"\n  Decision:\n    {d.decision}")
    if d.consequences:
        print(f"\n  Consequences:\n    {d.consequences}")
    if d.finding_sources:
        print(f"\n  Informed by:")
        for src in d.finding_sources:
            print(f"    - {src}")
    if d.goal_titles:
        print(f"\n  Linked goals:")
        for gt in d.goal_titles:
            print(f"    - {gt}")


def handle_decision_propose(args: list[str]) -> None:
    """janus decision propose <path>

    Create an ADR from a markdown file. The file must contain YAML
    frontmatter with decision metadata (adr_number, title, status,
    context, decision, consequences, finding_sources, goal_titles).
    """
    if not args or args[0] in ("-h", "--help"):
        print("Usage: janus decision propose <path>")
        print()
        print("Create a new ADR (Architectural Decision Record) from a markdown file.")
        print()
        print("The file must have YAML frontmatter with at least:")
        print("  adr_number, title, status, context, decision, consequences")
        return

    path = Path(args[0])
    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        decision = _parse_decision_file(path)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        adr_path = create_decision(decision)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Created ADR: ADR-{decision.adr_number}: {decision.title}")
    print(f"  Path: {adr_path}")


def handle_decision_link_finding(args: list[str]) -> None:
    """janus decision link-finding <adr> <artifact-slug> <finding-index>

    Link a research artifact's finding (by zero-based index) to a decision.
    Updates both the ADR's 'Informed by' section and the artifact's
    Finding.decision_numbers.
    """
    if not args or args[0] in ("-h", "--help"):
        print("Usage: janus decision link-finding <adr> <artifact-slug> <finding-index>")
        print()
        print("Link a research artifact finding to a decision (bidirectional).")
        print("  <adr>             ADR number (e.g. '005')")
        print("  <artifact-slug>   Slug of the research artifact (filename stem)")
        print("  <finding-index>   Zero-based index into the artifact's findings list")
        return

    if len(args) < 3:
        print("Error: adr, artifact-slug, and finding-index are required", file=sys.stderr)
        print("Usage: janus decision link-finding <adr> <artifact-slug> <finding-index>",
              file=sys.stderr)
        sys.exit(1)

    adr_number = args[0]
    artifact_slug = args[1]
    try:
        finding_index = int(args[2])
    except ValueError:
        print(f"Error: finding-index must be an integer, got {args[2]!r}", file=sys.stderr)
        sys.exit(1)

    # Load the artifact to get its title
    from janus.services.research_artifacts import load_artifact
    try:
        artifact = load_artifact(artifact_slug)
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

    try:
        _link_finding_to_decision(adr_number, artifact.title, finding_index)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Linked finding {finding_index} of '{artifact.title}' to decision {adr_number}")


def handle_decision_link_goal(args: list[str]) -> None:
    """janus decision link-goal <adr> <goal-title>

    Link a decision to a goal (bidirectional). Updates both the ADR
    (appends a [[Goal: title]] wikilink) and Goal.decision_numbers.
    """
    if not args or args[0] in ("-h", "--help"):
        print("Usage: janus decision link-goal <adr> <goal-title>")
        print()
        print("Link a decision to a goal (bidirectional).")
        print("  <adr>          ADR number (e.g. '005')")
        print("  <goal-title>   Title of the goal to link")
        return

    if len(args) < 2:
        print("Error: adr and goal-title are required", file=sys.stderr)
        print("Usage: janus decision link-goal <adr> <goal-title>", file=sys.stderr)
        sys.exit(1)

    adr_number = args[0]
    goal_title = args[1]

    try:
        link_decision_to_goal(adr_number, goal_title)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Linked decision {adr_number} to goal '{goal_title}'")


def _parse_decision_file(path: Path) -> Decision:
    """Parse a decision markdown file into a Decision object.

    Expects YAML frontmatter (delimited by ``---``) with keys:
    adr_number, title, status, context, decision, consequences,
    finding_sources, goal_titles.
    """
    content = path.read_text()
    return _parse_decision_content(content)


def _parse_decision_content(content: str) -> Decision:
    """Parse decision markdown text (YAML frontmatter + body) into a Decision.

    Expects YAML frontmatter (delimited by ``---``) with keys:
    adr_number, title, status, context, decision, consequences,
    finding_sources, goal_titles.  Used by both ``_parse_decision_file``
    (CLI file ingestion) and the Hermes→Janus sync listener
    (``execution_feedback._ingest_decision``) where the body arrives as a
    raw string rather than a file on disk.
    """
    frontmatter, body = _split_frontmatter(content)

    adr_number = frontmatter.get("adr_number")
    if not adr_number:
        raise ValueError("frontmatter must include 'adr_number'")

    title = frontmatter.get("title")
    if not title:
        raise ValueError("frontmatter must include 'title'")

    status = frontmatter.get("status", "proposed")
    if status not in VALID_DECISION_STATUSES:
        raise ValueError(
            f"Invalid status: {status!r}. "
            f"Allowed: {', '.join(VALID_DECISION_STATUSES)}"
        )

    context = frontmatter.get("context", "") or body.strip()
    decision_text = frontmatter.get("decision", "")
    consequences = frontmatter.get("consequences", "")
    finding_sources = _as_list(frontmatter.get("finding_sources", []))
    goal_titles = _as_list(frontmatter.get("goal_titles", []))

    return Decision(
        adr_number=str(adr_number),
        title=title,
        status=status,
        context=context,
        decision=decision_text,
        consequences=consequences,
        finding_sources=finding_sources,
        goal_titles=goal_titles,
    )


def _split_frontmatter(content: str) -> tuple[dict, str]:
    """Split markdown into (frontmatter dict, body).

    Frontmatter is delimited by ``---`` lines.
    """
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, content
    idx = 1
    fm_lines: list[str] = []
    while idx < len(lines) and lines[idx].strip() != "---":
        fm_lines.append(lines[idx])
        idx += 1
    body = "\n".join(lines[idx + 1:]) if idx < len(lines) else ""
    return _parse_simple_yaml("\n".join(fm_lines)), body


def _parse_simple_yaml(text: str) -> dict:
    """Parse minimal YAML: key: value and block-style lists."""
    result: dict = {}
    current_key: str | None = None
    current_list: list | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.strip().startswith("#"):
            continue
        stripped = line.strip()

        if not line.startswith(" "):
            if ":" in stripped:
                key, _, val = stripped.partition(":")
                key = key.strip()
                val = val.strip()
                if val:
                    if val.startswith("[") and val.endswith("]"):
                        items = [item.strip().strip("\"'") for item in val[1:-1].split(",") if item.strip()]
                        result[key] = items
                    else:
                        result[key] = _unquote(val)
                    current_key = None
                    current_list = None
                else:
                    current_key = key
                    result[key] = []
                    current_list = result[key]
            else:
                current_key = None
                current_list = None
        else:
            if current_key is not None and current_list is not None and stripped.startswith("- "):
                item = _unquote(stripped[2:].strip())
                current_list.append(item)
    return result


def _unquote(val: str) -> str:
    """Strip surrounding quotes from a value."""
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
        return val[1:-1]
    return val


def _as_list(value) -> list[str]:
    """Coerce a value into a list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]
