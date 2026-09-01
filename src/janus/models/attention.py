"""Attention engine models for Janus."""

from dataclasses import dataclass


@dataclass
class AttentionItem:
    """A single item that deserves the user's attention, with a reason and score.

    ``focus`` is True when the item is among the suggested-focus set (the top
    scoring items surfaced by the daily briefing). This flag is assigned
    deterministically at briefing-assembly time based on score ordering, never
    mutated by the attention engine itself.
    """

    title: str
    reason: str
    score: int
    category: str
    focus: bool = False
