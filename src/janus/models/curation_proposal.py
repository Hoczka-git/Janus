"""Curation proposal model for the Janus knowledge pipeline.

A :class:`CurationProposal` is the gating entity between summary generation
(Step 2 of the Research Knowledge Pipeline) and Obsidian vault promotion
(Step 4).  It carries a :class:`~janus.models.knowledge_summary.KnowledgeSummary`
together with its validation warnings and an approval state that must be
transitioned to ``APPROVED`` before the summary can be written to the vault.

States & transitions:

    PENDING ──approve──► APPROVED ──promote──► VAULTED
         │                       │
         │ reject                │ reject
         ▼                       ▼
     REJECTED                  REJECTED

    promote is the only transition out of APPROVED and leads to V AULTED
    (a terminal marker set by :func:`~janus.services.obsidian_promoter.promote_to_obsidian`).
"""

from __future__ import annotations

import hashlib
from copy import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from janus.models.knowledge_summary import KnowledgeSummary

# ── Approval state enum ──────────────────────────────────────────────────────

class CurationGateState(Enum):
    """Human-curated approval state for a knowledge proposal.

    PENDING  — awaiting human decision (initial state)
    APPROVED — human approved; may be promoted to Obsidian
    REJECTED — human rejected; terminal
    CANCELLED — human cancelled; terminal
    EXPIRED  — TTL elapsed without decision; terminal
    VAULTED  — approved and written to the Obsidian vault; terminal
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    VAULTED = "vaulted"

    @property
    def is_terminal(self) -> bool:
        return self in (
            CurationGateState.REJECTED,
            CurationGateState.CANCELLED,
            CurationGateState.EXPIRED,
            CurationGateState.VAULTED,
        )

    @property
    def label(self) -> str:
        return self.value

# ── Exceptions ───────────────────────────────────────────────────────────────

class CurationGateError(RuntimeError):
    """Raised when a curation operation is rejected by the gate."""

    def __init__(self, message: str) -> None:
        super().__init__(message)

class StaleStateError(CurationGateError):
    """Raised when attempting a transition from a terminal state."""

    def __init__(self, state: CurationGateState, action: str) -> None:
        super().__init__(
            f"Cannot {action} proposal in state {state.label} "
            f"(already {state.label})"
        )

# ── Approval states for the metadata-driven gate (existing API) ──────────────

APPROVAL_STATES = ("pending_approval", "approved", "rejected", "deferred", "vaulted")

# Terminal states — no further transitions allowed from these.
TERMINAL_STATES = ("rejected", "deferred", "vaulted")


@dataclass
class CurationProposal:
    """A KnowledgeSummary awaiting human curation before vault promotion.

    This class coordinates the human-in-the-loop curation gate between
    summary generation (Step 2) and Obsidian vault promotion (Step 4).

    Attributes:
        slug: Short identifier for the proposal (also used as filename stem).
        artifact_title: Title of the source research artifact.
        target: Research target (e.g. "GLUE", "research").
        note_content: Rendered Obsidian note body (produced by propose_note_content).
        finding_indices: Indices of findings included in this proposal.
        source_path: Optional path to the source artifact file.
        decision_adr: ADR governing this curation decision.
        created_at: When the proposal was created.
        updated_at: When the proposal last changed state.
        expires_at: TTL deadline for pending proposals.
        state: Current CurationGateState (enum).
        summary: The KnowledgeSummary IR that produced this proposal (optional).
        warnings: ValidationWarning dicts carried from Step 1 validation.
        vault_path: Set when promoted to the vault (for audit).
        approver: Who approved/rejected/cancelled/expires it.
        decision_note: Free-text rationale for the human decision.
    """

    slug: str = ""
    artifact_title: str = ""
    target: str = ""
    note_content: str = ""
    finding_indices: tuple[int, ...] = field(default_factory=tuple)
    source_path: str | None = None
    decision_adr: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    expires_at: datetime | None = None
    state: CurationGateState = CurationGateState.PENDING
    summary: KnowledgeSummary | None = None
    warnings: list[dict] = field(default_factory=list)
    vault_path: str = ""
    approver: str = ""
    decision_note: str = ""

    def __post_init__(self) -> None:
        if not self.slug or not self.slug.strip():
            raise ValueError("CurationProposal.slug must not be empty")
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        if self.updated_at is None:
            self.updated_at = self.created_at

    # ── Content hash ─────────────────────────────────────────────────────────

    @property
    def content_hash(self) -> str:
        """SHA-256 fingerprint of the proposal's content fields.

        Used by :func:`persist_promotion_record` for audit integrity.
        """
        payload = f"{self.artifact_title}|{self.finding_indices}|{self.note_content}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # ── Immutable state transitions ──────────────────────────────────────────

    def _replace(self, **kwargs: Any) -> CurationProposal:
        """Return a new instance with selected fields overridden (immutable)."""
        new = copy(self)
        for k, v in kwargs.items():
            setattr(new, k, v)
        return new

    def approve(self) -> CurationProposal:
        """Transition ``PENDING`` → ``APPROVED``, returning a new instance."""
        if self.state != CurationGateState.PENDING:
            raise StaleStateError(self.state, "approve")
        return self._replace(
            state=CurationGateState.APPROVED,
            updated_at=datetime.now(timezone.utc),
        )

    def reject(self, reason: str = "") -> CurationProposal:
        """Transition ``PENDING`` → ``REJECTED``, returning a new instance."""
        if self.state != CurationGateState.PENDING:
            raise StaleStateError(self.state, "reject")
        return self._replace(
            state=CurationGateState.REJECTED,
            updated_at=datetime.now(timezone.utc),
            decision_note=reason,
        )

    def cancel(self) -> CurationProposal:
        """Transition ``PENDING`` → ``CANCELLED``, returning a new instance."""
        if self.state != CurationGateState.PENDING:
            raise StaleStateError(self.state, "cancel")
        return self._replace(
            state=CurationGateState.CANCELLED,
            updated_at=datetime.now(timezone.utc),
        )

    def expire(self) -> CurationProposal:
        """Transition ``PENDING`` → ``EXPIRED``, returning a new instance."""
        if self.state != CurationGateState.PENDING:
            raise StaleStateError(self.state, "expire")
        return self._replace(
            state=CurationGateState.EXPIRED,
            updated_at=datetime.now(timezone.utc),
        )

    # ── Conflict + terminal checks ────────────────────────────────────────────

    def is_conflicting_with(self, other: CurationProposal) -> bool:
        """Return ``True`` when *other* is a different PENDING proposal with the same slug."""
        if self.slug != other.slug:
            return False
        if self.state != CurationGateState.PENDING:
            return False
        if other.state != CurationGateState.PENDING:
            return False
        # Same slug, both pending — but not the same object.
        return self is not other

    @property
    def is_terminal(self) -> bool:
        """Return ``True`` for terminal states (REJECTED, CANCELLED, EXPIRED, VAULTED)."""
        return self.state.is_terminal

    # ── Factory from KnowledgeSummary ─────────────────────────────────────────

    @classmethod
    def from_summary(
        cls,
        summary: KnowledgeSummary,
        finding_indices: tuple[int, ...] = (),
        source_path: str | None = None,
        ttl_seconds: int = 3600,
    ) -> CurationProposal:
        """Build a ``CurationProposal`` from a :class:`KnowledgeSummary`.

        Renders the summary via :func:`propose_note_content`, slugifies the
        title for the ``slug`` field, and sets a TTL-based ``expires_at``.
        """
        # Lazy import to break the cycle: obsidian_promoter imports this model.
        from janus.services.obsidian_promoter import propose_note_content  # noqa: PLC0415

        note = propose_note_content(summary)
        slug = _slugify(summary.title)

        if not finding_indices:
            # Default: one index per topic block (block-level selection).
            finding_indices = tuple(range(len(summary.ordered_topic_blocks())))

        now = datetime.now(timezone.utc)
        return cls(
            slug=slug,
            artifact_title=summary.title,
            target=summary.target,
            note_content=note,
            finding_indices=finding_indices,
            source_path=source_path,
            decision_adr="ADR-002",
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            state=CurationGateState.PENDING,
            summary=summary,
        )


def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    import re
    slug = text.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-") or "untitled"
