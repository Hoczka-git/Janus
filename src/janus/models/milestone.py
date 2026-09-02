from dataclasses import dataclass


@dataclass
class Milestone:
    """A milestone is a first-class child of a goal.

    Tracks a checkpoint in a goal's execution plan with a deadline,
    status, and the tasks that support it.
    """

    title: str                              # identity within parent goal
    goal_title: str                         # foreign key (denormalized for markdown)
    description: str = ""
    deadline: str | None = None             # ISO date YYYY-MM-DD
    status: str = "open"                    # open | in_progress | completed | skipped
    related_tasks: list[str] | None = None  # task titles supporting this milestone
    order: int = 0                          # sequential position within goal (0-based)

    def __post_init__(self):
        if self.related_tasks is None:
            self.related_tasks = []
        # Dedup preserving order
        self.related_tasks = self._dedup(self.related_tasks)
        if self.status not in ("open", "in_progress", "completed", "skipped"):
            raise ValueError(
                f"Invalid milestone status: {self.status!r}. "
                f"Allowed: open, in_progress, completed, skipped"
            )
        if not self.title or not self.title.strip():
            raise ValueError("Milestone title must not be empty")

    @staticmethod
    def _dedup(items: list[str]) -> list[str]:
        """Deduplicate preserving order."""
        seen = set()
        result = []
        for t in items:
            if t not in seen:
                seen.add(t)
                result.append(t)
        return result
