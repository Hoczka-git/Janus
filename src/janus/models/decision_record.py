"""Decision Record model for Janus — §9.2 (6-stage decision record shape).

A ``DecisionRecord`` represents a structured decision record following
the 6-stage shape: WHY → WHAT → ACTION → EVIDENCE → RESULT → DECISION.

Spec: ``docs/janus-agency-first-development-phase.md`` §9.2.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class DecisionRecordStatus(StrEnum):
    """Status of a decision record."""

    DRAFT = "draft"
    """The decision record is being drafted."""

    PROPOSED = "proposed"
    """The decision record has been proposed."""

    ACCEPTED = "accepted"
    """The decision record has been accepted."""

    REJECTED = "rejected"
    """The decision record has been rejected."""

    DEPRECATED = "deprecated"
    """The decision record has been deprecated."""


@dataclass
class DecisionRecord:
    """A structured decision record following the 6-stage shape.

    The 6 stages are:
    1. WHY: Why is this decision needed?
    2. WHAT: What is being decided?
    3. ACTION: What action will be taken?
    4. EVIDENCE: What evidence supports this decision?
    5. RESULT: What was the result of the action?
    6. DECISION: What was the final decision?

    Attributes:
        id: Stable identity for the decision record.
        title: Human-readable title of the decision.
        status: Current status of the decision record.
        why: Why is this decision needed?
        what: What is being decided?
        action: What action will be taken?
        evidence: What evidence supports this decision?
        result: What was the result of the action?
        decision: What was the final decision?
        created_at: When the decision record was created.
        updated_at: When the decision record was last updated.
        linked_goal_title: Optional goal this decision relates to.
        linked_adr: Optional ADR number this decision relates to.
        tags: Optional tags for categorization.
    """

    id: str
    title: str
    status: DecisionRecordStatus = DecisionRecordStatus.DRAFT
    why: str = ""
    what: str = ""
    action: str = ""
    evidence: str = ""
    result: str = ""
    decision: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    linked_goal_title: str = ""
    linked_adr: str = ""
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("DecisionRecord.id must not be empty")
        if not self.title or not self.title.strip():
            raise ValueError("DecisionRecord.title must not be empty")
        if not isinstance(self.status, DecisionRecordStatus):
            raise ValueError(
                f"Invalid status: {self.status!r}. "
                f"Allowed: {', '.join(s.value for s in DecisionRecordStatus)}"
            )
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()
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

    @property
    def is_complete(self) -> bool:
        """Return True if all 6 stages are filled."""
        return all([
            self.why.strip(),
            self.what.strip(),
            self.action.strip(),
            self.evidence.strip(),
            self.result.strip(),
            self.decision.strip(),
        ])

    @property
    def completion_percentage(self) -> float:
        """Return the completion percentage (0.0 to 1.0)."""
        stages = [self.why, self.what, self.action, self.evidence, self.result, self.decision]
        filled = sum(1 for s in stages if s.strip())
        return filled / len(stages)

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        from dataclasses import asdict

        raw = asdict(self)
        raw["status"] = self.status.value
        raw["is_complete"] = self.is_complete
        raw["completion_percentage"] = self.completion_percentage
        if self.created_at and hasattr(self.created_at, "isoformat"):
            raw["created_at"] = self.created_at.isoformat()
        if self.updated_at and hasattr(self.updated_at, "isoformat"):
            raw["updated_at"] = self.updated_at.isoformat()
        return raw
