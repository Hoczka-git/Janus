from datetime import date

from janus.integrations.google_calendar import list_upcoming_events
from janus.models.task import Task

def get_today_events():
    today = date.today()

    events = list_upcoming_events()

    return [
        event
        for event in events
        if event.start is not None and event.start.date() == today
    ]


def requires_attention(task: Task, today: date) -> bool:
    return (
        task.due_date is not None
        and task.due_date <= today
        or task.priority >= 3
    )


def show_today() -> None:
    today = date.today()

    events = get_today_events()

    tasks = [
        Task(
            title="Buy groceries",
            due_date=today,
            priority=2,
        ),
        Task(
            title="Plan weekend hike",
            priority=1,
        ),
        Task(
            title="Book dentist appointment",
            due_date=date(2026, 8, 27),
            priority=2,
        ),
        Task(
            title="Prepare training plan",
            priority=3,
        ),
    ]

    attention_tasks = [
        task
        for task in tasks
        if requires_attention(task, today)
    ]

    print("JANUS — TODAY")
    print()

    if events:
        print("Events:")

        for event in events:
            if event.all_day:
                print(f"- All day — {event.title}")
            else:
                print(
                    f"- {event.start.strftime('%H:%M')} — "
                    f"{event.title}"
                )

        print()

    if attention_tasks:
        print("Requires attention:")

        for task in attention_tasks:
            print(f"- {task.title}")

    else:
        print("Nothing requires your attention today.")
