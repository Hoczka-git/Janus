from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .attention import AttentionItem
    from .event import Event

@dataclass
class DailyBriefing:
    events: list["Event"]
    attention_items: list["AttentionItem"] = field(default_factory=list)
    suggested_focus: "AttentionItem | None" = None
