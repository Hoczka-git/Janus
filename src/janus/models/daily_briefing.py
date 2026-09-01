from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .attention import AttentionItem
    from .event import Event

# Maximum number of attention items to display in the "Requires attention"
# section of the daily briefing.
MAX_ATTENTION_ITEMS = 9

# Maximum number of items to surface as "Suggested focus".
MAX_FOCUS_ITEMS = 3


@dataclass
class DailyBriefing:
    events: list["Event"]
    attention_items: list["AttentionItem"] = field(default_factory=list)
    suggested_focus: list["AttentionItem"] = field(default_factory=list)
