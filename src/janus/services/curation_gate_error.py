"""Exception raised when vault promotion is blocked by the curation gate."""


class CurationGateError(RuntimeError):
    """Raised by :func:`~janus.services.curation_gate.promote_to_vault` when
    the proposal's :attr:`~janus.models.curation_proposal.CurationProposal.approval_state`
    is not ``approved``.

    Carries the blocking state so callers can surface a precise message.
    """

    def __init__(self, proposal_id: str, approval_state: str) -> None:
        self.proposal_id = proposal_id
        self.approval_state = approval_state
        super().__init__(
            f"Promotion blocked: proposal {proposal_id!r} is "
            f"{approval_state!r} (must be 'approved'). "
            f"Use 'janus research approve {proposal_id}' first."
        )
