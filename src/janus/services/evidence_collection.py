"""Evidence Collection module for Janus.

Consumes an ExecutionResult (ExecutionResultMessage) and produces a
structured Evidence artifact capturing execution artifacts relevant to
verifying the intended state change: command outputs, logs, state
snapshots, and file changes.

This module is the Janus-side component of the Evidence Collection
pipeline.  It is intentionally decoupled from the Hermes sync listener
and the dispatch path so it can be unit-tested in isolation and reused
by future pipeline stages (outcome verification, audit reporting).

Module interface:
    EvidenceCollector.collect(result: ExecutionResultMessage) -> Evidence
    EvidenceCollector.collect_safe(result: ExecutionResultMessage | None) -> Evidence
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from janus._log import emit
from janus.services.execution_feedback import (
    EvidencePackage,
    ExecutionResultMessage,
    JanusDomainMetadata,
)

logger = logging.getLogger(__name__)


# ── Evidence status ──────────────────────────────────────────────────────────


class EvidenceStatus(StrEnum):
    """Status of evidence collection.

    Members:
        SUCCESS — all expected evidence was collected.
        PARTIAL — some evidence was collected but important fields are missing.
        EMPTY — no evidence could be collected from the execution result.
        ERROR — evidence collection failed due to an error.
    """

    SUCCESS = "success"
    PARTIAL = "partial"
    EMPTY = "empty"
    ERROR = "error"


# ── Evidence component models ────────────────────────────────────────────────


@dataclass
class CommandOutput:
    """Captured output from a command execution.

    Attributes:
        command: The command that was executed.
        stdout: Standard output from the command.
        stderr: Standard error from the command.
        exit_code: Exit code from the command (None if not captured).
        duration_ms: Execution duration in milliseconds (None if not captured).
    """

    command: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    duration_ms: float | None = None


@dataclass
class LogEntry:
    """A captured log entry.

    Attributes:
        source: The source of the log entry (e.g., "execution_feedback").
        message: The log message.
        level: Log level (e.g., "INFO", "WARNING", "ERROR").
        timestamp: ISO-8601 timestamp (None if not captured).
    """

    source: str
    message: str
    level: str = "INFO"
    timestamp: str | None = None


@dataclass
class StateSnapshot:
    """A snapshot of system state at a point in time.

    Attributes:
        label: A label for the snapshot (e.g., "pre-execution", "post-execution").
        state: A dict representing the system state.
        timestamp: ISO-8601 timestamp (None if not captured).
    """

    label: str
    state: dict[str, Any] = field(default_factory=dict)
    timestamp: str | None = None


@dataclass
class FileChange:
    """A file change record.

    Attributes:
        path: The file path that was changed.
        change_type: The type of change ("modified", "created", "deleted").
        diff: Optional diff content for the change.
    """

    path: str
    change_type: str = "modified"
    diff: str | None = None


# ── Evidence artifact ────────────────────────────────────────────────────────


@dataclass
class Evidence:
    """Structured evidence artifact produced by evidence collection.

    Captures execution artifacts relevant to verifying the intended
    state change: command outputs, logs, state snapshots, and file
    changes.  Produced by :class:`EvidenceCollector`.

    Attributes:
        task_id: The ID of the task that produced this evidence.
        domain_object: The Janus domain object type (e.g., "task", "goal").
        domain_title: The title of the Janus domain object.
        collected_at: ISO-8601 timestamp when evidence was collected.
        command_outputs: List of captured command outputs.
        logs: List of captured log entries.
        state_snapshots: List of captured state snapshots.
        file_changes: List of captured file changes.
        tests_passed: Whether tests passed (None if not applicable).
        pr_url: URL of the associated pull request (None if not applicable).
        summary: Human-readable summary of the evidence.
        status: The evidence collection status.
        errors: List of error messages if collection failed.
    """

    task_id: str
    domain_object: str
    domain_title: str
    collected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    command_outputs: list[CommandOutput] = field(default_factory=list)
    logs: list[LogEntry] = field(default_factory=list)
    state_snapshots: list[StateSnapshot] = field(default_factory=list)
    file_changes: list[FileChange] = field(default_factory=list)
    tests_passed: bool | None = None
    pr_url: str | None = None
    summary: str = ""
    status: EvidenceStatus = EvidenceStatus.SUCCESS
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to a plain dict."""
        return {
            "task_id": self.task_id,
            "domain_object": self.domain_object,
            "domain_title": self.domain_title,
            "collected_at": self.collected_at,
            "command_outputs": [
                {
                    "command": co.command,
                    "stdout": co.stdout,
                    "stderr": co.stderr,
                    "exit_code": co.exit_code,
                    "duration_ms": co.duration_ms,
                }
                for co in self.command_outputs
            ],
            "logs": [
                {
                    "source": le.source,
                    "message": le.message,
                    "level": le.level,
                    "timestamp": le.timestamp,
                }
                for le in self.logs
            ],
            "state_snapshots": [
                {
                    "label": ss.label,
                    "state": ss.state,
                    "timestamp": ss.timestamp,
                }
                for ss in self.state_snapshots
            ],
            "file_changes": [
                {
                    "path": fc.path,
                    "change_type": fc.change_type,
                    "diff": fc.diff,
                }
                for fc in self.file_changes
            ],
            "tests_passed": self.tests_passed,
            "pr_url": self.pr_url,
            "summary": self.summary,
            "status": self.status,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Evidence:
        """Deserialize from a plain dict.

        Tolerates missing keys — every field has a sensible default.
        """
        return cls(
            task_id=data.get("task_id", ""),
            domain_object=data.get("domain_object", ""),
            domain_title=data.get("domain_title", ""),
            collected_at=data.get("collected_at", ""),
            command_outputs=[
                CommandOutput(**co) for co in data.get("command_outputs", [])
            ],
            logs=[LogEntry(**le) for le in data.get("logs", [])],
            state_snapshots=[
                StateSnapshot(**ss) for ss in data.get("state_snapshots", [])
            ],
            file_changes=[
                FileChange(**fc) for fc in data.get("file_changes", [])
            ],
            tests_passed=data.get("tests_passed"),
            pr_url=data.get("pr_url"),
            summary=data.get("summary", ""),
            status=EvidenceStatus(data.get("status", "success")),
            errors=data.get("errors", []),
        )


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
            return Evidence(
                task_id=getattr(result.evidence, "task_id", ""),
                domain_object=getattr(result.metadata, "object", "unknown"),
                domain_title=getattr(result.metadata, "title", "unknown"),
                status=EvidenceStatus.ERROR,
                errors=[str(exc)],
                summary=f"Evidence collection failed: {exc}",
            )
