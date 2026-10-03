"""Evidence data model for Janus.

Defines the structured Evidence artifact data model that captures
execution artifacts: command outputs, logs, state snapshots, and file
changes.  This module contains only the data model definitions — no
collection logic or pipeline integration.

Module interface:
    EvidenceStatus — status of evidence collection
    CommandOutput — captured output from a command execution
    LogEntry — a captured log entry
    StateSnapshot — a snapshot of system state at a point in time
    FileChange — a file change record
    Evidence — structured evidence artifact produced by evidence collection
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


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
