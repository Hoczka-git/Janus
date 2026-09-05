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
    from janus.integrations.google_calendar import _load_config

    attention_items = get_attention_items(events, tasks, goals, today)
    suggested_focus = attention_items[0] if attention_items else None

    calendar_configured = bool(_load_config())

    free_slots = []
    overload_warning = None
    placements = []

    if calendar_configured:
        from janus.services.freebusy import compute_free_slots
        from janus.services.overload import evaluate_load, load_planning_config
        from janus.services.placement import suggest_placement
        from janus.models.attention import AttentionItem

        planning_config = load_planning_config()

        free_slots = compute_free_slots(
            events,
            today,
            work_hours=planning_config.work_hours,
            min_slot_minutes=planning_config.min_focus_slot_minutes,
        )

        _, overload_warning = evaluate_load(
            events,
            tasks,
            today,
            free_slots,
            planning_config,
        )

        placements = suggest_placement(
            free_slots,
            tasks,
            attention_items,
            min_slot_minutes=planning_config.min_focus_slot_minutes,
        )

        if overload_warning is not None:
            attention_items = [
                AttentionItem(
                    title=overload_warning,
                    reason="Calendar overload detected",
                    score=200,
                    category="overload_warning",
                    focus=False,
                ),
                *attention_items,
            ]

    return DailyBriefing(
        events=events,
        attention_items=attention_items,
        suggested_focus=suggested_focus,
        free_slots=free_slots,
        overload_warning=overload_warning,
        placements=placements,
        has_calendar=calendar_configured,
    )
