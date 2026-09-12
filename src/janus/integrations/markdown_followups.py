"""Markdown follow-up loader for Janus — parses data/followups.md."""

import logging
import re
from pathlib import Path
from datetime import date, datetime

from janus.models.follow_up import FollowUp, FOLLOWUP_STATES, PRIORITIES

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FOLLOWUPS_PATH = PROJECT_ROOT / "data" / "followups.md"


def load_followups(
    path: Path | None = None,
    trace_id: str | None = None,
) -> list[FollowUp]:
    """Load all follow-ups from data/followups.md.

    Returns [] if file is missing.
    """
    fp = path if path is not None else FOLLOWUPS_PATH
    if not fp.exists():
        return []

    items: list[FollowUp] = []
    lines_scanned = 0

    with fp.open() as f:
        for line_num, line in enumerate(f, start=1):
            lines_scanned += 1
            line = line.strip()
            if not line.startswith("fu-"):
                continue
            item = _parse_followup_line(line, line_num)
            if item is not None:
                items.append(item)

    logger.debug("Loaded %d follow-ups from %s", len(items), fp)
    return items


def _parse_followup_line(line: str, line_num: int) -> FollowUp:
    """Parse one line → FollowUp. Raises ValueError on bad metadata."""
    # Format: fu-<id> | <title> | state: <state> | priority: <n> | due: <iso> | ...
    parts = line.split(" | ", 1)
    id_part = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    if not id_part.startswith("fu-"):
        raise ValueError(f"Invalid followup line {line_num}: missing fu- prefix")

    item_id = id_part[3:]  # strip "fu-"

    # Extract title (before first metadata key) and metadata
    meta_match = re.search(
        r"\b(state:|priority:|due:|scheduled:|assigned_to:|created_at:|completed_at:|created_by:|note:|goal:|linked_task:|converted_to_task:)\s*",
        rest,
    )
    if meta_match:
        title = rest[:meta_match.start()].strip()
        metadata = rest[meta_match.start():]
    else:
        title = rest.strip()
        metadata = ""

    if not title:
        raise ValueError(f"Empty title in follow-up at line {line_num}")

    # Parse metadata fields
    state_raw = _parse_field(metadata, r"state:\s*(\S+)", "state", line_num, default="pending")
    state = state_raw if state_raw else "pending"
    priority_raw = _parse_field(metadata, r"priority:\s*(\S+)", "priority", line_num, default="1")
    priority = int(priority_raw) if priority_raw else 1

    due_match = re.search(r"due:\s*(\S+)", metadata)
    due_date = None
    if due_match:
        try:
            due_date = date.fromisoformat(due_match.group(1))
        except ValueError:
            raise ValueError(f"Invalid due date in follow-up at line {line_num}: {due_match.group(1)}")

    sched_match = re.search(r"scheduled:\s*(\S+)", metadata)
    scheduled_for = None
    if sched_match:
        try:
            scheduled_for = date.fromisoformat(sched_match.group(1))
        except ValueError:
            raise ValueError(f"Invalid scheduled date in follow-up at line {line_num}: {sched_match.group(1)}")

    assigned_raw = _parse_field(metadata, r"assigned_to:\s*(\S+)", "assigned_to", line_num, default="")
    assigned_to = assigned_raw if assigned_raw else ""
    created_at_str = _parse_field(metadata, r"created_at:\s*(\S+)", "created_at", line_num, default=None)
    created_at = None
    if created_at_str:
        try:
            created_at = datetime.fromisoformat(created_at_str)
        except ValueError:
            raise ValueError(f"Invalid created_at in follow-up at line {line_num}: {created_at_str}")

    completed_at_str = _parse_field(metadata, r"completed_at:\s*(\S+)", "completed_at", line_num, default=None)
    completed_at = None
    if completed_at_str:
        try:
            completed_at = datetime.fromisoformat(completed_at_str)
        except ValueError:
            raise ValueError(f"Invalid completed_at in follow-up at line {line_num}: {completed_at_str}")

    created_by_raw = _parse_field(metadata, r"created_by:\s*(\S+)", "created_by", line_num, default="")
    created_by = created_by_raw if created_by_raw else ""
    note_match = re.search(r"note:\s*([^|]+)", metadata)
    note = note_match.group(1).strip() if note_match else ""

    goal_match = re.search(r"goal:\s*([^|]+)", metadata)
    linked_goal_title = goal_match.group(1).strip() if goal_match else ""

    linked_task_match = re.search(r"linked_task:\s*([^|]+)", metadata)
    linked_task_title = linked_task_match.group(1).strip() if linked_task_match else ""

    converted_match = re.search(r"converted_to_task:\s*([^|]+)", metadata)
    converted_to_task_title = converted_match.group(1).strip() if converted_match else ""

    return FollowUp(
        id=item_id,
        title=title,
        originating_inbox_id=None,
        state=state,
        priority=priority,
        due_date=due_date,
        scheduled_for=scheduled_for,
        assigned_to=assigned_to,
        created_at=created_at,
        completed_at=completed_at,
        created_by=created_by,
        note=note,
        linked_goal_title=linked_goal_title or "",
        linked_task_title=linked_task_title or None,
        converted_to_task_title=converted_to_task_title,
    )


def _parse_field(metadata: str, pattern: str, field_name: str, line_num: int, default: str | None) -> str | None:
    """Extract a single metadata field value, returning default if not found."""
    match = re.search(pattern, metadata)
    if not match:
        return default
    return match.group(1)


def _format_followup_line(fu: FollowUp) -> str:
    """Serialize FollowUp → line (only non-default fields emitted)."""
    parts = [f"fu-{fu.id} | {fu.title}"]

    if fu.state != "pending":
        parts.append(f"state: {fu.state}")
    if fu.priority != 1:
        parts.append(f"priority: {fu.priority}")
    if fu.due_date is not None:
        parts.append(f"due: {fu.due_date.isoformat()}")
    if fu.scheduled_for is not None:
        parts.append(f"scheduled: {fu.scheduled_for.isoformat()}")
    if fu.assigned_to:
        parts.append(f"assigned_to: {fu.assigned_to}")
    if fu.created_at is not None:
        parts.append(f"created_at: {fu.created_at.isoformat()}")
    if fu.completed_at is not None:
        parts.append(f"completed_at: {fu.completed_at.isoformat()}")
    if fu.created_by:
        parts.append(f"created_by: {fu.created_by}")
    if fu.note:
        parts.append(f"note: {fu.note}")
    if fu.linked_goal_title:
        parts.append(f"goal: {fu.linked_goal_title}")
    if fu.linked_task_title:
        parts.append(f"linked_task: {fu.linked_task_title}")
    if fu.converted_to_task_title:
        parts.append(f"converted_to_task: {fu.converted_to_task_title}")

    return " | ".join(parts)


def save_followup(fu: FollowUp) -> None:
    """Append a new FollowUp to data/followups.md (append mode, create file if needed)."""
    line = _format_followup_line(fu)
    with FOLLOWUPS_PATH.open("a") as f:
        f.write(line + "\n")


def update_followup(fu: FollowUp) -> None:
    """In-place rewrite of one follow-up by id."""
    from janus.integrations.data_protection import (
        protected_write,
        compute_content_hash,
    )

    raw_content = FOLLOWUPS_PATH.read_text()
    lines = raw_content.splitlines()
    found = False
    new_lines: list[str] = []
    for line in lines:
        if line.startswith(f"fu-{fu.id} |"):
            new_lines.append(_format_followup_line(fu))
            found = True
        else:
            new_lines.append(line)

    if not found:
        raise ValueError(f"Follow-up not found: {fu.id}")

    content = "\n".join(new_lines) + "\n"
    protected_write(
        FOLLOWUPS_PATH,
        content,
        expected_hash=compute_content_hash(raw_content),
        written_by="markdown_followups.update_followup",
    )
