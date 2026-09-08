"""Project domain model for Janus goal execution planning.

A Project groups related tasks under a Milestone. Projects provide explicit
task assignment (Project.related_tasks) while preserving the existing
dynamic milestone task derivation as a backward-compatible fallback.

The domain model intentionally does NOT contain ``goal_title`` — the Goal is
obtained through the parent Milestone context:

    Project
      └── milestone_title
            └── Goal
"""

from dataclasses import dataclass, field


# Terminal Project states: a project in one of these states is considered
# "done" and is excluded from next-action derivation.
_TERMINAL_STATUSES = frozenset({"completed", "skipped"})

# All valid Project statuses.
_VALID_STATUSES = frozenset({
    "open",
    "active",
    "blocked",
    "completed",
    "skipped",
})


@dataclass
class Project:
    """A project groups related tasks under a milestone.

    Fields:
        title: Human-readable Project identity. Unique within its parent Milestone.
        milestone_title: Parent Milestone reference (title-based, denormalized for markdown).
        description: Optional human-readable description of the execution scope.
        deadline: Optional ISO date YYYY-MM-DD.
        status: One of open, active, blocked, completed, skipped.
        order: Stable sequential position within the parent Milestone (0-based).
        related_tasks: Explicitly assigned Task titles (deduped, ordered).
    """

    title: str
    milestone_title: str
    description: str = ""
    deadline: str | None = None
    status: str = "open"
    order: int = 0
    related_tasks: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.title or not self.title.strip():
            raise ValueError("Project title must not be empty")
        if not self.milestone_title or not self.milestone_title.strip():
            raise ValueError("Project milestone_title must not be empty")
        if self.status not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid project status: {self.status!r}. "
                f"Allowed: {', '.join(sorted(_VALID_STATUSES))}"
            )
        # Dedup related_tasks preserving order
        self.related_tasks = self._dedup(self.related_tasks)

    @staticmethod
    def _dedup(items: list[str]) -> list[str]:
        """Deduplicate preserving order."""
        seen = set()
        result = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    @staticmethod
    def is_terminal_status(status: str) -> bool:
        """Return True if the given status is terminal (completed or skipped)."""
        return status in _TERMINAL_STATUSES

    @property
    def is_terminal(self) -> bool:
        """True if this Project is in a terminal state (completed or skipped)."""
        return self.is_terminal_status(self.status)
