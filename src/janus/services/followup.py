"""Follow-up service for Janus — CRUD and lifecycle operations."""

import logging
import uuid
from datetime import date, datetime
from pathlib import Path

from janus._log import emit
from janus.models.follow_up import FollowUp, FOLLOWUP_STATES, PRIORITIES
from janus.integrations.markdown_followups import (
    FOLLOWUPS_PATH as _FOLLOWUPS_PATH_MOD,
    save_followup,
    update_followup,
    load_followups,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FOLLOWUPS_PATH = PROJECT_ROOT / "data" / "followups.md"

logger = logging.getLogger(__name__)


def add_followup(
    title: str,
    due_date: date | None = None,
    scheduled_for: date | None = None,
    priority: int = 1,
    note: str = "",
    created_by: str = "cli",
    originating_inbox_id: str | None = None,
    linked_goal_title: str = "",
) -> FollowUp:
    """Validate, create, append to data/followups.md, return it."""
    if not title or not title.strip():
        raise ValueError("title must not be empty")
    if priority not in PRIORITIES:
        raise ValueError(f"Invalid priority: {priority!r}")
    if due_date is not None:
        try:
            date.fromisoformat(due_date.isoformat())
        except ValueError:
            raise ValueError(f"Invalid due_date: {due_date}")
    if scheduled_for is not None:
        try:
            date.fromisoformat(scheduled_for.isoformat())
        except ValueError:
            raise ValueError(f"Invalid scheduled_for: {scheduled_for}")

    fu_id = "fu-" + uuid.uuid4().hex[:8]
    fu = FollowUp(
        id=fu_id,
        title=title.strip(),
        originating_inbox_id=originating_inbox_id,
        priority=priority,
        due_date=due_date,
        scheduled_for=scheduled_for,
        note=note.strip(),
        created_by=created_by,
        linked_goal_title=linked_goal_title.strip(),
    )
    save_followup(fu)

    emit(logger, "service.followup.mutated",
         trace_id=None, span_id="service",
         operation="add", followup_id=fu_id,
         message=f"Follow-up '{fu_id}' added")

    # Bidirectional link: if linked to a goal, append fu.id to
    # Goal.followup_ids.
    if fu.linked_goal_title:
        try:
            from janus.services.goals import update_goal_fields
            update_goal_fields(fu.linked_goal_title, add_followup_id=fu.id)
        except ValueError as exc:
            logger.warning(
                "Follow-up %s references unknown goal %r: %s",
                fu_id, fu.linked_goal_title, exc,
            )

    return fu


def get_followup(fu_id: str) -> FollowUp:
    """Load single follow-up by exact id. Raises ValueError if not found."""
    items = load_followups(path=FOLLOWUPS_PATH)
    for fu in items:
        if fu.id == fu_id:
            return fu
    raise ValueError(f"Follow-up not found: {fu_id}")


def list_followups(state: str | None = None) -> list[FollowUp]:
    """Load all; optional filter by state."""
    items = load_followups(path=FOLLOWUPS_PATH)
    if state is None:
        return items
    return [fu for fu in items if fu.state == state]


def set_followup_state(fu_id: str, state: str, note: str = "") -> FollowUp:
    """Transition a follow-up to a new state. Validates against FOLLOWUP_STATES.

    Does NOT enforce the design spec's invalid-transition rules — those are
    documented as guidelines, not hard blocks (design §7.2).
    """
    if state not in FOLLOWUP_STATES:
        raise ValueError(f"Invalid state: {state!r}")

    fu = get_followup(fu_id)
    fu.state = state
    if note:
        fu.note = (fu.note + " " + note.strip()).strip()
    update_followup(fu)

    emit(logger, "service.followup.mutated",
         trace_id=None, span_id="service",
         operation="set_state", followup_id=fu_id,
         new_state=state,
         message=f"Follow-up '{fu_id}' state set to {state}")

    return fu


def schedule_followup(
    fu_id: str,
    scheduled_for: date | None = None,
    due_date: date | None = None,
) -> FollowUp:
    """Set scheduled_for and/or due_date on a follow-up."""
    fu = get_followup(fu_id)

    if scheduled_for is not None:
        try:
            date.fromisoformat(scheduled_for.isoformat())
        except ValueError:
            raise ValueError(f"Invalid scheduled_for: {scheduled_for}")
        fu.scheduled_for = scheduled_for

    if due_date is not None:
        try:
            date.fromisoformat(due_date.isoformat())
        except ValueError:
            raise ValueError(f"Invalid due_date: {due_date}")
        fu.due_date = due_date

    update_followup(fu)

    emit(logger, "service.followup.mutated",
         trace_id=None, span_id="service",
         operation="schedule", followup_id=fu_id,
         message=f"Follow-up '{fu_id}' scheduled")

    return fu


def complete_followup(fu_id: str) -> FollowUp:
    """Set state='completed', completed_at=now. Raises ValueError if not found."""
    fu = get_followup(fu_id)
    fu.state = "completed"
    fu.completed_at = datetime.now()
    update_followup(fu)

    emit(logger, "service.followup.mutated",
         trace_id=None, span_id="service",
         operation="complete", followup_id=fu_id,
         message=f"Follow-up '{fu_id}' completed")

    return fu


def convert_followup_to_task(fu_id: str, task_title: str) -> FollowUp:
    """Mark follow-up completed + set converted_to_task_title.

    The actual Task creation is done by the caller (CLI) via
    services.tasks.add_task. This service method only closes the follow-up
    and records the trace. Returns the updated FollowUp.
    """
    if not task_title or not task_title.strip():
        raise ValueError("task_title must not be empty")

    fu = get_followup(fu_id)
    fu.state = "completed"
    fu.completed_at = datetime.now()
    fu.converted_to_task_title = task_title.strip()
    update_followup(fu)

    emit(logger, "service.followup.mutated",
         trace_id=None, span_id="service",
         operation="convert_to_task", followup_id=fu_id,
         task_title=task_title,
         message=f"Follow-up '{fu_id}' converted to task '{task_title}'")

    return fu
