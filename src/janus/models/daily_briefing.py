from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .event import Event
    from .task import Task


@dataclass
class DailyBriefing:
    events: list["Event"]
    overdue_tasks: list["Task"]
    due_today_tasks: list["Task"]
    high_priority_tasks: list["Task"]
    suggested_focus: list["Task"]
