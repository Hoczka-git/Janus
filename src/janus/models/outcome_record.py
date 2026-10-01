"""OutcomeRecord model for Janus — Phase B (Evidence & Audit).

An ``OutcomeRecord`` is a standalone domain concept that captures the
final result of a task or goal execution. Unlike ``IntegrationResult``
(which records the mechanical outcome of a git integration), an
``OutcomeRecord`` captures the semantic outcome: what was attempted,
what happened, and what was learned.

Spec: ``docs/janus-agency-first-development-phase.md`` §13 Phase B.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class OutcomeStatus(StrEnum):
    """Classification of an outcome."""

    SUCCESS = "success"
    """The intended result was achieved."""

    PARTIAL = "partial"
    """Some but not all of the intended result was achieved."""

    FAILURE = "failure"
    """The intended result was not achieved."""

    ABANDONED = "abandoned"
    """The attempt was abandoned before completion."""


@dataclass
class OutcomeRecord:
    """A standalone record of an outcome.

    This is a domain concept that captures the semantic result of work,
    independent of the mechanical integration outcome. It can be linked
    to tasks, goals, or follow-ups.

    Attributes:
        id: Stable identity for the outcome record.
        title: Human-readable summary of what was attempted.
        status: Classification of the outcome.
        attempted: What was attempted.
        result: What actually happened.
        learned: What was learned from the outcome.
        linked_task_title: Optional task this outcome relates to.
        linked_goal_title: Optional goal this outcome relates to.
        linked_adr: Optional ADR number this outcome informs.
        created_at: When the outcome was recorded.
        tags: Optional tags for categorization.
    """

    id: str
    title: str
    status: OutcomeStatus = OutcomeStatus.SUCCESS
    attempted: str = ""
    result: str = ""
    learned: str = ""
    linked_task_title: str = ""
    linked_goal_title: str = ""
    linked_adr: str = ""
    created_at: datetime | None = None
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("OutcomeRecord.id must not be empty")
        if not self.title or not self.title.strip():
            raise ValueError("OutcomeRecord.title must not be empty")
        if not isinstance(self.status, OutcomeStatus):
            raise ValueError(
                f"Invalid status: {self.status!r}. "
                f"Allowed: {', '.join(s.value for s in OutcomeStatus)}"
            )
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.tags is None:
            self.tags = []
        self.tags = self._dedup(self.tags)

    @staticmethod
    def _dedup(tags: list[str]) -> list[str]:
        """Deduplicate preserving order."""
        seen = set()
        result = []
        for t in tags:
            if t not in seen:
                seen.add(t)
                result.append(t)
        return result

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        from dataclasses import asdict

        raw = asdict(self)
        raw["status"] = self.status.value
        if self.created_at and hasattr(self.created_at, "isoformat"):
            raw["created_at"] = self.created_at.isoformat()
        return raw
