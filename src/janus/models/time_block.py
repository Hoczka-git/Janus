from dataclasses import dataclass
from datetime import datetime


@dataclass
class TimeBlock:
    start: datetime
    end: datetime
    title: str = ""
    type: str = "free"  # "free" | "busy"

    @property
    def duration_minutes(self) -> int:
        delta = self.end - self.start
        return int(delta.total_seconds() // 60)

    @property
    def is_free(self) -> bool:
        return self.type == "free"


@dataclass
class Placement:
    """A task recommended for placement in a specific free time block."""

    task_title: str
    slot: TimeBlock
    reason: str

