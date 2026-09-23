"""Knowledge curation CLI surface (Phase 5).

Provides ``janus knowledge`` subcommands: promote, list, approve, reject, render.
Also exposes ``print_knowledge_help`` for the test surface.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def print_knowledge_help() -> None:
    """Print usage information for the ``janus knowledge`` CLI."""
    print("""\
usage: janus knowledge <command> [options]

Knowledge curation commands (ADR-002):

  janus knowledge promote <artifact> [--vault PATH]
      Promote a research artifact to the Obsidian knowledge vault.

  janus knowledge list
      List pending curation proposals.

  janus knowledge approve <proposal-id>
      Approve a pending proposal for promotion.

  janus knowledge reject <proposal-id>
      Reject a pending proposal.

  janus knowledge render <artifact>
      Render an artifact to Obsidian markdown (no promotion).

Options:
  --vault PATH     Path to the Obsidian vault directory.
                   Alternatively set JANUS_OBSIDIAN_VAULT.

Artifacts are the source of knowledge summaries.  Each artifact goes
through validation, summary generation, curation, and promotion.
""")


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``janus knowledge``.

    In ``promote`` mode the pipeline runs: validate → generate summary →
    build curation proposal → (auto-approve with --yes flag) → promote
    to vault.  Without ``--yes`` the proposal state is shown and the user
    is told to use ``janus knowledge approve`` / ``reject``.
    """
    parser = argparse.ArgumentParser(
        prog="janus knowledge",
        description="Knowledge curation commands (ADR-002).",
    )
    sub = parser.add_subparsers(dest="command")

    # promote
    p_promote = sub.add_parser("promote", help="Promote an artifact to the vault")
    p_promote.add_argument("artifact", help="Path to the research artifact")
    p_promote.add_argument("--vault", "-v", default=None,
                           help="Obsidian vault path")
    p_promote.add_argument("--yes", "-y", action="store_true", default=False,
                           help="Auto-approve and promote (non-interactive)")

    # list
    sub.add_parser("list", help="List pending curation proposals")

    # approve
    p_approve = sub.add_parser("approve", help="Approve a pending proposal")
    p_approve.add_argument("proposal_id", help="Curation proposal ID")

    # reject
    p_reject = sub.add_parser("reject", help="Reject a pending proposal")
    p_reject.add_argument("proposal_id", help="Curation proposal ID")
    p_reject.add_argument("--reason", "-r", default="",
                          help="Reason for rejection")

    # render
    p_render = sub.add_parser("render", help="Render artifact to markdown")
    p_render.add_argument("artifact", help="Path to the research artifact")

    args = parser.parse_args(argv)

    if args.command is None:
        print_knowledge_help()
        return 0

    if args.command == "list":
        print("No pending proposals.")
        return 0

    if args.command in ("approve", "reject"):
        print(f"{args.command} {args.proposal_id}: not implemented in CLI", file=sys.stderr)
        return 1

    if args.command == "render":
        _render_artifact(args.artifact)
        return 0

    if args.command == "promote":
        vault_str = args.vault or os.environ.get("JANUS_OBSIDIAN_VAULT", "")
        vault = Path(vault_str) if vault_str else None
        _promote_artifact(args.artifact, vault=vault,
                          auto_approve=args.yes)
        return 0

    return 0


# Alias for integration into the top-level janus dispatcher.
knowledge_main = main


# ── Internal helpers ─────────────────────────────────────────────────────────

def _render_artifact(artifact_path: str) -> None:
    """Render a research artifact to Obsidian markdown and print it.

    Loads the artifact from the research pipeline, generates a summary,
    and renders the Obsidian-ready note content.
    """
    from janus.services.knowledge_pipeline import generate_summary, validate_artifact
    from janus.services.obsidian_promoter import propose_note_content
    from pathlib import Path as _Path

    path = _Path(artifact_path)
    if not path.exists():
        print(f"Error: artifact not found: {artifact_path}", file=sys.stderr)
        sys.exit(1)

    from janus.integrations.markdown_research import _parse_artifact_content
    body = path.read_text(encoding="utf-8")
    artifact = _parse_artifact_content(body)

    warnings = validate_artifact(artifact)
    summary = generate_summary(artifact, warnings=warnings)
    note = propose_note_content(summary)
    print(note)

    if warnings:
        print(f"\n-- {len(warnings)} validation warning(s) --")
        for w in warnings:
            print(f"  [{w.category}] {w.message}")


def _promote_artifact(
    artifact_path: str,
    *,
    vault: Path | None = None,
    auto_approve: bool = False,
) -> None:
    """Promote a research artifact to the Obsidian vault through the curation gate.

    When *auto_approve* is True, the proposal is automatically approved and
    promoted.  Otherwise the proposal is shown as pending review.
    """
    from janus.services.knowledge_pipeline import generate_summary, validate_artifact
    from janus.models.curation_proposal import CurationProposal
    from janus.services.obsidian_promoter import curate_proposal, promote_to_obsidian
    from pathlib import Path as _Path

    path = _Path(artifact_path)
    if not path.exists():
        print(f"Error: artifact not found: {artifact_path}", file=sys.stderr)
        sys.exit(1)

    from janus.integrations.markdown_research import _parse_artifact_content
    body = path.read_text(encoding="utf-8")
    artifact = _parse_artifact_content(body)

    warnings = validate_artifact(artifact)
    summary = generate_summary(artifact, warnings=warnings)
    proposal = CurationProposal.from_summary(
        summary, source_path=str(path),
    )

    if auto_approve:
        approved = curate_proposal(proposal, "approve")
        report = promote_to_obsidian(approved, vault_path=vault)
        print(f"Promoted: {report['path']}")
    else:
        print(f"Proposal for '{artifact.title}' is pending approval.")
        print(f"  Slug: {proposal.slug}")
        print(f"  State: {proposal.state.label}")
        print(f"  Use --yes to auto-approve and promote to Obsidian.")
        if warnings:
            print(f"  Warnings: {len(warnings)}")
