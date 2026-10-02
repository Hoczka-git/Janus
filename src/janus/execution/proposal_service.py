"""Proposal service — persistence for action proposals.

This module provides the ProposalService which persists proposals
to disk and allows updating their status. The actual approval logic
(human interaction) is handled by the approval task (t_91c82a31).

Design reference: docs/design/action_proposal_engine_v1.md
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from janus.proposal.models import ActionProposal, ProposalStatus

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROPOSALS_PATH = PROJECT_ROOT / "data" / "proposals.jsonl"


class ProposalService:
    """Service for persisting and retrieving action proposals.

    This service provides:
    - Persistence: writes proposals to data/proposals.jsonl
    - Retrieval: loads proposals by ID or lists all
    - Status updates: allows updating proposal status (e.g., APPROVED)
    """

    def __init__(
        self,
        proposals_path: Path | None = None,
    ) -> None:
        """Initialize the proposal service.

        Args:
            proposals_path: Optional path to the proposals file.
                Defaults to data/proposals.jsonl.
        """
        self._proposals_path = proposals_path or PROPOSALS_PATH

    def save_proposal(self, proposal: ActionProposal) -> None:
        """Save a proposal to the proposals file.

        If a proposal with the same ID already exists, it is updated.
        Otherwise, it is appended.

        Args:
            proposal: The proposal to save.
        """
        self._proposals_path.parent.mkdir(parents=True, exist_ok=True)

        # Read existing proposals
        existing = self._load_all()

        # Update or append
        updated = False
        for i, p in enumerate(existing):
            if p.proposal_id == proposal.proposal_id:
                existing[i] = proposal
                updated = True
                break

        if not updated:
            existing.append(proposal)

        # Write all
        with self._proposals_path.open("w", encoding="utf-8") as f:
            for p in existing:
                f.write(json.dumps(p.to_dict(), ensure_ascii=False) + "\n")

        logger.info(
            "Proposal %s saved: %s %s",
            proposal.proposal_id,
            proposal.action_type.value,
            proposal.status.value,
        )

    def get_proposal(self, proposal_id: str) -> ActionProposal | None:
        """Retrieve a proposal by ID.

        Args:
            proposal_id: The proposal ID to look up.

        Returns:
            The ActionProposal if found, None otherwise.
        """
        for proposal in self._load_all():
            if proposal.proposal_id == proposal_id:
                return proposal
        return None

    def list_proposals(self) -> list[ActionProposal]:
        """List all proposals.

        Returns:
            A list of all ActionProposal records.
        """
        return self._load_all()

    def update_status(
        self,
        proposal_id: str,
        status: ProposalStatus,
    ) -> ActionProposal | None:
        """Update the status of a proposal.

        Args:
            proposal_id: The proposal ID to update.
            status: The new status.

        Returns:
            The updated ActionProposal if found, None otherwise.
        """
        proposal = self.get_proposal(proposal_id)
        if proposal is None:
            return None

        proposal.status = status
        self.save_proposal(proposal)
        return proposal

    def _load_all(self) -> list[ActionProposal]:
        """Load all proposals from the proposals file.

        Returns:
            A list of all ActionProposal records.
        """
        proposals: list[ActionProposal] = []

        if not self._proposals_path.exists():
            return proposals

        try:
            content = self._proposals_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    proposals.append(ActionProposal.from_dict(record))
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
        except OSError:
            pass

        return proposals
