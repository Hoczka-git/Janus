from dataclasses import dataclass


@dataclass
class Milestone:
    """A milestone is a first-class child of a goal.

    Tracks a checkpoint in a goal's execution plan with a deadline and
    status. Task-to-milestone membership is NOT stored here — it is derived
    dynamically at query/planning time (see services/next_action.py,
    ``derive_milestone_tasks``). A shared task belongs to whichever
    non-terminal milestone is earliest in ``order``; as earlier milestones
    complete or are skipped, the task becomes eligible for the next
    non-terminal milestone.
    """

    title: str                              # identity within parent goal
    goal_title: str                         # foreign key (denormalized for markdown)
    description: str = ""
    deadline: str | None = None             # ISO date YYYY-MM-DD
    status: str = "open"                    # open | in_progress | completed | skipped
    order: int = 0                          # sequential position within goal (0-based)

    def __post_init__(self):
        if self.status not in ("open", "in_progress", "completed", "skipped"):
            raise ValueError(
                f"Invalid milestone status: {self.status!r}. "
                f"Allowed: open, in_progress, completed, skipped"
            )
        if not self.title or not self.title.strip():
            raise ValueError("Milestone title must not be empty")
