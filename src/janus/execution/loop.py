"""Execution loop — orchestrates ActionProposal → Execution → Evidence → Verification.

This module wires together the three stages of the closed-loop execution
pipeline:

1. **Execution** (:class:`ExecutionService`) — executes an approved
   :class:`ActionProposal` and produces an :class:`ExecutionResult`.
2. **Evidence Collection** (:class:`EvidenceCollector`) — consumes the
   execution result and produces a structured :class:`Evidence` artifact.
3. **Outcome Verification** (:func:`verify_outcome`) — compares the evidence
   against an :class:`IntendedState` specification and produces an
   :class:`OutcomeVerification` result.

The loop handles verification failures gracefully: even when verification
returns UNVERIFIED or INCONCLUSIVE, the loop returns a complete
:class:`ExecutionLoopResult` with all intermediate artifacts so callers
can inspect and react to the outcome.

Usage::

    from janus.execution.loop import run_execution_loop
    from janus.services.outcome_verification import IntendedState

    result = run_execution_loop(
        proposal,
        intended_state=IntendedState(expected_tests_passed=True),
    )
    if result.success:
        print("Execution succeeded and outcome verified")
    else:
        print(f"Execution: {result.execution.status}")
        print(f"Verification: {result.verification.status}")
        print(f"Reasoning: {result.verification.reasoning}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from janus.execution.models import ExecutionResult
from janus.execution.service import ExecutionService
from janus.proposal.models import ActionProposal
from janus.services.evidence import Evidence
from janus.services.evidence_collection import EvidenceCollector
from janus.services.execution_feedback import (
    EvidencePackage,
    ExecutionResultMessage,
    JanusDomainMetadata,
)
from janus.services.outcome_verification import (
    IntendedState,
    OutcomeVerification,
    VerificationStatus,
    verify_outcome,
)

logger = logging.getLogger(__name__)


# ── Execution loop result ────────────────────────────────────────────────────


@dataclass
class ExecutionLoopResult:
    """Result of the full execution loop.

    This is the primary output of :func:`run_execution_loop`.  It captures
    all three stages of the pipeline so callers can inspect the complete
    execution lifecycle.

    Attributes:
        execution: The raw execution result from the executor.
        evidence: The structured evidence artifact collected from the
            execution result.
        verification: The outcome verification result comparing evidence
            against the intended state.
        success: ``True`` only when execution succeeded **and** the
            intended state was achieved (verification status is VERIFIED).
        intended_state: The intended-state specification that was used
            for verification (useful for auditing and debugging).
    """

    execution: ExecutionResult
    evidence: Evidence
    verification: OutcomeVerification
    success: bool = False
    intended_state: IntendedState = field(default_factory=IntendedState)

    @property
    def execution_succeeded(self) -> bool:
        """Whether the execution itself succeeded."""
        return self.execution.is_success

    @property
    def outcome_verified(self) -> bool:
        """Whether the intended state was achieved."""
        return self.verification.intended_state_achieved

    @property
    def verification_status(self) -> VerificationStatus:
        """The verification status (VERIFIED / UNVERIFIED / INCONCLUSIVE)."""
        return self.verification.status

    def to_dict(self) -> dict:
        """Serialize to a JSON-serializable dict."""
        return {
            "execution": self.execution.to_dict(),
            "evidence": self.evidence.to_dict(),
            "verification": self.verification.to_dict(),
            "success": self.success,
            "intended_state": {
                "expected_changed_files": self.intended_state.expected_changed_files,
                "expected_tests_passed": self.intended_state.expected_tests_passed,
                "expected_pr_url": self.intended_state.expected_pr_url,
                "expected_summary_contains": self.intended_state.expected_summary_contains,
                "expected_body_contains": self.intended_state.expected_body_contains,
                "expected_metric_updates": self.intended_state.expected_metric_updates,
                "require_all_changed_files": self.intended_state.require_all_changed_files,
            },
        }


# ── Bridge: ExecutionResult → ExecutionResultMessage ─────────────────────────


def _build_result_message(
    result: ExecutionResult,
    proposal: ActionProposal,
) -> ExecutionResultMessage:
    """Build an :class:`ExecutionResultMessage` from an :class:`ExecutionResult`.

    The executor produces an :class:`ExecutionResult` with ``result_details``
    that may contain evidence-like fields (changed_files, tests_passed, pr_url,
    body, metric_updates).  This function maps those into the
    :class:`ExecutionResultMessage` wire format expected by
    :class:`EvidenceCollector`.

    Fields not present in ``result_details`` are set to ``None`` / empty,
    which the evidence collector handles gracefully (producing an EMPTY or
    PARTIAL evidence artifact).
    """
    details = result.result_details

    # Determine the domain title from the proposal
    title = proposal.target_id or proposal.parameters.get("title", "unknown")

    metadata = JanusDomainMetadata(
        object="task",
        title=title,
        changed_files=details.get("changed_files"),
        tests_passed=details.get("tests_passed"),
        pr_url=details.get("pr_url"),
    )

    evidence = EvidencePackage(
        task_id=proposal.proposal_id,
        summary=result.error or f"Execution {result.status.value.lower()}",
        changed_files=details.get("changed_files") or [],
        tests_passed=details.get("tests_passed"),
        pr_url=details.get("pr_url"),
        body=details.get("body"),
        janus_body=details.get("janus_body"),
        metric_updates=details.get("metric_updates"),
    )

    return ExecutionResultMessage(metadata=metadata, evidence=evidence)


# ── Intended-state derivation ────────────────────────────────────────────────


def derive_intended_state(proposal: ActionProposal) -> IntendedState:
    """Derive an :class:`IntendedState` from an :class:`ActionProposal`.

    Extracts verification criteria from the proposal's ``metadata`` and
    ``parameters`` fields.  When the proposal carries no intended-state
    information, the returned :class:`IntendedState` has all fields set to
    ``None`` (which causes :func:`verify_outcome` to return INCONCLUSIVE).

    Supported metadata keys:
        - ``expected_changed_files``: list of file paths
        - ``expected_tests_passed``: bool
        - ``expected_pr_url``: str
        - ``expected_summary_contains``: list of substrings
        - ``expected_body_contains``: list of substrings
        - ``expected_metric_updates``: list of dicts
        - ``require_all_changed_files``: bool (default True)
    """
    meta = proposal.metadata

    return IntendedState(
        expected_changed_files=meta.get("expected_changed_files"),
        expected_tests_passed=meta.get("expected_tests_passed"),
        expected_pr_url=meta.get("expected_pr_url"),
        expected_summary_contains=meta.get("expected_summary_contains"),
        expected_body_contains=meta.get("expected_body_contains"),
        expected_metric_updates=meta.get("expected_metric_updates"),
        require_all_changed_files=meta.get("require_all_changed_files", True),
    )


# ── Main execution loop ──────────────────────────────────────────────────────


def run_execution_loop(
    proposal: ActionProposal,
    intended_state: IntendedState | None = None,
    *,
    execution_service: ExecutionService | None = None,
    evidence_collector: EvidenceCollector | None = None,
) -> ExecutionLoopResult:
    """Run the full execution loop: Execute → Collect Evidence → Verify Outcome.

    This is the primary entry point for the closed-loop execution pipeline.
    It orchestrates three stages:

    1. **Execute** the proposal via :class:`ExecutionService`.
    2. **Collect evidence** from the execution result via
       :class:`EvidenceCollector`.
    3. **Verify outcome** by comparing the evidence against the intended
       state via :func:`verify_outcome`.

    The loop is designed to be resilient: it never raises for verification
    failures.  Even when verification returns UNVERIFIED or INCONCLUSIVE,
    a complete :class:`ExecutionLoopResult` is returned with all
    intermediate artifacts.

    Args:
        proposal: The approved :class:`ActionProposal` to execute.
        intended_state: Optional intended-state specification for
            verification.  If ``None``, one is derived from the proposal's
            metadata via :func:`derive_intended_state`.
        execution_service: Optional :class:`ExecutionService` instance.
            If ``None``, a default instance is created.
        evidence_collector: Optional :class:`EvidenceCollector` instance.
            If ``None``, a default instance is created.

    Returns:
        An :class:`ExecutionLoopResult` containing the execution result,
        evidence artifact, and verification result.
    """
    # Use derived intended state if none provided
    if intended_state is None:
        intended_state = derive_intended_state(proposal)

    # Stage 1: Execute
    service = execution_service or ExecutionService()
    execution_result = service.execute(proposal)

    # Stage 2: Collect evidence
    # Build the wire-format message from the execution result
    result_message = _build_result_message(execution_result, proposal)
    collector = evidence_collector or EvidenceCollector()
    evidence = collector.collect_safe(result_message)

    # Stage 3: Verify outcome
    # Use the evidence package from the message (not the Evidence artifact)
    # because verify_outcome expects an EvidencePackage
    verification = verify_outcome(
        result_message.evidence,
        intended_state,
        execution_succeeded=execution_result.is_success,
    )

    # Determine overall success: execution succeeded AND intended state achieved
    success = execution_result.is_success and verification.intended_state_achieved

    logger.info(
        "Execution loop completed for %s: execution=%s, verification=%s, success=%s",
        proposal.proposal_id,
        execution_result.status.value,
        verification.status.value,
        success,
    )

    return ExecutionLoopResult(
        execution=execution_result,
        evidence=evidence,
        verification=verification,
        success=success,
        intended_state=intended_state,
    )
