"""Daily Briefing service for Janus — creates DailyBriefing from events, tasks, and goals.

Delegates attention prioritization to the Attention Engine.
"""

from datetime import date
from typing import TYPE_CHECKING

from janus.models.daily_briefing import DailyBriefing, MAX_ATTENTION_ITEMS, MAX_FOCUS_ITEMS
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

    The attention engine produces a deterministically sorted list; the top
    ``MAX_FOCUS_ITEMS`` (3) are surfaced as the suggested focus and flagged
    on the attention items themselves so renderers can mark them.
    """
    from janus.services.attention import get_attention_items

    attention_items = get_attention_items(events, tasks, goals, today)

    # Cap at MAX_ATTENTION_ITEMS; mark top MAX_FOCUS_ITEMS as focus.
    capped = attention_items[:MAX_ATTENTION_ITEMS]
    for i, item in enumerate(capped):
        item.focus = i < MAX_FOCUS_ITEMS

    suggested_focus = capped[:MAX_FOCUS_ITEMS]

    return DailyBriefing(
        events=events,
        attention_items=capped,
        suggested_focus=suggested_focus,
    )
