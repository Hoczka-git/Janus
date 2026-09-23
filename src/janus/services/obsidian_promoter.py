"""Obsidian promotion pipeline — Phase 3–5 of the Research Knowledge Pipeline.

Steps 3–5 (per docs/specs/research_knowledge_pipeline_specification.md):

    Step 3 — propose_note_content(summary) → Obsidian-ready Markdown
    Step 4 — curate_proposal(...) → dispatch approve/reject/cancel
    Step 5 — promote_to_obsidian(...) → write to vault + audit record

See: docs/guides/knowledge_summary_obsidian_pipeline_design.md
     docs/specs/research_knowledge_pipeline_specification.md
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from janus.models.curation_proposal import (
    CurationGateError,
    CurationGateState,
    CurationProposal,
    StaleStateError,
    _slugify,
)
from janus.models.knowledge_summary import KnowledgeSummary

# ── Step 3: note rendering ───────────────────────────────────────────────────

CONFIDENCE_ICONS: dict[str, str] = {"wyzszy": "+", "sredni": "o", "niski": "!"}


def propose_note_content(summary: KnowledgeSummary) -> str:
    """Render a :class:`KnowledgeSummary` to Obsidian-ready Markdown.

    Produces a document with YAML frontmatter, a level-1 title, conclusions,
    topic blocks with confidence-tagged findings, source links, entity
    wikilinks, knowledge gaps, and a metadata footer.
    """
    lines: list[str] = []

    # ── frontmatter ──
    lines.append("---")
    lines.append(f"title: {summary.title}")
    lines.append(f"target: {summary.target}")
    lines.append(f"artifact_version: {summary.artifact_version}")
    gen = summary.generated_at or datetime.now(timezone.utc)
    lines.append(f"created: {gen.isoformat()}")
    lines.append(f"confidence: {summary.high_confidence_count}/{summary.source_count}")
    lines.append("---")
    lines.append("")

    # ── title ──
    lines.append(f"# {summary.title}")
    lines.append("")

    # ── summary ──
    lines.append(summary.summary_text)
    lines.append("")

    # ── conclusions ──
    lines.append("## Conclusions:")
    lines.append("")
    if summary.conclusions:
        lines.append(summary.conclusions)
    else:
        lines.append("(no conclusions recorded)")
    lines.append("")

    # ── topic blocks ──
    lines.append("## Topic Blocks")
    lines.append("")
    for tb in summary.ordered_topic_blocks():
        lines.append(f"### {tb.topic} ({tb.composite_confidence})")
        lines.append("")
        lines.append(tb.narrative)
        lines.append("")
        for finding in tb.findings:
            icon = CONFIDENCE_ICONS.get(finding.confidence, "?")
            lines.append(f"- [{icon}] {finding.statement}")
            for src in finding.sources:
                if src.title:
                    lines.append(f"  - [{src.title}]({src.url})")
                else:
                    lines.append(f"  - {src.url}")
            lines.append("")
        lines.append("")

    # ── entities ──
    if summary.entities:
        lines.append("## Entities")
        lines.append("")
        for ent in summary.entities:
            lines.append(f"- [[{ent}]]")
        lines.append("")

    # ── knowledge gaps ──
    if summary.knowledge_gaps:
        lines.append("## Knowledge gaps")
        lines.append("")
        for gap in summary.knowledge_gaps:
            lines.append(f"- {gap}")
        lines.append("")
    else:
        lines.append("## Knowledge gaps")
        lines.append("")
        lines.append("No knowledge gaps identified.")
        lines.append("")

    # ── metadata footer ──
    lines.append("## Metadata")
    lines.append("")
    lines.append(f"- Sources: {summary.source_count}")
    lines.append(f"- High confidence: {summary.high_confidence_count}")
    lines.append(f"- Low confidence: {summary.low_confidence_count}")
    lines.append("")

    return "\n".join(lines)


# ── Step 4: curation dispatcher ──────────────────────────────────────────────

def curate_proposal(proposal: CurationProposal, action: str) -> CurationProposal:
    """Dispatch a curation action on *proposal*, returning a new instance.

    Actions: ``"approve"``, ``"reject"``, ``"cancel"``.
    """
    if action == "approve":
        return proposal.approve()
    elif action == "reject":
        return proposal.reject()
    elif action == "cancel":
        return proposal.cancel()
    else:
        raise CurationGateError(f"Unknown curation action: {action!r}")


def expire_stale_proposals(
    proposals: list[CurationProposal],
    now: datetime | None = None,
) -> list[CurationProposal]:
    """Return all proposals, with PENDING-past-TTL ones marked EXPIRED.

    Non-PENDING and within-TTL proposals pass through unchanged in the same
    order.  (Immutable: input list and its elements are not mutated.)
    """
    now = now or datetime.now(timezone.utc)
    out: list[CurationProposal] = []
    for p in proposals:
        if p.state == CurationGateState.PENDING and p.expires_at is not None:
            if p.expires_at < now:
                try:
                    out.append(p.expire())
                    continue
                except StaleStateError:
                    pass
        out.append(p)
    return out


# ── Step 5: vault promotion ──────────────────────────────────────────────────

def _resolve_vault(
    vault_path: Path | None,
    raise_on_missing: bool = False,
) -> Path | None:
    """Resolve the Obsidian vault directory.

    If *vault_path* is given and exists, return it.  Otherwise consult
    ``JANUS_OBSIDIAN_VAULT``.  Returns ``None`` when no valid vault is
    configured or the configured path does not exist.

    When *raise_on_missing* is ``True``, raises :exc:`CurationGateError`
    instead of returning ``None``.
    """
    if vault_path is not None:
        if vault_path.exists():
            return vault_path
        if raise_on_missing:
            raise CurationGateError("Obsidian vault path is not configured")
        return None
    env = os.environ.get("JANUS_OBSIDIAN_VAULT")
    if env:
        p = Path(env)
        if p.exists():
            return p
        if raise_on_missing:
            raise CurationGateError("Obsidian vault path is not configured")
        return None
    if raise_on_missing:
        raise CurationGateError("Obsidian vault path is not configured")
    return None


def _is_vault_unconfigured() -> bool:
    """Return ``True`` when no valid vault directory is configured."""
    env = os.environ.get("JANUS_OBSIDIAN_VAULT")
    if not env:
        return True
    return not Path(env).exists()


KNOWLEDGE_SUBDIR = "Knowledge"


def promote_to_obsidian(
    proposal: CurationProposal,
    vault_path: Path | None = None,
) -> dict[str, Any]:
    """Promote an approved proposal to the Obsidian vault.

    Writes the proposal's ``note_content`` to
    ``<vault>/Knowledge/<slug>.md``.  Returns a report dict.

    Raises :exc:`CurationGateError` when the proposal is not in
    ``APPROVED`` state or the vault is not configured.
    """
    if proposal.state != CurationGateState.APPROVED:
        raise CurationGateError(
            f"Proposal {proposal.slug!r} state must be APPROVED "
            f"(currently {proposal.state.label})"
        )

    vault = _resolve_vault(vault_path, raise_on_missing=True)

    knowledge_dir = vault / KNOWLEDGE_SUBDIR
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    dest = knowledge_dir / f"{proposal.slug}.md"
    dest.write_text(proposal.note_content, encoding="utf-8")
    now = datetime.now(timezone.utc)

    return {
        "slug": proposal.slug,
        "promoted": True,
        "adapter": False,
        "path": str(dest),
        "action": "promote_to_obsidian",
        "promoted_at": now.isoformat(),
    }


# ── Persistence: promotion records ───────────────────────────────────────────

DEFAULT_RECORD_DIR = Path("promotion_records")


def persist_promotion_record(
    proposal: CurationProposal,
    report: dict[str, Any],
    record_dir: Path | None = None,
) -> Path:
    """Write a promotion audit record as JSON.

    The record contains the proposal's identifying fields plus the report
    payload and a content hash for audit purposes.
    """
    base = record_dir or DEFAULT_RECORD_DIR
    base.mkdir(parents=True, exist_ok=True)

    rec = base / f"{proposal.slug}.json"
    data: dict[str, Any] = {
        "slug": proposal.slug,
        "artifact_title": proposal.artifact_title,
        "target": proposal.target,
        "state": proposal.state.label,
        "content_hash": proposal.content_hash,
        "promoted": report.get("promoted", False),
        "path": report.get("path"),
        "promoted_at": report.get("promoted_at"),
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
        "expires_at": proposal.expires_at.isoformat() if proposal.expires_at else None,
    }
    rec.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return rec


def load_record(path: Path) -> dict[str, Any] | None:
    """Read a promotion record JSON back into a dict.

    Returns ``None`` when the file does not exist.
    """
    if not path.exists():
        return None
    return json.loads(path.read_text())
