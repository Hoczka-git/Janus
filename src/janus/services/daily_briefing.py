from datetime import date
from typing import TYPE_CHECKING

from janus.models.daily_briefing import DailyBriefing

if TYPE_CHECKING:
    from janus.models.event import Event
    from janus.models.task import Task


def create_daily_briefing(
    events: list["Event"],
    tasks: list["Task"],
    today: date,
) -> DailyBriefing:
    """Create a daily briefing from today's events and all tasks."""
    overdue: list["Task"] = []
    due_today: list["Task"] = []
    high_priority: list["Task"] = []

    for task in tasks:
        if task.due_date is not None and task.due_date < today:
            overdue.append(task)
        elif task.due_date is not None and task.due_date == today:
            due_today.append(task)
        elif task.priority >= 3:
            high_priority.append(task)

    seen_ids = set()
    suggested_focus: list["Task"] = []

    for group in (overdue, due_today, high_priority):
        sorted_group = sorted(group, key=lambda t: (-t.priority))
        for task in sorted_group:
            if len(suggested_focus) >= 3:
                break
            if id(task) in seen_ids:
                continue
            seen_ids.add(id(task))
            suggested_focus.append(task)
        if len(suggested_focus) >= 3:
            break

    return DailyBriefing(
        events=events,
        overdue_tasks=overdue,
        due_today_tasks=due_today,
        high_priority_tasks=high_priority,
        suggested_focus=suggested_focus,
    )
