"""Today view for Janus — renders schedule, attention items, and suggested focus.

Implements the Attention Engine integration: Daily Briefing now delegates
to the Attention Engine for deterministic prioritization of what deserves
the user's attention right now.
"""

from datetime import date
from io import StringIO
from typing import TYPE_CHECKING
from unittest.mock import patch

from janus.integrations.google_calendar import list_upcoming_events
from janus.integrations.markdown_tasks import load_tasks
from janus.integrations.markdown_goals import load_goals
from janus.integrations.telegram import send_briefing
from janus.services.daily_briefing import create_daily_briefing
from janus.models.daily_briefing import MAX_ATTENTION_ITEMS
from janus.models.event import Event
from janus.models.task import Task
from janus.models.goal import Goal
from janus.models.attention import AttentionItem

if TYPE_CHECKING:
    from janus.models.daily_briefing import DailyBriefing


def _build_today_briefing() -> "DailyBriefing":
    """Collect today's events, open tasks, and active goals into a DailyBriefing.

    This helper is used by both show_today() and show_telegram() to avoid
    duplicating the data-collection logic.
    """
    today = date.today()
    all_events = list_upcoming_events()
    today_events: list[Event] = [
        e for e in all_events
        if e.start is not None and e.start.date() == today
    ]
    tasks = load_tasks()
    goals = load_goals()
    return create_daily_briefing(today_events, tasks, goals, today)


def show_today() -> None:
    briefing = _build_today_briefing()

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

    displayed = briefing.attention_items[:MAX_ATTENTION_ITEMS]
    for i, item in enumerate(displayed, 1):
        has_attention = True
        focus_marker = " [FOCUS]" if item.focus else ""
        print(f"{i}. {item.title}{focus_marker}")
        print(f"   {item.reason}")

    hidden_count = len(briefing.attention_items) - len(displayed)
    if hidden_count > 0:
        has_attention = True
        print(f"and {hidden_count} more")

    if not has_attention:
        print("Nothing requires your attention today.")
    print()

    if briefing.suggested_focus:
        print("SUGGESTED FOCUS")
        for i, item in enumerate(briefing.suggested_focus, 1):
            print(f"{i}. {item.title}")
            print(f"   {item.reason}")
        print()


def show_telegram() -> None:
    briefing = _build_today_briefing()
    send_briefing(briefing)
