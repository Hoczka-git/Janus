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
from typing import Any

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


# ── Safe field access helpers ────────────────────────────────────────────────


def _safe_str(value: Any, default: str = "") -> str:
    """Coerce a value to a string, returning *default* if *value* is None."""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def _safe_str_list(value: Any) -> list[str]:
    """Coerce a value to a list of strings.

    - ``None`` → ``[]``
    - ``str`` → ``[value]`` if non-empty, else ``[]``
    - ``list``/``tuple`` → ``[str(item) for item in value if item is not None]``
    - anything else → ``[]``
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item is not None]
    return []


def _safe_bool_or_none(value: Any) -> bool | None:
    """Coerce a value to ``bool`` or ``None``.

    - ``None`` → ``None``
    - ``bool`` → as-is
    - ``int``/``float`` → ``bool(value)``
    - ``str`` → ``True`` for ``"true"``, ``"1"``, ``"yes"`` (case-insensitive)
    - anything else → ``None``
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return None


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

        # Safely access metadata and evidence
        metadata = getattr(result, "metadata", None)
        evidence_pkg = getattr(result, "evidence", None)

        # Handle None metadata / evidence gracefully
        if metadata is None:
            metadata = JanusDomainMetadata(object="unknown", title="unknown")
        if evidence_pkg is None:
            evidence_pkg = EvidencePackage(task_id="", summary="")

        # Safely extract fields
        domain_object = _safe_str(getattr(metadata, "object", "unknown"), "unknown")
        domain_title = _safe_str(getattr(metadata, "title", "unknown"), "unknown")
        task_id = _safe_str(getattr(evidence_pkg, "task_id", ""))
        summary = _safe_str(getattr(evidence_pkg, "summary", ""))
        pr_url_raw = getattr(evidence_pkg, "pr_url", None)
        pr_url = str(pr_url_raw) if pr_url_raw is not None else None
        tests_passed = _safe_bool_or_none(getattr(evidence_pkg, "tests_passed", None))

        # Safely extract changed_files
        metadata_changed_files = _safe_str_list(getattr(metadata, "changed_files", None))
        evidence_changed_files = _safe_str_list(getattr(evidence_pkg, "changed_files", None))
        changed_files = metadata_changed_files or evidence_changed_files or []

        # Build file changes
        file_changes = [
            FileChange(path=path, change_type="modified")
            for path in changed_files
        ]

        # Build command outputs
        command_outputs = []
        if tests_passed is not None:
            command_outputs.append(
                CommandOutput(
                    command="pytest",
                    stdout=f"tests_passed={tests_passed}",
                    exit_code=0 if tests_passed else 1,
                )
            )

        # Build logs
        logs = []
        if summary:
            logs.append(
                LogEntry(
                    source="execution_feedback",
                    message=summary,
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
                        "tests_passed": tests_passed,
                        "pr_url": pr_url,
                    },
                )
            )

        # Determine status
        has_changed_files = bool(changed_files)
        has_tests = tests_passed is not None
        has_pr = bool(pr_url)
        has_body = bool(getattr(evidence_pkg, "body", None) or getattr(evidence_pkg, "janus_body", None))
        metric_updates = getattr(evidence_pkg, "metric_updates", None)
        has_metrics = isinstance(metric_updates, list) and bool(metric_updates)

        if not has_changed_files and not has_tests and not has_pr and not has_body and not has_metrics:
            status = EvidenceStatus.EMPTY
        elif has_changed_files and has_tests:
            status = EvidenceStatus.SUCCESS
        else:
            status = EvidenceStatus.PARTIAL

        # Build summary
        parts = [f"Evidence for {domain_object}={domain_title!r}"]
        if has_changed_files:
            parts.append(f"{len(file_changes)} file(s) changed")
        if has_tests:
            parts.append(f"tests {'passed' if tests_passed else 'failed'}")
        if has_pr:
            parts.append(f"PR: {pr_url}")
        if isinstance(metric_updates, list) and metric_updates:
            parts.append(f"{len(metric_updates)} metric update(s)")

        collected = Evidence(
            task_id=task_id,
            domain_object=domain_object,
            domain_title=domain_title,
            command_outputs=command_outputs,
            logs=logs,
            state_snapshots=state_snapshots,
            file_changes=file_changes,
            tests_passed=tests_passed,
            pr_url=pr_url,
            summary="; ".join(parts),
            status=status,
        )

        emit(
            logger,
            "service.evidence_collection.collected",
            trace_id=None,
            span_id="evidence_collection",
            domain_object=domain_object,
            domain_title=domain_title,
            task_id=task_id,
            status=status.value,
            message=f"Evidence collected for {domain_object}={domain_title!r}",
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
            # Safely extract fields for error evidence — getattr with default
            # catches AttributeError, but a property raising another exception
            # would propagate. Wrap each access defensively.
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
                task_id=_safe_str(task_id),
                domain_object=_safe_str(domain_object, "unknown"),
                domain_title=_safe_str(domain_title, "unknown"),
                status=EvidenceStatus.ERROR,
                errors=[str(exc)],
                summary=f"Evidence collection failed: {exc}",
            )
