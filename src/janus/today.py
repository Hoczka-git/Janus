"""Today view for Janus — renders schedule, attention items, and suggested focus.

Implements the Attention Engine integration: Daily Briefing now delegates
to the Attention Engine for deterministic prioritization of what deserves
the user's attention right now.
"""

from datetime import date
from io import StringIO
from typing import TYPE_CHECKING
from unittest.mock import patch

import logging
import time

from janus._log import emit
from janus.integrations.google_calendar import list_upcoming_events, _load_config
from janus.integrations.markdown_tasks import load_tasks
from janus.integrations.markdown_goals import load_goals
from janus.integrations.telegram import send_briefing
from janus.services.daily_briefing import create_daily_briefing
from janus.models.event import Event
from janus.models.task import Task
from janus.models.goal import Goal
from janus.models.attention import AttentionItem

if TYPE_CHECKING:
    from janus.models.daily_briefing import DailyBriefing

logger = logging.getLogger(__name__)


def _build_today_briefing(trace_id: str | None = None) -> "DailyBriefing":
    """Collect today's events, open tasks, and active goals into a DailyBriefing.

    This helper is used by both show_today() and show_telegram() to avoid
    duplicating the data-collection logic.
    """
    start = time.monotonic()
    emit(logger, "briefing.generation.started",
         trace_id=trace_id, span_id="build_daily",
         correlation_id=trace_id,
         briefing_type="daily",
         message="Daily briefing generation started")

    today = date.today()
    all_events = list_upcoming_events(trace_id=trace_id)
    today_events: list[Event] = [
        e for e in all_events
        if (
            e.start is not None
            and (
                e.start.date() == today
                or (e.end is not None and e.start.date() < today <= e.end.date())
            )
        )
    ]
    tasks = load_tasks(trace_id=trace_id)
    goals = load_goals(trace_id=trace_id)
    briefing = create_daily_briefing(today_events, tasks, goals, today, trace_id=trace_id)

    # Build attention breakdown from the briefing for the finished event.
    attention_items_count = len(briefing.attention_items)
    attention_by_category: dict[str, int] = {}
    for item in briefing.attention_items:
        attention_by_category[item.category] = (
            attention_by_category.get(item.category, 0) + 1
        )
    suggested_focus_present = len(briefing.suggested_focus) > 0

    duration_ms = (time.monotonic() - start) * 1000
    emit(logger, "briefing.generation.finished",
         trace_id=trace_id, span_id="build_daily",
         correlation_id=trace_id,
         briefing_type="daily",
         duration_ms=duration_ms,
         source_calendars=len(_load_config()),
         events_total=len(all_events),
         events_today=len(today_events),
         tasks_loaded=len(tasks),
         goals_loaded=len(goals),
         attention_items=attention_items_count,
         attention_by_category=attention_by_category,
         suggested_focus_present=suggested_focus_present,
         message="Daily briefing generation finished")

    return briefing


def show_today(trace_id: str | None = None) -> None:
    briefing = _build_today_briefing(trace_id)

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

    if briefing.has_calendar and briefing.free_slots:
        print("FREE TIME")
        for slot in briefing.free_slots:
            print(
                f"- {slot.start.strftime('%H:%M')}–{slot.end.strftime('%H:%M')} "
                f"({slot.duration_minutes} min)"
            )
        print()

    if briefing.has_calendar and briefing.overload_warning:
        print("CALENDAR LOAD")
        print(briefing.overload_warning)
        print()

    if briefing.has_calendar and briefing.placements:
        print("SUGGESTED PLACEMENTS")
        for i, placement in enumerate(briefing.placements, 1):
            print(
                f"{i}. {placement.task_title} — "
                f"{placement.slot.start.strftime('%H:%M')}–"
                f"{placement.slot.end.strftime('%H:%M')}"
            )
            print(f"   {placement.reason}")
        print()

    print("REQUIRES ATTENTION")
    has_attention = False

    for i, item in enumerate(briefing.attention_items[:3], 1):
        has_attention = True
        print(f"{i}. {item.title}")
        print(f"   {item.reason}")

    if not has_attention:
        print("Nothing requires your attention today.")
    print()

    if briefing.suggested_focus:
        print("SUGGESTED FOCUS")
        for i, item in enumerate(briefing.suggested_focus, 1):
            print(f"{i}. {item.title}")
            print(f"   {item.reason}")
        print()


def show_telegram(trace_id: str | None = None) -> None:
    briefing = _build_today_briefing(trace_id)
    send_briefing(briefing, trace_id=trace_id)


def _capture_show_today(events, tasks, goals, today=date(2026, 8, 28)):
    """Run show_today() with mocked dependencies and return printed output.

    This helper is used by tests to capture CLI output without making
    real Google Calendar or file-system calls.
    """
    with patch("janus.today.list_upcoming_events", return_value=events), \
         patch("janus.today.load_tasks", return_value=tasks), \
         patch("janus.today.load_goals", return_value=goals), \
         patch("janus.today.date") as mock_date:
        mock_date.today.return_value = today
        mock_date.__eq__ = lambda self, other: self.toordinal() == other.toordinal()
        mock_date.__hash__ = lambda self: hash(self.toordinal())
        mock_date.isoformat.return_value = today.isoformat()

        buf = StringIO()
        with patch("sys.stdout", buf):
            show_today()
        return buf.getvalue()
