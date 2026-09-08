"""Follow-up model for Janus — tracked pending actions before or instead of tasks."""

from dataclasses import dataclass
from datetime import date, datetime

FOLLOWUP_STATES = ("pending", "scheduled", "in_progress", "blocked", "completed", "deferred")
PRIORITIES = (1, 2, 3, 4, 5)  # 1 = lowest, 5 = highest


@dataclass
class FollowUp:
    """An actionable item that needs tracking over time, before or instead of
    becoming a Janus Task.

    A FollowUp is born from triage of an InboxItem. It can later be converted
    into a Janus Task when it is ready to become active work, or completed
    directly if it is a lightweight action.
    """

    id: str                              # stable identity (carried from InboxItem.id or new)
    title: str                           # human-readable action title
    originating_inbox_id: str | None = None  # which InboxItem this came from
    state: str = "pending"               # pending | scheduled | in_progress | blocked | completed | deferred
    priority: int = 1                    # 1-5
    due_date: date | None = None         # when the follow-up should be done by
    scheduled_for: date | None = None    # when it is intended to be worked on
    assigned_to: str = ""                # who owns it; "" = unassigned
    created_at: datetime | None = None
    completed_at: datetime | None = None
    created_by: str = ""                 # who created it (e.g. "telegram", "cli")
    note: str = ""                       # free-text context / instructions
    linked_goal_title: str = ""          # optional goal this contributes to
    linked_task_title: str | None = None # optional: Janus Task this is a follow-up for
    converted_to_task_title: str = ""    # set when this FollowUp → Task conversion happens

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("FollowUp.id must not be empty")
        if not self.title or not self.title.strip():
            raise ValueError("FollowUp.title must not be empty")
        if self.state not in FOLLOWUP_STATES:
            raise ValueError(
                f"Invalid state: {self.state!r}. "
                f"Allowed: {', '.join(FOLLOWUP_STATES)}"
            )
        if self.priority not in PRIORITIES:
            raise ValueError(
                f"Invalid priority: {self.priority!r}. "
                f"Allowed: {PRIORITIES}"
            )
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.linked_goal_title is None:
            self.linked_goal_title = ""
        if self.linked_task_title is None:
            self.linked_task_title = ""
