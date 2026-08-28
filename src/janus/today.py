from datetime import date

from janus.integrations.google_calendar import list_upcoming_events
from janus.integrations.markdown_tasks import load_tasks
from janus.integrations.telegram import send_briefing
from janus.models.event import Event
from janus.services.daily_briefing import create_daily_briefing


def show_today() -> None:
    today = date.today()

    all_events = list_upcoming_events()
    today_events: list[Event] = [
        e for e in all_events
        if e.start is not None and e.start.date() == today
    ]

    tasks = load_tasks()
    briefing = create_daily_briefing(today_events, tasks, today)

    print("JANUS — TODAY")
    print()

    print("SCHEDULE")
    if briefing.events:
        for event in briefing.events:
            if event.all_day:
                print(f"- All day — {event.title}")
            elif event.start:
                source = f" — {event.source}" if event.source else ""
                print(f"- {event.start.strftime('%H:%M')} — {event.title}{source}")
    else:
        print("No events scheduled today.")
    print()

    print("REQUIRES ATTENTION")
    has_attention = False

    if briefing.overdue_tasks:
        has_attention = True
        print("Overdue:")
        for task in briefing.overdue_tasks:
            print(f"- {task.title}")
        print()

    if briefing.due_today_tasks:
        has_attention = True
        print("Due today:")
        for task in briefing.due_today_tasks:
            print(f"- {task.title}")
        print()

    if briefing.high_priority_tasks:
        has_attention = True
        print("High priority:")
        for task in briefing.high_priority_tasks:
            print(f"- {task.title}")
        print()

    if not has_attention:
        print("Nothing requires your attention today.")
    print()

    if briefing.suggested_focus:
        print("SUGGESTED FOCUS")
        for i, task in enumerate(briefing.suggested_focus, 1):
            print(f"{i}. {task.title}")
        print()


def show_telegram() -> None:
    today = date.today()

    all_events = list_upcoming_events()
    today_events: list[Event] = [
        e for e in all_events
        if e.start is not None and e.start.date() == today
    ]

    tasks = load_tasks()
    briefing = create_daily_briefing(today_events, tasks, today)

    send_briefing(briefing)
