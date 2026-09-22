"""Curation gate service for the Janus knowledge pipeline.

Implements Step 3 of the Research Knowledge Pipeline: the human curation
gate.  A :class:`~janus.models.curation_proposal.CurationProposal` is created
from a :class:`~janus.models.knowledge_summary.KnowledgeSummary` plus its
validation warnings; it starts in ``pending_approval`` and must be explicitly
approved before :func:`promote_to_vault` will write to the Obsidian vault.

State transitions (6 total):
    1. pending_approval ──approve──► approved
    2. pending_approval ──reject──► rejected  (terminal)
    3. pending_approval ──defer──► deferred  (terminal)
    4. approved ──reject──► rejected  (terminal)
    5. approved ──defer──► deferred  (terminal)
    6. approved ──promote──► vaulted  (terminal, programmatic)

Re-approving an already-approved proposal is a no-op.  Transitioning a
terminal state raises ``ValueError``.
"""

from datetime import datetime
from pathlib import Path

from janus._log import emit
from janus.integrations.markdown_curation import (
    load_proposals,
    save_proposal,
    update_proposal,
    next_proposal_id,
)
from janus.models.curation_proposal import (
    CurationProposal,
    APPROVAL_STATES,
    TERMINAL_STATES,
)
from janus.models.knowledge_summary import KnowledgeSummary
from janus.services.curation_gate_error import CurationGateError

import logging

logger = logging.getLogger(__name__)

# Vault output directory (Obsidian).
PROJECT_ROOT = Path(__file__).resolve().parents[3]
VAULT_DIR = PROJECT_ROOT / "data" / "vault"


# ── Creation ──

def create_curation_proposal(
    summary: KnowledgeSummary,
    warnings: list[dict] | None = None,
) -> CurationProposal:
    """Create a CurationProposal in ``pending_approval`` state and persist it.

    This is the Step-2 -> Step-3 bridge: called after ``generate_summary``
    produces a KnowledgeSummary, before ``promote_to_vault`` writes to the
    Obsidian vault.

    Args:
        summary: The KnowledgeSummary IR to gate.
        warnings: ValidationWarning dicts from Step 1 (category, message,
            finding_index).

    Returns:
        The persisted CurationProposal (approval_state='pending_approval').
    """
    if not isinstance(summary, KnowledgeSummary):
        raise ValueError(
            f"summary must be a KnowledgeSummary, got {type(summary).__name__}"
        )
    proposal = CurationProposal(
        proposal_id=next_proposal_id(),
        summary=summary,
        warnings=list(warnings) if warnings else [],
        approval_state="pending_approval",
    )
    save_proposal(proposal)
    emit(logger, "service.curation_gate",
         trace_id=None, span_id="create_curation_proposal",
         proposal_id=proposal.proposal_id, approval_state="pending_approval",
         warning_count=len(proposal.warnings),
         message=f"Created curation proposal {proposal.proposal_id} (pending approval)")
    return proposal


# ── Approval / rejection / deferral ──

def approve_proposal(proposal_id: str, approver: str = "", note: str = "") -> CurationProposal:
    """Transition a proposal to ``approved``.

    Raises ValueError if the proposal is not found or is in a terminal state
    (rejected / deferred / vaulted) that cannot be re-approved.
    Re-approving an already-approved proposal is a no-op.
    """
    proposal = _get_proposal_or_raise(proposal_id)

    if proposal.approval_state == "approved":
        return proposal
    if proposal.approval_state in TERMINAL_STATES:
        raise ValueError(
            f"Cannot approve proposal {proposal_id!r}: it is in terminal "
            f"state {proposal.approval_state!r}"
        )

    proposal.approval_state = "approved"
    proposal.approver = (approver or "").strip()
    proposal.decision_note = (note or "").strip()
    proposal.updated_at = datetime.now().astimezone()
    update_proposal(proposal)

    emit(logger, "service.curation_gate",
         trace_id=None, span_id="approve_proposal",
         proposal_id=proposal_id, approval_state="approved",
         approver=approver,
         message=f"Proposal {proposal_id} approved by {approver or 'system'}")
    return proposal


def reject_proposal(proposal_id: str, approver: str = "", note: str = "") -> CurationProposal:
    """Transition a proposal to ``rejected`` (terminal)."""
    proposal = _get_proposal_or_raise(proposal_id)
    _check_not_terminal(proposal)

    proposal.approval_state = "rejected"
    proposal.approver = (approver or "").strip()
    proposal.decision_note = (note or "").strip()
    proposal.updated_at = datetime.now().astimezone()
    update_proposal(proposal)

    emit(logger, "service.curation_gate",
         trace_id=None, span_id="reject_proposal",
         proposal_id=proposal_id, approval_state="rejected",
         approver=approver,
         message=f"Proposal {proposal_id} rejected by {approver or 'system'}")
    return proposal


def defer_proposal(proposal_id: str, approver: str = "", note: str = "") -> CurationProposal:
    """Transition a proposal to ``deferred`` (terminal).

    The proposal remains linked to its summary but will not promote; a
    deferred proposal can be re-created later if the research is refreshed.
    """
    proposal = _get_proposal_or_raise(proposal_id)
    _check_not_terminal(proposal)

    proposal.approval_state = "deferred"
    proposal.approver = (approver or "").strip()
    proposal.decision_note = (note or "").strip()
    proposal.updated_at = datetime.now().astimezone()
    update_proposal(proposal)

    emit(logger, "service.curation_gate",
         trace_id=None, span_id="defer_proposal",
         proposal_id=proposal_id, approval_state="deferred",
         approver=approver,
         message=f"Proposal {proposal_id} deferred by {approver or 'system'}")
    return proposal


# ── Vault promotion (the blocking gate) ──

def promote_to_vault(proposal_id: str) -> Path:
    """Write an approved proposal's KnowledgeSummary to the Obsidian vault.

    **This is the enforcement point of the human curation gate.**  It raises
    :class:`CurationGateError` when ``approval_state != 'approved'``, blocking
    any promotion that has not received explicit human approval.

    Args:
        proposal_id: The curation proposal to promote.

    Returns:
        The path to the written vault file.

    Raises:
        CurationGateError: if the proposal is not in ``approved`` state.
        ValueError: if the proposal is not found.
    """
    proposal = _get_proposal_or_raise(proposal_id)

    if proposal.approval_state != "approved":
        raise CurationGateError(proposal_id, proposal.approval_state)

    vault_content = _render_vault_markdown(proposal)
    slug = _slugify(proposal.summary.title)
    vault_path = VAULT_DIR / f"{slug}.md"
    vault_path.parent.mkdir(parents=True, exist_ok=True)

    existing_hash = None
    if vault_path.exists():
        from janus.integrations.atomic_io import compute_content_hash
        existing_hash = compute_content_hash(vault_path.read_text(encoding="utf-8"))

    from janus.integrations.atomic_io import atomic_write
    atomic_write(
        vault_path,
        vault_content,
        expected_hash=existing_hash,
        written_by="curation_gate.promote_to_vault",
    )

    proposal.approval_state = "vaulted"
    proposal.vault_path = str(vault_path)
    proposal.updated_at = datetime.now().astimezone()
    update_proposal(proposal)

    emit(logger, "service.curation_gate",
         trace_id=None, span_id="promote_to_vault",
         proposal_id=proposal_id, vault_path=str(vault_path),
         message=f"Promoted proposal {proposal_id} to vault: {vault_path.name}")
    return vault_path


# ── Read helpers ──

def get_proposal(proposal_id: str) -> CurationProposal:
    """Load a single proposal by id.  Raises ValueError if not found."""
    return _get_proposal_or_raise(proposal_id)


def list_proposals(state: str | None = None) -> list[CurationProposal]:
    """Load all proposals; optional filter by approval_state."""
    items = load_proposals()
    if state is None:
        return items
    if state not in APPROVAL_STATES:
        raise ValueError(f"Invalid state filter: {state!r}. Allowed: {', '.join(APPROVAL_STATES)}")
    return [p for p in items if p.approval_state == state]


# ── Internals ──

def _get_proposal_or_raise(proposal_id: str) -> CurationProposal:
    for proposal in load_proposals():
        if proposal.proposal_id == proposal_id:
            return proposal
    raise ValueError(f"Curation proposal not found: {proposal_id}")


def _check_not_terminal(proposal: CurationProposal) -> None:
    """Raise ValueError if the proposal is in a terminal state."""
    if proposal.approval_state in TERMINAL_STATES:
        raise ValueError(
            f"Cannot transition proposal {proposal.proposal_id!r}: it is in "
            f"terminal state {proposal.approval_state!r}"
        )


def _render_vault_markdown(proposal: CurationProposal) -> str:
    """Render a KnowledgeSummary to Obsidian-ready Markdown."""
    summary = proposal.summary
    lines: list[str] = []

    lines.append("---")
    lines.append(f"title: {summary.title}")
    lines.append(f"target: {summary.target}")
    lines.append(f"artifact_version: {summary.artifact_version}")
    lines.append(f"curation_proposal_id: {proposal.proposal_id}")
    lines.append(f"curation_state: {proposal.approval_state}")
    if proposal.approver:
        lines.append(f"approved_by: {proposal.approver}")
    if summary.generated_at:
        lines.append(f"generated_at: {summary.generated_at.isoformat()}")
    lines.append("---")
    lines.append("")

    lines.append(summary.summary_text)
    lines.append("")

    lines.append("## Conclusions")
    lines.append("")
    lines.append(summary.conclusions)
    lines.append("")

    lines.append("## Topic Blocks")
    lines.append("")
    for tb in summary.ordered_topic_blocks():
        lines.append(f"### {tb.topic} ({tb.composite_confidence})")
        lines.append("")
        lines.append(tb.narrative)
        lines.append("")
        for finding in tb.findings:
            icon = {"wyzszy": "+", "sredni": "o", "niski": "!"}.get(finding.confidence, "?")
            lines.append(f"- [{icon}] {finding.statement}")
            for src in finding.sources:
                src_line = f"  - [{src.title or 'source'}]({src.url})" if src.title else f"  - {src.url}"
                lines.append(src_line)
        lines.append("")

    if summary.entities:
        lines.append("## Entities")
        lines.append("")
        for ent in summary.entities:
            lines.append(f"- [[{ent}]]")
        lines.append("")

    if summary.knowledge_gaps:
        lines.append("## Knowledge Gaps")
        lines.append("")
        for gap in summary.knowledge_gaps:
            lines.append(f"- {gap}")
        lines.append("")

    lines.append("## Metadata")
    lines.append("")
    lines.append(f"- Sources: {summary.source_count}")
    lines.append(f"- High confidence: {summary.high_confidence_count}")
    lines.append(f"- Low confidence: {summary.low_confidence_count}")
    lines.append(f"- Curation proposal: `{proposal.proposal_id}`")
    lines.append("")

    return "\n".join(lines)


def _slugify(text: str) -> str:
    """Convert text to a slug suitable for a vault filename."""
    import re
    slug = text.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-") or "untitled"
