"""Evidence Collection module for Janus.

Consumes an ExecutionResult (ExecutionResultMessage) and produces a
structured Evidence artifact capturing execution artifacts relevant to
verifying the intended state change: command outputs, logs, state
snapshots, and file changes.

This module is the Janus-side component of the Evidence Collection
pipeline.  It is intentionally decoupled from the Hermes sync listener
and the dispatch path so it can be unit-tested in isolation and reused
by future pipeline stages (outcome verification, audit reporting).

The data model definitions live in :mod:`janus.services.evidence`.

Module interface:
    EvidenceCollector.collect(result: ExecutionResultMessage) -> Evidence
    EvidenceCollector.collect_safe(result: ExecutionResultMessage | None) -> Evidence
"""
from __future__ import annotations

import logging

from janus._log import emit
from janus.services.evidence import (
    CommandOutput,
    Evidence,
    EvidenceStatus,
    FileChange,
    LogEntry,
    StateSnapshot,
)
from janus.services.execution_feedback import (
    EvidencePackage,
    ExecutionResultMessage,
    JanusDomainMetadata,
)

logger = logging.getLogger(__name__)


# ── Evidence collector ───────────────────────────────────────────────────────


class EvidenceCollector:
    """Collects structured evidence from an ExecutionResult.

    This is the main entry point for evidence collection.  It consumes
    an :class:`ExecutionResultMessage` and produces a structured
    :class:`Evidence` artifact.

    The collector extracts what is available from the execution result
    (file changes, test results, PR URL, summary) and builds a
    complete Evidence artifact.  Missing or partial results are handled
    gracefully — the status field indicates whether the collection was
    successful, partial, empty, or errored.
    """

    def collect(self, result: ExecutionResultMessage | None) -> Evidence:
        """Collect evidence from an execution result.

        Handles ``None`` input and missing fields gracefully — returns a
        valid :class:`Evidence` with ``status=ERROR`` rather than raising.

        Args:
            result: The execution result message to collect evidence from,
                or ``None``.

        Returns:
            A structured :class:`Evidence` artifact.
        """
        if result is None:
            return Evidence(
                task_id="",
                domain_object="unknown",
                domain_title="unknown",
                status=EvidenceStatus.ERROR,
                errors=["No execution result provided"],
                summary="Evidence collection failed: no execution result",
            )

        metadata = result.metadata
        evidence_pkg = result.evidence

        # Handle None metadata / evidence gracefully
        if metadata is None:
            metadata = JanusDomainMetadata(object="unknown", title="unknown")
        if evidence_pkg is None:
            evidence_pkg = EvidencePackage(task_id="", summary="")

        # Build file changes from changed_files
        changed_files = metadata.changed_files or evidence_pkg.changed_files or []
        file_changes = [
            FileChange(path=path, change_type="modified")
            for path in changed_files
        ]

        # Build command outputs from evidence
        command_outputs = []
        if evidence_pkg.tests_passed is not None:
            command_outputs.append(
                CommandOutput(
                    command="pytest",
                    stdout=f"tests_passed={evidence_pkg.tests_passed}",
                    exit_code=0 if evidence_pkg.tests_passed else 1,
                )
            )

        # Build logs from evidence summary
        logs = []
        if evidence_pkg.summary:
            logs.append(
                LogEntry(
                    source="execution_feedback",
                    message=evidence_pkg.summary,
                    level="INFO",
                )
            )

        # Build state snapshots
        state_snapshots = []
        if changed_files:
            state_snapshots.append(
                StateSnapshot(
                    label="post-execution",
                    state={
                        "changed_files": changed_files,
                        "tests_passed": evidence_pkg.tests_passed,
                        "pr_url": evidence_pkg.pr_url,
                    },
                )
            )

        # Determine status
        has_changed_files = bool(changed_files)
        has_tests = evidence_pkg.tests_passed is not None
        has_pr = bool(evidence_pkg.pr_url)
        has_body = bool(evidence_pkg.body or evidence_pkg.janus_body)
        has_metrics = bool(evidence_pkg.metric_updates)

        if not has_changed_files and not has_tests and not has_pr and not has_body and not has_metrics:
            status = EvidenceStatus.EMPTY
        elif has_changed_files and has_tests:
            status = EvidenceStatus.SUCCESS
        else:
            status = EvidenceStatus.PARTIAL

        # Build summary
        parts = [f"Evidence for {metadata.object}={metadata.title!r}"]
        if has_changed_files:
            parts.append(f"{len(file_changes)} file(s) changed")
        if has_tests:
            parts.append(
                f"tests {'passed' if evidence_pkg.tests_passed else 'failed'}"
            )
        if has_pr:
            parts.append(f"PR: {evidence_pkg.pr_url}")
        if has_metrics and evidence_pkg.metric_updates is not None:
            parts.append(f"{len(evidence_pkg.metric_updates)} metric update(s)")

        collected = Evidence(
            task_id=evidence_pkg.task_id,
            domain_object=metadata.object,
            domain_title=metadata.title,
            command_outputs=command_outputs,
            logs=logs,
            state_snapshots=state_snapshots,
            file_changes=file_changes,
            tests_passed=evidence_pkg.tests_passed,
            pr_url=evidence_pkg.pr_url,
            summary="; ".join(parts),
            status=status,
        )

        emit(
            logger,
            "service.evidence_collection.collected",
            trace_id=None,
            span_id="evidence_collection",
            domain_object=metadata.object,
            domain_title=metadata.title,
            task_id=evidence_pkg.task_id,
            status=status.value,
            message=f"Evidence collected for {metadata.object}={metadata.title!r}",
        )

        return collected

    def collect_safe(
        self, result: ExecutionResultMessage | None
    ) -> Evidence:
        """Collect evidence, handling None or malformed input gracefully.

        Unlike :meth:`collect`, this method never raises.  If the input
        is None or an error occurs during collection, an :class:`Evidence`
        with ``status=ERROR`` is returned.

        Args:
            result: The execution result message, or None.

        Returns:
            A structured :class:`Evidence` artifact (with ERROR status
            if input is invalid).
        """
        if result is None:
            return Evidence(
                task_id="",
                domain_object="unknown",
                domain_title="unknown",
                status=EvidenceStatus.ERROR,
                errors=["No execution result provided"],
                summary="Evidence collection failed: no execution result",
            )

        try:
            return self.collect(result)
        except Exception as exc:
            # Safely extract task_id/domain from result, handling cases where
            # accessing result.evidence or result.metadata itself raises.
            try:
                task_id = getattr(result.evidence, "task_id", "")
            except Exception:
                task_id = ""
            try:
                domain_object = getattr(result.metadata, "object", "unknown")
            except Exception:
                domain_object = "unknown"
            try:
                domain_title = getattr(result.metadata, "title", "unknown")
            except Exception:
                domain_title = "unknown"
            return Evidence(
                task_id=task_id,
                domain_object=domain_object,
                domain_title=domain_title,
                status=EvidenceStatus.ERROR,
                errors=[str(exc)],
                summary=f"Evidence collection failed: {exc}",
            )
