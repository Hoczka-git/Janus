"""Daily Briefing service for Janus — creates DailyBriefing from events, tasks, and goals.

Delegates attention prioritization to the Attention Engine.
"""

from datetime import date
from typing import TYPE_CHECKING

from janus.models.daily_briefing import DailyBriefing
from janus.models.goal import Goal

if TYPE_CHECKING:
    from janus.models.event import Event
    from janus.models.task import Task


def create_daily_briefing(
    events: list["Event"],
    tasks: list["Task"],
    goals: list[Goal],
    today: date,
) -> DailyBriefing:
    """Create a daily briefing from today's events, tasks, and goals.

    Delegates attention prioritization to the Attention Engine.
    """
    from janus.services.attention import get_attention_items

    attention_items = get_attention_items(events, tasks, goals, today)
    suggested_focus = attention_items[0] if attention_items else None

    return DailyBriefing(
        events=events,
        attention_items=attention_items,
        suggested_focus=suggested_focus,
    )
