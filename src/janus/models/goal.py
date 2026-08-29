from dataclasses import dataclass


@dataclass
class Goal:
    title: str
    description: str = ""
    status: str = "active"
    related_tasks: list[str] = None

    def __post_init__(self):
        if self.related_tasks is None:
            self.related_tasks = []
