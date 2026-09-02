from dataclasses import dataclass

@dataclass
class Goal:
    # Required
    title: str                              # persistence identity, immutable in MVP

    # Optional descriptive
    description: str = ""
    status: str = "active"                  # active | completed | inactive
    deadline: str | None = None             # ISO date YYYY-MM-DD

    # Optional metric fields (7 new)
    metric_name: str | None = None          # e.g. "Body fat %"
    metric_unit: str | None = None          # e.g. "%", "PLN", "kg"
    start_value: float | None = None        # baseline
    current_value: float | None = None      # latest
    target_value: float | None = None       # desired outcome
    direction: str | None = None            # "increase" | "decrease"

    # Task relationship
    related_tasks: list[str] = None         # supporting task titles (deduped, ordered)

    # Execution planning (optional)
    # Stored as list[dict] (not list[Milestone]) to avoid import cycle and
    # keep markdown serialization simple. The service layer constructs
    # Milestone objects from the dicts when needed.
    milestones: list[dict] | None = None     # list of milestone dicts (see spec)

    def __post_init__(self):
        if self.related_tasks is None:
            self.related_tasks = []
        # Dedup preserving order
        self.related_tasks = self._dedup_related_tasks(self.related_tasks)
        if self.milestones is None:
            self.milestones = []
        if self.status not in ("active", "completed", "inactive"):
            raise ValueError(
                f"Invalid goal status: {self.status!r}. "
                f"Allowed: active, completed, inactive"
            )
        if self.direction is not None and self.direction not in ("increase", "decrease"):
            raise ValueError(
                f"Invalid direction: {self.direction!r}. "
                f"Allowed: increase, decrease"
            )
        if not self.title or not self.title.strip():
            raise ValueError("Goal title must not be empty")

    @staticmethod
    def _dedup_related_tasks(tasks: list[str]) -> list[str]:
        """Deduplicate preserving order."""
        seen = set()
        result = []
        for t in tasks:
            if t not in seen:
                seen.add(t)
                result.append(t)
        return result
