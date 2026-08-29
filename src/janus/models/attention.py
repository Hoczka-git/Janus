"""Attention engine models for Janus."""

from dataclasses import dataclass


@dataclass
class AttentionItem:
    """A single item that deserves the user's attention, with a reason and score."""

    title: str
    reason: str
    score: int
    category: str
