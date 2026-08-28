from dataclasses import dataclass
from datetime import date


@dataclass
class Task:
    title: str
    due_date: date | None = None
    priority: int = 1
