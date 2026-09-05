from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .attention import AttentionItem
    from .event import Event
    from .time_block import Placement, TimeBlock

@dataclass
class DailyBriefing:
    events: list["Event"]
    attention_items: list["AttentionItem"] = field(default_factory=list)
    suggested_focus: list["AttentionItem"] = field(default_factory=list)
    free_slots: list["TimeBlock"] = field(default_factory=list)
    overload_warning: str | None = None
    placements: list["Placement"] = field(default_factory=list)
    has_calendar: bool = True
