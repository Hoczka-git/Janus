from dataclasses import dataclass
from datetime import date

ALLOWED_STATES = frozenset({"todo", "in_progress", "blocked"})


@dataclass
class Task:
    title: str
    due_date: date | None = None
    priority: int = 1
    state: str | None = None
    progress: int | None = None
    extra_metadata: list[str] | None = None

    def __post_init__(self) -> None:
        if self.state is not None and self.state not in ALLOWED_STATES:
            raise ValueError(
                f"Invalid task state: {self.state!r}. "
                f"Allowed values: {', '.join(sorted(ALLOWED_STATES))}"
            )
        if self.progress is not None:
            if not isinstance(self.progress, int) or not (0 <= self.progress <= 100):
                raise ValueError(
                    f"Progress must be an integer between 0 and 100, got {self.progress!r}"
                )
