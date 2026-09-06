"""Decision model for Janus.

A structured in-memory representation of an ADR (Architectural Decision Record).
Canonical storage is markdown in docs/decisions/; this dataclass is the
structured access model for linking and querying.

Follows the existing Janus dataclass pattern (goal.py, research_artifact.py).
"""

from dataclasses import dataclass, field
from datetime import datetime


VALID_DECISION_STATUSES = ("proposed", "accepted", "deprecated", "superseded")


@dataclass
class Decision:
    """A structured decision record.

    Canonical storage is markdown ADR files in docs/decisions/. This model
    is the in-memory representation for linking and querying, not a new
    persistence format.
    """

    adr_number: str                 # e.g. "001" — matches filename prefix
    title: str                      # e.g. "Hermes-Janus System Model"
    status: str = "proposed"        # proposed | accepted | deprecated | superseded
    context: str = ""               # problem statement / context
    decision: str = ""              # what was decided
    consequences: str = ""          # positive and negative consequences
    goal_titles: list[str] = field(default_factory=list)
    supersedes_adr: str | None = None  # ADR number this decision supersedes
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.adr_number or not self.adr_number.strip():
            raise ValueError("Decision.adr_number must not be empty")
        if not self.title or not self.title.strip():
            raise ValueError("Decision.title must not be empty")
        if self.status not in VALID_DECISION_STATUSES:
            raise ValueError(
                f"Invalid status: {self.status!r}. "
                f"Allowed values: {', '.join(VALID_DECISION_STATUSES)}"
            )
        if self.goal_titles is None:
            self.goal_titles = []
        self.goal_titles = self._dedup(self.goal_titles)
        for t in self.goal_titles:
            if not isinstance(t, str):
                raise ValueError(
                    f"Decision.goal_titles must contain str instances, "
                    f"got {type(t).__name__}"
                )

    @staticmethod
    def _dedup(titles: list[str]) -> list[str]:
        """Deduplicate preserving order."""
        seen = set()
        result = []
        for t in titles:
            if t not in seen:
                seen.add(t)
                result.append(t)
        return result
