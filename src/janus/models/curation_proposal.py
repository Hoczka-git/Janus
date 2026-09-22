"""Curation proposal model for the Janus knowledge pipeline.

A :class:`CurationProposal` is the gating entity between summary generation
(Step 2 of the Research Knowledge Pipeline) and Obsidian vault promotion
(Step 4).  It carries a :class:`~janus.models.knowledge_summary.KnowledgeSummary`
together with its validation warnings and an approval state that must be
transitioned to ``approved`` before the summary can be written to the vault.

States & transitions (see docs/design/knowledge_curation_gate_state_spec.md):

    pending_approval ──approve──► approved ──promote──► vaulted
           │                           │
           │ reject                    │ reject
           ▼                           ▼
       rejected                     rejected
           │                           │
           └──── defer ──► deferred ◄──┘

    promote is the only transition out of ``approved`` and leads to ``vaulted``
    (a terminal marker set by :func:`~janus.services.curation_gat.promote_to_vault`).
"""

from dataclasses import dataclass, field
from datetime import datetime

from janus.models.knowledge_summary import KnowledgeSummary

# Approval states — the four from the spec plus ``vaulted`` (a terminal
# state set programmatically by promote_to_vault).
APPROVAL_STATES = ("pending_approval", "approved", "rejected", "deferred", "vaulted")

# Terminal states — no further transitions allowed from these.
TERMINAL_STATES = ("rejected", "deferred", "vaulted")


@dataclass
class CurationProposal:
    """A KnowledgeSummary awaiting human curation before vault promotion.

    Attributes:
        proposal_id: Stable identity (``cp-<8-hex>``).
        summary:    The KnowledgeSummary IR to be gated.
        warnings:   ValidationWarning dicts carried from Step 1.
        approval_state: Current curation state (one of APPROVAL_STATES).
        created_at: When the proposal was created.
        updated_at: When the proposal last changed state.
        approver:   Who approved/rejected/deferred it.
        decision_note: Free-text rationale for the human decision.
        vault_path: Set when ``approved`` and promoted to the vault.
    """

    proposal_id: str
    summary: KnowledgeSummary
    warnings: list[dict] = field(default_factory=list)
    approval_state: str = "pending_approval"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    approver: str = ""
    decision_note: str = ""
    vault_path: str = ""

    def __post_init__(self) -> None:
        if not self.proposal_id or not self.proposal_id.strip():
            raise ValueError("CurationProposal.proposal_id must not be empty")
        if not isinstance(self.summary, KnowledgeSummary):
            raise ValueError(
                f"CurationProposal.summary must be a KnowledgeSummary, "
                f"got {type(self.summary).__name__}"
            )
        if self.approval_state not in APPROVAL_STATES:
            raise ValueError(
                f"Invalid approval_state: {self.approval_state!r}. "
                f"Allowed: {', '.join(APPROVAL_STATES)}"
            )
        if self.created_at is None:
            self.created_at = datetime.now().astimezone()
        if self.updated_at is None:
            self.updated_at = self.created_at
