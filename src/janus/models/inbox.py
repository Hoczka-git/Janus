"""Inbox item model for Janus — raw captured items waiting for triage."""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

CAPTURE_SOURCES = ("telegram", "cli", "manual", "research", "email", "other")
TRIAGE_STATES = ("pending", "discarded", "converted", "follow_up")


@dataclass
class InboxItem:
    """A captured item waiting for triage. Not yet an action — a candidate for one.

    Canonical storage is a markdown file (data/inbox.md). This dataclass is the
    in-memory representation; serialization follows the existing Janus pattern
    (markdown_tasks.py-style line parsing).
    """

    id: str                              # stable identity for referencing
    captured_text: str                   # the raw text as captured
    source: str = "manual"               # how it arrived
    captured_at: datetime | None = None  # when it was captured
    context: str = ""                    # optional: where/why
    triage_state: str = "pending"        # pending | discarded | converted | follow_up
    triage_note: str = ""                # why it was routed this way
    triage_at: datetime | None = None    # when triage happened
    linked_goal_title: str = ""          # optional: goal this item relates to
    linked_research_title: str = ""      # optional: research artifact this came from

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("InboxItem.id must not be empty")
        if not self.captured_text or not self.captured_text.strip():
            raise ValueError("InboxItem.captured_text must not be empty")
        if self.source not in CAPTURE_SOURCES:
            raise ValueError(
                f"Invalid source: {self.source!r}. "
                f"Allowed: {', '.join(CAPTURE_SOURCES)}"
            )
        if self.triage_state not in TRIAGE_STATES:
            raise ValueError(
                f"Invalid triage_state: {self.triage_state!r}. "
                f"Allowed: {', '.join(TRIAGE_STATES)}"
            )
        if self.captured_at is None:
            self.captured_at = datetime.now()
