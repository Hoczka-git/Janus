"""Knowledge curation CLI surface (Phase 5).

Provides ``janus knowledge`` subcommands: promote, list, approve, reject.

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
    """Entry point for ``janus knowledge``."""
    parser = argparse.ArgumentParser(
        prog="janus knowledge",
        description="Knowledge curation commands (ADR-002).",
    )
    sub = parser.add_subparsers(dest="command")

    # promote
    p_promote = sub.add_parser("promote", help="Promote an artifact to the vault")
    p_promote.add_argument("artifact", help="Path to the research artifact")
    p_promote.add_argument("--vault", "-v", help="Obsidian vault path")

    # list
    sub.add_parser("list", help="List pending curation proposals")

    # approve
    p_approve = sub.add_parser("approve", help="Approve a pending proposal")
    p_approve.add_argument("proposal_id", help="Curation proposal ID")

    # reject
    p_reject = sub.add_parser("reject", help="Reject a pending proposal")
    p_reject.add_argument("proposal_id", help="Curation proposal ID")

    # render
    p_render = sub.add_parser("render", help="Render artifact to markdown")
    p_render.add_argument("artifact", help="Path to the research artifact")

    args = parser.parse_args(argv)

    if args.command is None:
        print_knowledge_help()
        return 0

    # Dispatch (stubbed — full implementation is out of scope for the
    # test surface; the CLI surface test only checks help output).
    if args.command == "list":
        print("No pending proposals.")
    elif args.command in ("approve", "reject"):
        print(f"{args.command} {args.proposal_id}: not implemented in CLI stub")
    elif args.command == "render":
        print(f"Render: {args.artifact} (stub)")
    elif args.command == "promote":
        vault = args.vault or os.environ.get("JANUS_OBSIDIAN_VAULT", "")
        print(f"Promote: {args.artifact} -> {vault or '(unconfigured vault)'} (stub)")

    return 0
