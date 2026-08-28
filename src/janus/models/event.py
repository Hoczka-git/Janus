from dataclasses import dataclass
from datetime import datetime


@dataclass
class Event:
    title: str
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool = False
